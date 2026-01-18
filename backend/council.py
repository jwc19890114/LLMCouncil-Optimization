"""3-stage LLM Council orchestration (with agents + trace)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Tuple

from .agents_store import AgentConfig, get_models as get_agent_models, list_agents
from .kb_store import KBStore
from .kb_retrieval import KBHybridRetriever
from .llm_client import parse_model_spec, provider_key_configured, query_model
from .settings_store import get_settings
from .storage import get_conversation
from .trace_store import append as trace_append
from .web_search import ddg_search
from .neo4j_store import Neo4jKGStore


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


_agent_web_search_sem = asyncio.Semaphore(3)


def _agent_vote_weight(agent: AgentConfig) -> float:
    influence = float(agent.influence_weight)
    seniority = max(0, int(agent.seniority_years))
    return max(0.0, influence) * (1.0 + seniority / 10.0)


def _agent_system_messages(agent: AgentConfig) -> List[Dict[str, str]]:
    settings = get_settings()
    parts: List[str] = []
    if agent.persona and agent.persona.strip():
        parts.append(agent.persona.strip())

    if settings.output_language == "zh":
        parts.append("输出要求：全程使用简体中文回答。除非用户明确要求，否则不要输出英文。")
    elif settings.output_language == "en":
        parts.append("Output requirement: respond in English.")

    if not parts:
        return []
    return [{"role": "system", "content": "\n\n".join(parts)}]


async def _query_agent(
    *,
    conversation_id: str | None,
    stage: str,
    agent: AgentConfig,
    messages: List[Dict[str, str]],
    timeout: float,
) -> Dict[str, Any] | None:
    started = time.perf_counter()
    response = None
    error = None
    try:
        response = await query_model(agent.model_spec, messages, timeout=timeout)
        return response
    except Exception as e:
        error = str(e)
        return None
    finally:
        if conversation_id:
            duration_ms = int((time.perf_counter() - started) * 1000)
            trace_append(
                conversation_id,
                {
                    "type": "llm_call",
                    "stage": stage,
                    "agent": {
                        "id": agent.id,
                        "name": agent.name,
                        "model_spec": agent.model_spec,
                        "influence_weight": agent.influence_weight,
                        "seniority_years": agent.seniority_years,
                    },
                    "request": {"messages": messages, "timeout": timeout},
                    "response": response,
                    "ok": response is not None,
                    "duration_ms": duration_ms,
                    "error": error,
                },
            )


def _get_enabled_agents() -> List[AgentConfig]:
    return [a for a in list_agents() if a.enabled]


def _get_conversation_agents(conversation_id: str | None) -> List[AgentConfig]:
    enabled = _get_enabled_agents()
    if not conversation_id:
        return enabled
    conv = get_conversation(conversation_id)
    agent_ids = conv.get("agent_ids") if isinstance(conv, dict) else None
    if not agent_ids:
        return enabled
    enabled_by_id = {a.id: a for a in enabled}
    selected = [enabled_by_id[aid] for aid in agent_ids if aid in enabled_by_id]
    return selected or enabled


def _get_conversation_kb_doc_ids(conversation_id: str | None) -> List[str]:
    if not conversation_id:
        return []
    conv = get_conversation(conversation_id)
    if not isinstance(conv, dict):
        return []
    ids = conv.get("kb_doc_ids") or []
    if not isinstance(ids, list):
        return []
    out: List[str] = []
    seen = set()
    for d in ids:
        if not isinstance(d, str):
            continue
        s = d.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _get_conversation_chairman_model(conversation_id: str | None) -> str:
    if not conversation_id:
        return ""
    conv = get_conversation(conversation_id)
    if not isinstance(conv, dict):
        return ""
    return str(conv.get("chairman_model") or "").strip()


def _get_conversation_chairman_agent_id(conversation_id: str | None) -> str:
    if not conversation_id:
        return ""
    conv = get_conversation(conversation_id)
    if not isinstance(conv, dict):
        return ""
    return str(conv.get("chairman_agent_id") or "").strip()


async def _build_realtime_context(user_query: str, conversation_id: str | None) -> str:
    settings = get_settings()
    chunks: List[str] = []
    if settings.enable_date_context:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).astimezone()
        chunks.append(f"当前日期时间：{now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    if settings.enable_web_search and settings.web_search_results > 0:
        try:
            results = await ddg_search(user_query, max_results=settings.web_search_results)
            if conversation_id:
                trace_append(
                    conversation_id,
                    {
                        "type": "web_search",
                        "query": user_query,
                        "results": [r.__dict__ for r in results],
                    },
                )
            if results:
                lines = ["网页检索结果（仅供参考，请自行甄别真伪）："]
                for i, r in enumerate(results, start=1):
                    snippet = f" - {r.snippet}" if r.snippet else ""
                    lines.append(f"{i}. {r.title} ({r.url}){snippet}")
                chunks.append("\n".join(lines))
        except Exception as e:
            if conversation_id:
                trace_append(conversation_id, {"type": "web_search_error", "error": str(e)})

    return "\n\n".join(chunks).strip()


_kb = KBStore()
_kb_retriever = KBHybridRetriever(_kb)


async def stage0_preprocess(user_query: str, conversation_id: str | None) -> Dict[str, Any] | None:
    """
    Optional pre-processing before Stage1:
    - Summarize / segment uploaded KB documents bound to the conversation
    - Propose key questions / subtasks
    Returns structured JSON (best-effort). The caller can decide how to inject it.
    """
    settings = get_settings()
    if not settings.enable_preprocess:
        return None
    if not conversation_id:
        return None

    doc_ids = _get_conversation_kb_doc_ids(conversation_id)
    if not doc_ids:
        return None

    docs: List[Dict[str, Any]] = []
    total_chars = 0
    max_total_chars = 24000
    per_doc_limit = 8000
    for doc_id in doc_ids[:12]:
        doc = _kb.get_document(doc_id)
        if not doc:
            continue
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        text = text[:per_doc_limit]
        total_chars += len(text)
        if total_chars > max_total_chars:
            break
        docs.append(
            {
                "doc_id": doc.get("id") or doc_id,
                "title": doc.get("title") or "",
                "source": doc.get("source") or "",
                "text": text,
            }
        )

    if not docs:
        return None

    models = get_agent_models()
    chairman_spec = _get_conversation_chairman_model(conversation_id) or models.get("chairman_model") or ""
    chairman_agent = next((a for a in list_agents() if a.enabled and a.model_spec == chairman_spec), None)

    system = (
        "你是“文档预处理器”。\n"
        "你的任务：根据用户问题与上传的文档内容，生成预处理摘要，帮助后续专家更快理解材料并提出更好的回答。\n"
        "要求：\n"
        "- 必须使用简体中文\n"
        "- 输出必须是严格 JSON（不要 Markdown，不要解释文字）\n"
        '- JSON 结构：{"summary":"...","outline":[...],"key_questions":[...],"suggested_subtasks":[...],"used_docs":[...]}。\n'
        "- summary 不超过 200 字；每个列表最多 8 条；used_docs 里只放 doc_id。\n"
    )
    user = (
        "用户问题：\n"
        + (user_query or "").strip()
        + "\n\n上传文档（可能截断）：\n"
        + "\n\n".join(
            [
                f"KB[{d['doc_id']}]\n标题：{d.get('title')}\n来源：{d.get('source')}\n内容：\n{d.get('text')}"
                for d in docs
            ]
        )
    )

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage0", "doc_ids": [d["doc_id"] for d in docs]})

    resp = await _query_agent(
        conversation_id=conversation_id,
        stage="stage0",
        agent=chairman_agent
        if chairman_agent
        else AgentConfig(id="preprocess", name="Preprocess", model_spec=chairman_spec or models.get("chairman_model") or ""),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout=90.0,
    )
    raw = (resp or {}).get("content") or ""
    data = _extract_json_object(raw)

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_complete", "stage": "stage0", "ok": bool(data), "raw": raw, "data": data})

    return data


async def _build_agent_knowledge(agent: AgentConfig, user_query: str, conversation_id: str | None) -> str:
    """
    Build agent-specific knowledge context:
    - Knowledge base snippets scoped to agent.kb_doc_ids (if set) or agent.kb_categories (if set)
    - Neo4j subgraph (if agent.graph_id configured)
    """
    parts: List[str] = []

    # Agent-specific web search (best-effort)
    try:
        settings = get_settings()
        if settings.enable_agent_web_search and settings.agent_web_search_results > 0:
            q = (user_query or "").strip()
            if q:
                # Simple personalization: include agent name as a query hint.
                query = f"{q} {agent.name}".strip()
                async with _agent_web_search_sem:
                    results = await ddg_search(query, max_results=int(settings.agent_web_search_results))
                if conversation_id:
                    trace_append(
                        conversation_id,
                        {
                            "type": "web_search_agent",
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "query": query,
                            "results": [r.__dict__ for r in results],
                        },
                    )
                if results:
                    lines = [f"专家专属网页检索结果（Agent={agent.name}，仅供参考）："]
                    for i, r in enumerate(results, start=1):
                        snippet = f" - {r.snippet}" if r.snippet else ""
                        lines.append(f"{i}. {r.title} ({r.url}){snippet}")
                    parts.append("\n".join(lines))
    except Exception as e:
        if conversation_id:
            trace_append(
                conversation_id,
                {"type": "web_search_agent_error", "agent_id": agent.id, "agent_name": agent.name, "error": str(e)},
            )

    # KB
    try:
        settings = get_settings()
        models = get_agent_models()
        conv_doc_ids = _get_conversation_kb_doc_ids(conversation_id)
        categories = None
        doc_ids = None
        if conv_doc_ids:
            doc_ids = list(conv_doc_ids)
            if agent.kb_doc_ids:
                allow = set([d.strip() for d in (agent.kb_doc_ids or []) if isinstance(d, str) and d.strip()])
                doc_ids = [d for d in doc_ids if d in allow]
        else:
            if not agent.kb_doc_ids and getattr(agent, "kb_categories", None):
                categories = list(agent.kb_categories or [])
            doc_ids = list(agent.kb_doc_ids) if agent.kb_doc_ids else None

        agent_filter_id = None if (doc_ids or categories) else agent.id
        if isinstance(doc_ids, list) and len(doc_ids) == 0:
            kb_hits = []
        else:
            kb_hits = await _kb_retriever.search(
                query=user_query,
                agent_id=agent_filter_id,
                doc_ids=doc_ids,
                categories=categories,
                limit=5,
                mode=settings.kb_retrieval_mode,
                embedding_model_spec=settings.kb_embedding_model,
                enable_rerank=bool(settings.kb_enable_rerank),
                rerank_model_spec=(settings.kb_rerank_model or models.get("chairman_model") or ""),
                semantic_pool=int(settings.kb_semantic_pool),
                initial_k=int(settings.kb_initial_k),
            )
        if kb_hits:
            lines = ["专家知识库命中："]
            for i, h in enumerate(kb_hits, start=1):
                title = h.get("title") or h.get("doc_id")
                source = h.get("source") or ""
                snippet = (h.get("text") or "").strip()
                if len(snippet) > 500:
                    snippet = snippet[:500] + "..."
                meta = []
                if h.get("categories"):
                    meta.append(f"categories={','.join(h.get('categories') or [])}")
                if h.get("retrieval"):
                    meta.append(f"method={','.join(h.get('retrieval') or [])}")
                if h.get("rerank_score") is not None:
                    meta.append(f"rerank={h.get('rerank_score'):.2f}")
                lines.append(f"{i}. {title} {('(' + source + ')') if source else ''}\n{snippet}")
                if meta:
                    lines.append("   " + " ".join(meta))
            parts.append("\n".join(lines))
            if conversation_id:
                trace_append(
                    conversation_id,
                    {
                        "type": "kb_hits",
                        "agent_id": agent.id,
                        "hits": kb_hits,
                        "kb_settings": {
                            "mode": settings.kb_retrieval_mode,
                            "embedding_model": settings.kb_embedding_model,
                            "enable_rerank": settings.kb_enable_rerank,
                            "rerank_model": settings.kb_rerank_model or models.get("chairman_model") or "",
                        },
                    },
                )
    except Exception as e:
        if conversation_id:
            trace_append(conversation_id, {"type": "kb_error", "agent_id": agent.id, "error": str(e)})

    # KG (Neo4j)
    if agent.graph_id:
        try:
            store = Neo4jKGStore()
            try:
                sub = store.query_subgraph(agent.graph_id, user_query)
            finally:
                store.close()
            nodes = sub.get("nodes") or []
            edges = sub.get("edges") or []
            if nodes:
                lines = [f"专家知识图谱子图（graph_id={agent.graph_id}）："]
                lines.append("节点：")
                for n in nodes[:25]:
                    lines.append(f"- {n.get('label')} [{n.get('type')}]")
                if edges:
                    lines.append("关系：")
                    for r in edges[:40]:
                        lines.append(f"- {r.get('from')} -[{r.get('label')}]-> {r.get('to')}")
                parts.append("\n".join(lines))
            if conversation_id:
                trace_append(conversation_id, {"type": "kg_subgraph", "agent_id": agent.id, "graph_id": agent.graph_id, "subgraph": sub})
        except Exception as e:
            if conversation_id:
                trace_append(conversation_id, {"type": "kg_error", "agent_id": agent.id, "graph_id": agent.graph_id, "error": str(e)})

    return "\n\n".join([p for p in parts if p.strip()]).strip()

async def stage1_collect_responses(
    user_query: str,
    conversation_id: str | None = None,
    preprocess: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Stage 1: Collect individual responses from all enabled agents."""
    agents = _get_conversation_agents(conversation_id)
    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage1"})

    context_text = await _build_realtime_context(user_query, conversation_id)
    preprocess_text = ""
    if isinstance(preprocess, dict):
        summary = str(preprocess.get("summary") or "").strip()
        key_questions = preprocess.get("key_questions") if isinstance(preprocess.get("key_questions"), list) else []
        subtasks = preprocess.get("suggested_subtasks") if isinstance(preprocess.get("suggested_subtasks"), list) else []
        used_docs = preprocess.get("used_docs") if isinstance(preprocess.get("used_docs"), list) else []
        lines = ["【文档预处理摘要（供专家参考）】"]
        if summary:
            lines.append(f"摘要：{summary}")
        if key_questions:
            lines.append("关键问题：")
            for q in key_questions[:8]:
                s = str(q).strip()
                if s:
                    lines.append(f"- {s}")
        if subtasks:
            lines.append("建议拆分任务：")
            for t in subtasks[:8]:
                s = str(t).strip()
                if s:
                    lines.append(f"- {s}")
        if used_docs:
            ids = [str(x).strip() for x in used_docs[:12] if str(x).strip()]
            if ids:
                lines.append("涉及文档： " + ", ".join(ids))
        preprocess_text = "\n".join(lines).strip()

    async def run_one(agent: AgentConfig):
        messages = _agent_system_messages(agent)
        if context_text:
            messages.append({"role": "system", "content": f"可用外部信息：\n{context_text}"})
        if preprocess_text:
            messages.append({"role": "system", "content": preprocess_text})
        knowledge = await _build_agent_knowledge(agent, user_query, conversation_id)
        if knowledge:
            messages.append({"role": "system", "content": knowledge})
        messages.append({"role": "user", "content": user_query})
        return agent, await _query_agent(
            conversation_id=conversation_id,
            stage="stage1",
            agent=agent,
            messages=messages,
            timeout=120.0,
        )

    results = await asyncio.gather(*[run_one(a) for a in agents])
    stage1_results: List[Dict[str, Any]] = []
    for agent, resp in results:
        if resp is None:
            continue
        stage1_results.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "model": agent.model_spec,
                "influence_weight": agent.influence_weight,
                "seniority_years": agent.seniority_years,
                "response": resp.get("content", "") if isinstance(resp, dict) else "",
            }
        )

    if conversation_id:
        trace_append(
            conversation_id,
            {"type": "stage_complete", "stage": "stage1", "agents_count": len(agents), "ok_count": len(stage1_results)},
        )
    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    conversation_id: str | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Stage 2: Each enabled agent ranks the anonymized stage1 responses."""
    agents = _get_conversation_agents(conversation_id)
    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage2"})

    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...
    label_to_agent = {
        f"Response {label}": {
            "agent_id": result.get("agent_id"),
            "agent_name": result.get("agent_name"),
            "model_spec": result.get("model"),
        }
        for label, result in zip(labels, stage1_results)
    }

    responses_text = "\n\n".join(
        [f"Response {label}:\n{result['response']}" for label, result in zip(labels, stage1_results)]
    )

    ranking_prompt = f"""你正在评估多个匿名回答，这些回答都在回答同一个问题。

问题：{user_query}

以下是不同专家的回答（已匿名，使用 Response A/B/C... 代号）：

{responses_text}

你的任务：
1. 逐个评估每个回答：指出优点、缺点、关键遗漏与潜在错误。
2. 最后在你的回答末尾给出最终排名。

重要要求：
- 除“最终排名”区块外，其余内容必须使用简体中文。
- 最终排名必须严格使用如下格式（为了便于机器解析，必须是英文标签）：
  - 以一行 `FINAL RANKING:` 开始（全大写，带冒号）
  - 然后用编号列表从好到坏列出
  - 每行格式必须是：数字 + 点 + 空格 + 仅包含 `Response X`（例如：`1. Response A`）
  - 排名区块不要添加任何额外解释

示例（你的整个输出结构应类似，评审内容用中文，排名区块用固定英文标签）：

Response A 对 X 的分析较完整，但遗漏了 Y...
Response B 的结论较准确，但对 Z 的解释不够深入...
Response C 覆盖面最广，论据也更充分...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

现在请给出评估与最终排名："""

    async def run_one(agent: AgentConfig):
        messages = _agent_system_messages(agent) + [{"role": "user", "content": ranking_prompt}]
        return agent, await _query_agent(
            conversation_id=conversation_id,
            stage="stage2",
            agent=agent,
            messages=messages,
            timeout=180.0,
        )

    results = await asyncio.gather(*[run_one(a) for a in agents])
    stage2_results: List[Dict[str, Any]] = []
    for agent, resp in results:
        if resp is None:
            continue
        full_text = resp.get("content", "") if isinstance(resp, dict) else ""
        parsed = parse_ranking_from_text(full_text)
        stage2_results.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "model": agent.model_spec,
                "influence_weight": agent.influence_weight,
                "seniority_years": agent.seniority_years,
                "vote_weight": round(_agent_vote_weight(agent), 4),
                "ranking": full_text,
                "parsed_ranking": parsed,
            }
        )

    if conversation_id:
        trace_append(
            conversation_id,
            {"type": "stage_complete", "stage": "stage2", "agents_count": len(agents), "ok_count": len(stage2_results)},
        )
    return stage2_results, label_to_agent


async def stage2b_roundtable(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    *,
    conversation_id: str | None,
) -> List[Dict[str, Any]]:
    """Extra stage: agents discuss based on persona + web info (best-effort)."""
    settings = get_settings()
    if not settings.enable_roundtable:
        return []

    agents = _get_conversation_agents(conversation_id)
    if not agents:
        return []

    rounds = max(0, min(3, int(settings.roundtable_rounds or 1)))
    if rounds <= 0:
        return []

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage2b", "rounds": rounds})

    context_text = await _build_realtime_context(user_query, conversation_id)
    kb_doc_ids = _get_conversation_kb_doc_ids(conversation_id)
    kb_meta = []
    for did in kb_doc_ids[:20]:
        doc = _kb.get_document(did)
        if doc:
            kb_meta.append({"doc_id": did, "title": doc.get("title") or "", "source": doc.get("source") or ""})

    s1 = "\n\n".join([f"- {r.get('agent_name')}: {r.get('response')}" for r in stage1_results])
    s2 = "\n\n".join([f"- {r.get('agent_name')} 的评审：\n{r.get('ranking')}" for r in stage2_results])

    async def run_one(agent: AgentConfig) -> Dict[str, Any] | None:
        knowledge = await _build_agent_knowledge(agent, user_query, conversation_id)
        messages = _agent_system_messages(agent)
        prompt = (
            "你将参与一轮“专家圆桌讨论”。请以你自己的身份（使用你的专业背景/人设）发表评论，必须基于以下材料：\n"
            "1) 其它专家的初稿与互评\n"
            "2) 网页检索结果（若提供）\n"
            "3) 上传的知识库文档（如有，引用时请标注 KB[doc_id]）\n\n"
            "要求：\n"
            "- 用简体中文\n"
            "- 必须点名回应至少 1 位其它专家（用其 agent_name）\n"
            "- 尽量引用“网页检索结果”的 URL 或 KB[doc_id] 作为依据（如果给了）\n"
            "- 输出长度 150~450 字\n"
        )
        material = (
            f"用户问题：{user_query}\n\n"
            + (f"网页检索结果：\n{context_text}\n\n" if context_text else "")
            + (f"你的可用知识库/图谱信息：\n{knowledge}\n\n" if knowledge else "")
            + (f"上传文档列表：\n{json.dumps(kb_meta, ensure_ascii=False)}\n\n" if kb_meta else "")
            + "阶段1初稿：\n"
            + s1
            + "\n\n阶段2互评：\n"
            + s2
        )
        resp = await _query_agent(
            conversation_id=conversation_id,
            stage="stage2b",
            agent=agent,
            messages=messages + [{"role": "user", "content": prompt + "\n\n" + material}],
            timeout=180.0,
        )
        if not resp:
            return None
        return {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "model": agent.model_spec,
            "message": (resp.get("content") or "").strip(),
        }

    out: List[Dict[str, Any]] = []
    for _ in range(rounds):
        results = await asyncio.gather(*[run_one(a) for a in agents])
        out = [r for r in results if r]

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_complete", "stage": "stage2b", "ok_count": len(out)})
    return out


async def stage2c_fact_check(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    roundtable: List[Dict[str, Any]],
    *,
    conversation_id: str | None,
) -> Dict[str, Any] | None:
    """Extra stage: fact-check with evidence and output structured JSON (best-effort)."""
    settings = get_settings()
    if not settings.enable_fact_check:
        return None

    models = get_agent_models()
    chairman_spec = (_get_conversation_chairman_model(conversation_id) or models.get("chairman_model") or "").strip()
    if not chairman_spec:
        chairman_spec = models.get("chairman_model") or ""

    context_text = await _build_realtime_context(user_query, conversation_id)
    kb_doc_ids = _get_conversation_kb_doc_ids(conversation_id)
    kb_meta = []
    for did in kb_doc_ids[:20]:
        doc = _kb.get_document(did)
        if doc:
            kb_meta.append({"doc_id": did, "title": doc.get("title") or "", "source": doc.get("source") or ""})

    system = (
        "你是“事实核查与证据整理员”。\n"
        "任务：根据专家初稿、互评、圆桌讨论，以及给定的网页检索结果与上传文档列表，抽取关键主张并进行证据归因。\n"
        "要求：\n"
        "- 必须使用简体中文\n"
        "- 输出必须是严格 JSON（不要 Markdown，不要解释文字）\n"
        '- JSON 结构：{"claims":[{"claim":"...","status":"supported|uncertain|refuted","evidence":[{"type":"web|kb|other","ref":"...","note":"..."}],"confidence":0.0}],"open_questions":[...]}。\n'
        "- evidence.ref 若来自网页检索必须包含 URL；若来自上传文档必须用 KB[doc_id]。\n"
        "- 只列最重要的 5~12 条 claims。\n"
    )

    user = (
        f"用户问题：{user_query}\n\n"
        + (f"网页检索结果：\n{context_text}\n\n" if context_text else "网页检索结果：无\n\n")
        + (f"上传文档列表：\n{json.dumps(kb_meta, ensure_ascii=False)}\n\n" if kb_meta else "上传文档列表：无\n\n")
        + "阶段1初稿：\n"
        + json.dumps(stage1_results, ensure_ascii=False)
        + "\n\n阶段2互评：\n"
        + json.dumps(stage2_results, ensure_ascii=False)
        + "\n\n圆桌讨论：\n"
        + json.dumps(roundtable or [], ensure_ascii=False)
    )

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage2c", "model": chairman_spec})

    resp = await _query_agent(
        conversation_id=conversation_id,
        stage="stage2c",
        agent=AgentConfig(id="factcheck", name="FactCheck", model_spec=chairman_spec),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout=180.0,
    )
    raw = (resp or {}).get("content") or ""
    data = _extract_json_object(raw)

    if conversation_id:
        trace_append(
            conversation_id,
            {"type": "stage_complete", "stage": "stage2c", "ok": bool(data), "raw": raw, "data": data},
        )

    return data


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    roundtable: List[Dict[str, Any]] | None = None,
    fact_check: Dict[str, Any] | None = None,
    conversation_id: str | None = None,
) -> Dict[str, Any]:
    """Stage 3: Chairman synthesizes final response."""
    models = get_agent_models()
    agents = list_agents()
    chairman_agent_id = _get_conversation_chairman_agent_id(conversation_id)
    chairman_agent = next((a for a in agents if chairman_agent_id and a.id == chairman_agent_id), None)
    chairman_spec = (
        chairman_agent.model_spec
        if chairman_agent
        else (_get_conversation_chairman_model(conversation_id) or models["chairman_model"])
    )

    if not chairman_agent:
        chairman_agent = next((a for a in agents if a.model_spec == chairman_spec), None)

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_start", "stage": "stage3", "chairman_model": chairman_spec})

    stage1_text = "\n\n".join(
        [
            (
                f"Agent: {r.get('agent_name')} ({r.get('agent_id')})\n"
                f"Model: {r.get('model')}\n"
                f"Influence: {r.get('influence_weight')}, SeniorityYears: {r.get('seniority_years')}\n"
                f"Response: {r.get('response')}"
            )
            for r in stage1_results
        ]
    )

    stage2_text = "\n\n".join(
        [
            (
                f"Agent: {r.get('agent_name')} ({r.get('agent_id')})\n"
                f"Model: {r.get('model')}\n"
                f"VoteWeight: {r.get('vote_weight')}\n"
                f"Ranking: {r.get('ranking')}"
            )
            for r in stage2_results
        ]
    )

    settings = get_settings()
    if settings.output_language == "zh":
        rt_text = ""
        if roundtable:
            rt_lines = []
            for m in (roundtable or [])[:12]:
                rt_lines.append(f"- {m.get('agent_name')}: {m.get('message')}")
            if rt_lines:
                rt_text = "\n".join(rt_lines)
        fc_text = json.dumps(fact_check, ensure_ascii=False) if fact_check else ""

        chairman_prompt = f"""你是“专家委员会”的主席。多位专家针对同一个问题给出了各自的回答，并互相进行了评审与排名。

原始问题：{user_query}

阶段 1：各专家初稿
{stage1_text}

阶段 2：互评与排名
{stage2_text}

阶段 2B：圆桌讨论（可选）
{rt_text or '（无）'}

阶段 2C：事实核查 JSON（可选）
{fc_text or '（无）'}

你的任务：综合以上信息，输出一份最终结论，要求：
- 准确、完整、可操作
- 明确区分事实与推断；必要时给出不确定性与风险提示
- 优先采纳被多方认可/证据更充分的观点，但也要指出少数派的关键反例

请直接给出最终回答（使用简体中文）："""
    else:
        chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple agents have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question.
Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = (_agent_system_messages(chairman_agent) if chairman_agent else []) + [
        {"role": "user", "content": chairman_prompt}
    ]
    resp = await _query_agent(
        conversation_id=conversation_id,
        stage="stage3",
        agent=chairman_agent
        if chairman_agent
        else AgentConfig(id="chairman", name="Chairman", model_spec=chairman_spec),
        messages=messages,
        timeout=240.0,
    )

    if resp is None:
        result = {"model": chairman_spec, "response": "Error: Unable to generate final synthesis."}
    else:
        result = {"model": chairman_spec, "response": resp.get("content", "")}

    if conversation_id:
        trace_append(conversation_id, {"type": "stage_complete", "stage": "stage3", "ok": resp is not None})
    return result


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """Parse the FINAL RANKING section from the model's response."""
    import re

    if "FINAL RANKING:" in ranking_text:
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            numbered_matches = re.findall(r"\d+\.\s*Response [A-Z]", ranking_section)
            if numbered_matches:
                return [re.search(r"Response [A-Z]", m).group() for m in numbered_matches]
            matches = re.findall(r"Response [A-Z]", ranking_section)
            return matches

    matches = re.findall(r"Response [A-Z]", ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_agent: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Calculate aggregate rankings across all models (weighted by agent importance)."""
    model_weighted_sum: Dict[str, float] = {}
    model_weight_total: Dict[str, float] = {}
    model_votes: Dict[str, int] = {}

    label_to_model = {k: v.get("model_spec") for k, v in label_to_agent.items()}
    for ranking in stage2_results:
        ranking_text = ranking.get("ranking") or ""
        vote_weight = float(ranking.get("vote_weight") or 1.0)
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label not in label_to_model:
                continue
            model_spec = label_to_model[label]
            model_weighted_sum[model_spec] = model_weighted_sum.get(model_spec, 0.0) + (position * vote_weight)
            model_weight_total[model_spec] = model_weight_total.get(model_spec, 0.0) + vote_weight
            model_votes[model_spec] = model_votes.get(model_spec, 0) + 1

    aggregate: List[Dict[str, Any]] = []
    for model_spec, weighted_sum in model_weighted_sum.items():
        total_w = model_weight_total.get(model_spec, 0.0) or 1.0
        avg_rank = weighted_sum / total_w
        aggregate.append(
            {
                "model": model_spec,
                "average_rank": round(avg_rank, 3),
                "votes": model_votes.get(model_spec, 0),
                "total_vote_weight": round(total_w, 3),
            }
        )

    aggregate.sort(key=lambda x: x["average_rank"])
    return aggregate


async def generate_conversation_title(user_query: str, conversation_id: str | None = None) -> str:
    """Generate a short title for a conversation based on the first user message."""
    models = get_agent_models()
    title_spec = models["title_model"]
    chairman_spec = models.get("chairman_model") or ""

    settings = get_settings()
    if settings.output_language == "zh":
        title_prompt = f"""请为下面的问题生成一个非常简短的标题（最多 3-5 个中文词语），要求简洁明确，不要引号和标点。

问题：{user_query}

标题："""
    else:
        title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    agents = list_agents()

    def _spec_is_usable(spec: str) -> bool:
        if not spec or not spec.strip():
            return False
        parsed = parse_model_spec(spec)
        configured = provider_key_configured(parsed.provider)
        return configured is not False

    # Prefer configured title model; fall back to chairman, then to any configured agent model.
    candidate_specs: List[str] = []
    for spec in [title_spec, chairman_spec] + [a.model_spec for a in agents]:
        if spec and spec not in candidate_specs:
            candidate_specs.append(spec)

    candidate_specs = [s for s in candidate_specs if _spec_is_usable(s)]

    resp = None
    for spec in candidate_specs:
        title_agent = next((a for a in agents if a.model_spec == spec), None)
        resp = await _query_agent(
            conversation_id=conversation_id,
            stage="title",
            agent=title_agent if title_agent else AgentConfig(id="title", name="Title", model_spec=spec),
            messages=[{"role": "user", "content": title_prompt}],
            timeout=30.0,
        )
        if resp is not None:
            break

    if resp is None:
        return "New Conversation"

    title = (resp.get("content") or "New Conversation").strip()
    title = title.strip("\"'")
    if len(title) > 50:
        title = title[:47] + "..."
    return title


async def run_full_council(user_query: str, conversation_id: str | None = None) -> Tuple[List, List, Dict, Dict]:
    """Run the complete 3-stage council process."""
    preprocess = await stage0_preprocess(user_query, conversation_id)
    stage1_results = await stage1_collect_responses(user_query, conversation_id=conversation_id, preprocess=preprocess)

    if not stage1_results:
        missing = []
        for a in _get_conversation_agents(conversation_id):
            parsed = parse_model_spec(a.model_spec)
            configured = provider_key_configured(parsed.provider)
            if configured is False:
                missing.append(parsed.provider)
        missing = sorted(set(missing))
        if missing:
            return [], [], {
                "model": "error",
                "response": (
                    "No model responded successfully. Missing API key(s) for provider(s): "
                    + ", ".join(missing)
                    + ". Check your .env and try again."
                ),
            }, {}
        return [], [], {"model": "error", "response": "All models failed to respond. Please try again."}, {}

    stage2_results, label_to_agent = await stage2_collect_rankings(
        user_query, stage1_results, conversation_id=conversation_id
    )
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_agent)
    roundtable = await stage2b_roundtable(
        user_query, stage1_results, stage2_results, conversation_id=conversation_id
    )
    fact_check = await stage2c_fact_check(
        user_query, stage1_results, stage2_results, roundtable, conversation_id=conversation_id
    )
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        roundtable=roundtable,
        fact_check=fact_check,
        conversation_id=conversation_id,
    )

    metadata = {
        "label_to_agent": label_to_agent,
        "aggregate_rankings": aggregate_rankings,
        "preprocess": preprocess,
        "roundtable": roundtable,
        "fact_check": fact_check,
        "agents_snapshot": [
            {
                "id": a.id,
                "name": a.name,
                "model_spec": a.model_spec,
                "enabled": a.enabled,
                "influence_weight": a.influence_weight,
                "seniority_years": a.seniority_years,
            }
            for a in list_agents()
        ],
        "models": get_agent_models(),
    }
    return stage1_results, stage2_results, stage3_result, metadata
