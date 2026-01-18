"""FastAPI backend for LLM Council."""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from . import agents_store, trace_store, settings_store
from .llm_client import parse_model_spec, query_model
from .council import (
    calculate_aggregate_rankings,
    generate_conversation_title,
    run_full_council,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage2b_roundtable,
    stage2c_fact_check,
    stage3_synthesize_final,
    stage0_preprocess,
    stage4_generate_report,
)
from .kb_store import KBStore
from .kb_retrieval import KBHybridRetriever
from .entity_type_normalizer import canonicalize_entity_type
from .kg_extractor import DEFAULT_ONTOLOGY, extract_kg_incremental
from .kg_interpret import build_components, interpret_entity, summarize_community
from .neo4j_store import KGChunk, KGEntity, KGRelation, Neo4jKGStore

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="LLM Council API", default_response_class=UTF8JSONResponse)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    # Allow local dev frontends on any port via localhost/127.0.0.1.
    # This avoids common CORS preflight failures when opening the frontend with 127.0.0.1.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    agent_ids: Optional[List[str]] = None


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class AgentUpsertRequest(BaseModel):
    id: Optional[str] = None
    name: str
    model_spec: str
    enabled: bool = True
    persona: str = ""
    influence_weight: float = 1.0
    seniority_years: int = 0
    kb_doc_ids: Optional[List[str]] = None
    kb_categories: Optional[List[str]] = None
    graph_id: str = ""


class AgentModelsRequest(BaseModel):
    chairman_model: Optional[str] = None
    title_model: Optional[str] = None


class AgentPersonaGenerateRequest(BaseModel):
    name: str
    model_spec: Optional[str] = None


class SettingsPatchRequest(BaseModel):
    output_language: Optional[str] = None
    enable_date_context: Optional[bool] = None
    enable_web_search: Optional[bool] = None
    web_search_results: Optional[int] = None
    enable_agent_web_search: Optional[bool] = None
    agent_web_search_results: Optional[int] = None
    kb_retrieval_mode: Optional[str] = None
    kb_embedding_model: Optional[str] = None
    kb_enable_rerank: Optional[bool] = None
    kb_rerank_model: Optional[str] = None
    kb_semantic_pool: Optional[int] = None
    kb_initial_k: Optional[int] = None
    enable_preprocess: Optional[bool] = None
    enable_roundtable: Optional[bool] = None
    enable_fact_check: Optional[bool] = None
    roundtable_rounds: Optional[int] = None
    enable_report_generation: Optional[bool] = None
    report_instructions: Optional[str] = None
    auto_save_report_to_kb: Optional[bool] = None
    auto_bind_report_to_conversation: Optional[bool] = None
    report_kb_category: Optional[str] = None


class KBAddRequest(BaseModel):
    id: Optional[str] = None
    title: str
    source: str = ""
    text: str
    categories: Optional[List[str]] = None
    agent_ids: Optional[List[str]] = None
    # Best-effort: index embeddings after insertion.
    # When omitted, the server will index if an embedding model is configured.
    index_embeddings: Optional[bool] = None
    embedding_model: Optional[str] = None


class KBSearchResponse(BaseModel):
    results: List[Dict[str, Any]]

class KBUpdateRequest(BaseModel):
    categories: Optional[List[str]] = None
    agent_ids: Optional[List[str]] = None


class KBIndexRequest(BaseModel):
    agent_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    embedding_model: Optional[str] = None
    pool: int = 5000


class KBAddBatchRequest(BaseModel):
    documents: List[KBAddRequest]
    # When omitted, the server will index if an embedding model is configured.
    index_embeddings: Optional[bool] = None
    embedding_model: Optional[str] = None


class KGExtractRequest(BaseModel):
    text: str
    graph_id: str
    model_spec: Optional[str] = None
    ontology: Optional[Dict[str, Any]] = None


class KGCreateRequest(BaseModel):
    name: str
    agent_id: str = ""


class KGInterpretRequest(BaseModel):
    mode: str = "both"  # nodes|communities|both
    model_spec: Optional[str] = None
    max_nodes: int = 60
    max_mentions: int = 3
    max_communities: int = 8


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    agent_ids: Optional[List[str]] = None
    chairman_model: str = ""
    chairman_agent_id: str = ""
    kb_doc_ids: List[str] = []
    report_requirements: str = ""
    messages: List[Dict[str, Any]]


class ConversationKBDocsRequest(BaseModel):
    doc_ids: List[str] = []


class ConversationChairmanRequest(BaseModel):
    chairman_model: str = ""
    chairman_agent_id: str = ""


class ConversationReportRequest(BaseModel):
    report_requirements: str = ""


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/status")
async def status():
    """Basic runtime configuration (no secrets)."""
    agents_store.ensure_initialized()
    models = agents_store.get_models()
    agents = agents_store.list_agents()
    return {
        "settings": settings_store.get_settings().__dict__,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "model_spec": a.model_spec,
                "provider": parse_model_spec(a.model_spec).provider,
                "model": parse_model_spec(a.model_spec).model,
                "enabled": a.enabled,
                "influence_weight": a.influence_weight,
                "seniority_years": a.seniority_years,
                "kb_doc_ids": a.kb_doc_ids,
                "kb_categories": a.kb_categories,
                "graph_id": a.graph_id,
            }
            for a in agents
        ],
        "council_models": [
            {"spec": a.model_spec, "provider": parse_model_spec(a.model_spec).provider, "model": parse_model_spec(a.model_spec).model}
            for a in agents
            if a.enabled
        ],
        "chairman_model": {"spec": models["chairman_model"], **parse_model_spec(models["chairman_model"]).__dict__},
        "title_model": {"spec": models["title_model"], **parse_model_spec(models["title_model"]).__dict__},
    }


@app.get("/api/agents")
async def list_agents():
    agents_store.ensure_initialized()
    return [
        {
            "id": a.id,
            "name": a.name,
            "model_spec": a.model_spec,
            "enabled": a.enabled,
            "persona": a.persona,
            "influence_weight": a.influence_weight,
            "seniority_years": a.seniority_years,
            "kb_doc_ids": a.kb_doc_ids,
            "kb_categories": a.kb_categories,
            "graph_id": a.graph_id,
            "created_at": a.created_at,
        }
        for a in agents_store.list_agents()
    ]


@app.post("/api/agents")
async def create_agent(request: AgentUpsertRequest):
    agent_id = request.id or str(uuid.uuid4())
    agent = agents_store.AgentConfig(
        id=agent_id,
        name=request.name,
        model_spec=request.model_spec,
        enabled=request.enabled,
        persona=request.persona or "",
        influence_weight=request.influence_weight,
        seniority_years=request.seniority_years,
        kb_doc_ids=list(request.kb_doc_ids or []),
        kb_categories=list(request.kb_categories or []),
        graph_id=request.graph_id or "",
    )
    agents_store.upsert_agent(agent)
    return {"ok": True, "agent": {"id": agent.id}}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpsertRequest):
    existing = agents_store.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agents_store.AgentConfig(
        id=agent_id,
        name=request.name,
        model_spec=request.model_spec,
        enabled=request.enabled,
        persona=request.persona or "",
        influence_weight=request.influence_weight,
        seniority_years=request.seniority_years,
        kb_doc_ids=list(request.kb_doc_ids or []),
        kb_categories=list(request.kb_categories or []),
        graph_id=request.graph_id or "",
        created_at=existing.created_at,
    )
    agents_store.upsert_agent(agent)
    return {"ok": True}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    deleted = agents_store.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True}


@app.post("/api/agents/models")
async def set_agent_models(request: AgentModelsRequest):
    models = agents_store.set_models(chairman_model=request.chairman_model, title_model=request.title_model)
    return {"ok": True, "models": models}


@app.post("/api/agents/persona/generate")
async def generate_agent_persona(request: AgentPersonaGenerateRequest):
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")

    models = agents_store.get_models()
    model_spec = (request.model_spec or models.get("chairman_model") or "").strip()
    if not model_spec:
        raise HTTPException(status_code=400, detail="model_spec 不能为空")

    system_prompt = (
        "你是“Agent 人设(System Prompt)撰写专家”。\n"
        "你的任务：根据给定的 Agent 名称，生成一段可直接作为 LLM system prompt 的中文人设。\n"
        "要求：\n"
        "- 不要输出 JSON，不要输出 Markdown 代码块。\n"
        "- 不要编造具体真实个人隐私（手机号/地址/身份证等）；可使用合理但虚构且泛化的背景。\n"
        "- 用第二人称“你是…”写法，清晰可执行。\n"
        "- 包含：角色定位、能力边界、沟通风格、偏好/禁忌、输出格式要求（简洁、结构化）。\n"
        "- 长度建议 300~800 字。\n"
    )

    user_prompt = f"Agent 名称：{name}\n\n请输出该 Agent 的 system prompt（纯文本）。"

    resp = await query_model(
        model_spec,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=120.0,
    )
    content = (resp or {}).get("content") if isinstance(resp, dict) else None
    if not content or not str(content).strip():
        raise HTTPException(status_code=502, detail="人设生成失败：模型未返回内容")

    persona = str(content).strip()
    return {"ok": True, "persona": persona, "model_spec": model_spec}


@app.get("/api/settings")
async def get_settings():
    return settings_store.get_settings().__dict__


@app.post("/api/settings")
async def patch_settings(request: SettingsPatchRequest):
    patch = request.model_dump(exclude_none=True)
    s = settings_store.update_settings(patch)
    return {"ok": True, "settings": s.__dict__}


kb = KBStore()
kb_retriever = KBHybridRetriever(kb)


@app.get("/api/kb/documents")
async def kb_list_documents():
    return {"documents": kb.list_documents()}


# NOTE: This route must be declared before "/api/kb/documents/{doc_id}" routes,
# otherwise "batch" will be captured as a doc_id and POST will return 405.
@app.post("/api/kb/documents/batch")
async def kb_add_documents_batch(request: KBAddBatchRequest):
    import uuid as _uuid

    settings = settings_store.get_settings()
    results: List[Dict[str, Any]] = []
    ok_doc_ids: List[str] = []

    for d in request.documents or []:
        doc_id = d.id or _uuid.uuid4().hex
        try:
            r = kb.add_document(
                doc_id=doc_id,
                title=d.title,
                source=d.source or "",
                text=d.text,
                categories=d.categories or [],
                agent_ids=d.agent_ids or [],
            )
            ok_doc_ids.append(doc_id)
            results.append({"ok": True, **r})
        except Exception as e:
            results.append({"ok": False, "doc_id": doc_id, "error": str(e)})

    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    should_index = request.index_embeddings if request.index_embeddings is not None else bool(model)
    embeddings = None
    if should_index and model and ok_doc_ids:
        embeddings = await kb_retriever.index_embeddings(
            embedding_model_spec=model,
            doc_ids=ok_doc_ids,
            pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
        )

    return {"ok": True, "results": results, "embeddings": embeddings}


@app.get("/api/kb/documents/{doc_id}")
async def kb_get_document(doc_id: str):
    doc = kb.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": doc}

@app.put("/api/kb/documents/{doc_id}")
async def kb_update_document(doc_id: str, request: KBUpdateRequest):
    updated_any = False
    if request.categories is not None:
        updated_any = kb.set_document_categories(doc_id, request.categories) or updated_any
    if request.agent_ids is not None:
        updated_any = kb.set_document_agents(doc_id, request.agent_ids) or updated_any
    if not updated_any:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}

@app.post("/api/kb/index")
async def kb_index(request: KBIndexRequest):
    settings = settings_store.get_settings()
    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    return await kb_retriever.index_embeddings(
        embedding_model_spec=model,
        agent_id=(request.agent_id or "").strip() or None,
        doc_ids=request.doc_ids,
        categories=request.categories,
        pool=int(request.pool or 5000),
    )


@app.post("/api/kb/documents")
async def kb_add_document(request: KBAddRequest):
    import uuid as _uuid

    settings = settings_store.get_settings()
    doc_id = request.id or _uuid.uuid4().hex
    result = kb.add_document(
        doc_id=doc_id,
        title=request.title,
        source=request.source or "",
        text=request.text,
        categories=request.categories or [],
        agent_ids=request.agent_ids or [],
    )

    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    should_index = request.index_embeddings if request.index_embeddings is not None else bool(model)
    embeddings = None
    if should_index and model:
        embeddings = await kb_retriever.index_embeddings(
            embedding_model_spec=model,
            doc_ids=[doc_id],
            pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
        )

    return {"ok": True, **result, "embeddings": embeddings}


@app.delete("/api/kb/documents/{doc_id}")
async def kb_delete_document(doc_id: str):
    deleted = kb.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@app.get("/api/kb/search", response_model=KBSearchResponse)
async def kb_search(q: str, agent_id: Optional[str] = None, limit: int = 6):
    settings = settings_store.get_settings()
    results = await kb_retriever.search(
        query=q,
        agent_id=agent_id,
        doc_ids=None,
        categories=None,
        limit=limit,
        mode=settings.kb_retrieval_mode,
        embedding_model_spec=settings.kb_embedding_model,
        enable_rerank=bool(settings.kb_enable_rerank),
        rerank_model_spec=settings.kb_rerank_model or agents_store.get_models().get("chairman_model") or "",
        semantic_pool=int(settings.kb_semantic_pool),
        initial_k=int(settings.kb_initial_k),
    )
    return {"results": results}


def _get_neo4j() -> Neo4jKGStore:
    try:
        return Neo4jKGStore()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Neo4j 未配置或连接失败：{e}")


@app.get("/api/kg/graphs")
async def kg_list_graphs(agent_id: Optional[str] = None):
    store = _get_neo4j()
    try:
        return {"graphs": store.list_graphs(agent_id=agent_id)}
    finally:
        store.close()


@app.post("/api/kg/graphs")
async def kg_create_graph(request: KGCreateRequest):
    store = _get_neo4j()
    try:
        graph_id = store.create_graph(name=request.name, agent_id=request.agent_id)
        if request.agent_id:
            existing = agents_store.get_agent(request.agent_id)
            if existing and not (existing.graph_id or "").strip():
                agents_store.upsert_agent(
                    agents_store.AgentConfig(
                        id=existing.id,
                        name=existing.name,
                        model_spec=existing.model_spec,
                        enabled=existing.enabled,
                        persona=existing.persona,
                        influence_weight=existing.influence_weight,
                        seniority_years=existing.seniority_years,
                        kb_doc_ids=list(existing.kb_doc_ids or []),
                        kb_categories=list(existing.kb_categories or []),
                        graph_id=graph_id,
                        created_at=existing.created_at,
                    )
                )
        return {"ok": True, "graph_id": graph_id}
    finally:
        store.close()


@app.post("/api/kg/extract")
async def kg_extract_and_upsert(request: KGExtractRequest):
    # Default to Chairman model for extraction.
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]

    ontology = request.ontology or DEFAULT_ONTOLOGY
    extracted = await extract_kg_incremental(model_spec=model_spec, text=request.text, ontology=ontology)

    store = _get_neo4j()
    try:
        chunks = extracted.get("chunks") or []
        total_entities = 0
        total_relations = 0

        for c in chunks:
            chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
            chunk_text = str((c.get("text") or "")) if isinstance(c, dict) else ""
            store.upsert_chunk(KGChunk(graph_id=request.graph_id, chunk_id=chunk_id, text=chunk_text))

            entities_in_chunk = c.get("entities") or []
            relations_in_chunk = c.get("relations") or []

            entities: List[KGEntity] = []
            uuid_by_key: Dict[str, str] = {}
            for ent in entities_in_chunk:
                raw_type = ent.get("type", "")
                canonical_type = canonicalize_entity_type(raw_type)
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                eobj = KGEntity(
                    graph_id=request.graph_id,
                    name=name,
                    entity_type=canonical_type,
                    summary=(ent.get("summary") or "").strip(),
                    attributes=ent.get("attributes") or {},
                    source_entity_types=[str(raw_type).strip()] if raw_type else [],
                )
                entities.append(eobj)
                uuid_by_key[f"{canonical_type}:{name}".lower()] = eobj.uuid

            if entities:
                entity_uuids = store.upsert_entities(entities)
                store.link_mentions(chunk_id=chunk_id, entity_uuids=entity_uuids, graph_id=request.graph_id)
                total_entities += len(entities)

            relations: List[KGRelation] = []
            # Ensure endpoints exist for relations, even if not emitted as entities in this chunk.
            missing_endpoint_entities: List[KGEntity] = []
            for rel in relations_in_chunk:
                s_type_raw = rel.get("source_type") or "Entity"
                t_type_raw = rel.get("target_type") or "Entity"
                s_type = canonicalize_entity_type(s_type_raw)
                t_type = canonicalize_entity_type(t_type_raw)
                s_name = (rel.get("source") or "").strip()
                t_name = (rel.get("target") or "").strip()
                if not s_name or not t_name:
                    continue
                s_key = f"{s_type}:{s_name}".lower()
                t_key = f"{t_type}:{t_name}".lower()
                s_uuid = uuid_by_key.get(s_key) or _stable_uuid_fallback(request.graph_id, s_type, s_name)
                t_uuid = uuid_by_key.get(t_key) or _stable_uuid_fallback(request.graph_id, t_type, t_name)

                if s_key not in uuid_by_key:
                    missing_endpoint_entities.append(
                        KGEntity(
                            graph_id=request.graph_id,
                            name=s_name,
                            entity_type=s_type,
                            summary="",
                            attributes={},
                            source_entity_types=[str(s_type_raw).strip()] if s_type_raw else [],
                        )
                    )
                if t_key not in uuid_by_key:
                    missing_endpoint_entities.append(
                        KGEntity(
                            graph_id=request.graph_id,
                            name=t_name,
                            entity_type=t_type,
                            summary="",
                            attributes={},
                            source_entity_types=[str(t_type_raw).strip()] if t_type_raw else [],
                        )
                    )

                relations.append(
                    KGRelation(
                        graph_id=request.graph_id,
                        source_uuid=s_uuid,
                        target_uuid=t_uuid,
                        relation_name=(rel.get("relation") or "").strip(),
                        fact=(rel.get("fact") or "").strip(),
                        attributes=rel.get("attributes") or {},
                    )
                )

            if missing_endpoint_entities:
                store.upsert_entities(missing_endpoint_entities)
            if relations:
                store.upsert_relations(relations)
                total_relations += len(relations)

        return {"ok": True, "extracted": extracted, "entities": total_entities, "relations": total_relations}
    finally:
        store.close()


def _stable_uuid_fallback(graph_id: str, entity_type: str, name: str) -> str:
    # Keep consistent with Neo4j store stable id.
    import hashlib

    normalized = (name or "").strip().lower()
    base = f"{graph_id}:{entity_type}:{normalized}".encode("utf-8")
    digest = hashlib.sha1(base).hexdigest()[:16]
    return f"ent_{digest}"


@app.get("/api/kg/graphs/{graph_id}")
async def kg_get_graph(graph_id: str):
    store = _get_neo4j()
    try:
        data = store.get_graph_data(graph_id)
        community = store.get_graph_community_summaries(graph_id=graph_id)
        if community:
            data["community_summaries"] = community
        return data
    finally:
        store.close()


@app.get("/api/kg/graphs/{graph_id}/subgraph")
async def kg_subgraph(graph_id: str, q: str):
    store = _get_neo4j()
    try:
        return store.query_subgraph(graph_id, q)
    finally:
        store.close()


@app.post("/api/kg/graphs/{graph_id}/interpret")
async def kg_interpret(graph_id: str, request: KGInterpretRequest):
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]
    mode = (request.mode or "both").strip().lower()
    max_nodes = max(1, min(200, int(request.max_nodes or 60)))
    max_mentions = max(0, min(10, int(request.max_mentions or 3)))
    max_communities = max(0, min(50, int(request.max_communities or 8)))

    store = _get_neo4j()
    try:
        graph = store.get_graph_data(graph_id, limit=2000)
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []

        id_to_node = {n["id"]: n for n in nodes if n.get("id")}
        id_to_label = {n["id"]: n.get("label") or n["id"] for n in nodes if n.get("id")}

        # Degree for ordering
        degree = {nid: 0 for nid in id_to_node.keys()}
        for e in edges:
            a = e.get("from")
            b = e.get("to")
            if a in degree:
                degree[a] += 1
            if b in degree:
                degree[b] += 1

        result: Dict[str, Any] = {"ok": True, "graph_id": graph_id, "mode": mode, "model_spec": model_spec}

        if mode in ("nodes", "both"):
            selected_ids = sorted(degree.keys(), key=lambda x: degree.get(x, 0), reverse=True)[:max_nodes]
            done = 0
            for eid in selected_ids:
                entity = id_to_node.get(eid)
                if not entity:
                    continue
                neighbors = []
                for rel in edges:
                    if rel.get("from") == eid:
                        neighbors.append(f"{entity.get('label')} -[{rel.get('label')}]-> {id_to_label.get(rel.get('to'), rel.get('to'))}")
                    elif rel.get("to") == eid:
                        neighbors.append(f"{id_to_label.get(rel.get('from'), rel.get('from'))} -[{rel.get('label')}]-> {entity.get('label')}")
                mentions = []
                if max_mentions > 0:
                    hits = store.get_entity_mentions(graph_id=graph_id, entity_uuid=eid, limit=max_mentions)
                    for h in hits:
                        t = (h.get("text") or "").strip()
                        if len(t) > 360:
                            t = t[:360] + "…"
                        if t:
                            mentions.append(t)
                interp = await interpret_entity(
                    model_spec=model_spec,
                    query_language="zh",
                    entity=entity,
                    neighbors=neighbors,
                    mentions=mentions,
                    timeout=120.0,
                )
                if interp:
                    store.set_entity_interpretation(
                        graph_id=graph_id,
                        entity_uuid=eid,
                        summary=interp.get("summary") or "",
                        key_facts=list(interp.get("key_facts") or []),
                        model_spec=model_spec,
                    )
                    done += 1
            result["nodes_interpreted"] = done

        if mode in ("communities", "both"):
            comps = build_components(nodes, edges)
            # Build lightweight edge strings for each community
            comm_summaries: List[Dict[str, Any]] = []
            for idx, comp in enumerate(comps[:max_communities], start=1):
                comp_nodes = [id_to_node[c] for c in comp if c in id_to_node]
                # pick most connected nodes as representatives
                comp_nodes.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
                edge_strs = []
                comp_set = set(comp)
                for rel in edges:
                    a = rel.get("from")
                    b = rel.get("to")
                    if a in comp_set and b in comp_set:
                        edge_strs.append(f"{id_to_label.get(a,a)} -[{rel.get('label')}]-> {id_to_label.get(b,b)}")
                summ = await summarize_community(
                    model_spec=model_spec,
                    query_language="zh",
                    community_index=idx,
                    entities=comp_nodes[:60],
                    edges=edge_strs[:80],
                    timeout=120.0,
                )
                if summ:
                    comm_summaries.append(summ)

            store.set_graph_community_summaries(graph_id=graph_id, summaries=comm_summaries, model_spec=model_spec)
            result["communities"] = comm_summaries

        return result
    finally:
        store.close()


@app.post("/api/kg/graphs/{graph_id}/interpret/stream")
async def kg_interpret_stream(graph_id: str, request: KGInterpretRequest):
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]
    mode = (request.mode or "both").strip().lower()
    max_nodes = max(1, min(200, int(request.max_nodes or 60)))
    max_mentions = max(0, min(10, int(request.max_mentions or 3)))
    max_communities = max(0, min(50, int(request.max_communities or 8)))

    async def event_stream():
        store = _get_neo4j()
        try:
            graph = store.get_graph_data(graph_id, limit=2000)
            nodes = graph.get("nodes") or []
            edges = graph.get("edges") or []

            id_to_node = {n["id"]: n for n in nodes if n.get("id")}
            id_to_label = {n["id"]: n.get("label") or n["id"] for n in nodes if n.get("id")}
            degree = {nid: 0 for nid in id_to_node.keys()}
            for e in edges:
                a = e.get("from")
                b = e.get("to")
                if a in degree:
                    degree[a] += 1
                if b in degree:
                    degree[b] += 1

            yield f"data: {json.dumps({'type':'start','mode':mode,'model_spec':model_spec}, ensure_ascii=False)}\n\n"

            interpreted = 0
            if mode in ("nodes", "both"):
                selected_ids = sorted(degree.keys(), key=lambda x: degree.get(x, 0), reverse=True)[:max_nodes]
                yield f"data: {json.dumps({'type':'nodes_start','total':len(selected_ids)}, ensure_ascii=False)}\n\n"
                for i, eid in enumerate(selected_ids, start=1):
                    entity = id_to_node.get(eid)
                    if not entity:
                        continue
                    yield f"data: {json.dumps({'type':'node_progress','current':i,'total':len(selected_ids),'entity':entity.get('label')}, ensure_ascii=False)}\n\n"

                    neighbors = []
                    for rel in edges:
                        if rel.get("from") == eid:
                            neighbors.append(
                                f"{entity.get('label')} -[{rel.get('label')}]-> {id_to_label.get(rel.get('to'), rel.get('to'))}"
                            )
                        elif rel.get("to") == eid:
                            neighbors.append(
                                f"{id_to_label.get(rel.get('from'), rel.get('from'))} -[{rel.get('label')}]-> {entity.get('label')}"
                            )
                    mentions = []
                    if max_mentions > 0:
                        hits = store.get_entity_mentions(graph_id=graph_id, entity_uuid=eid, limit=max_mentions)
                        for h in hits:
                            t = (h.get("text") or "").strip()
                            if len(t) > 360:
                                t = t[:360] + "…"
                            if t:
                                mentions.append(t)
                    interp = await interpret_entity(
                        model_spec=model_spec,
                        query_language="zh",
                        entity=entity,
                        neighbors=neighbors,
                        mentions=mentions,
                        timeout=120.0,
                    )
                    if interp:
                        ok = store.set_entity_interpretation(
                            graph_id=graph_id,
                            entity_uuid=eid,
                            summary=interp.get("summary") or "",
                            key_facts=list(interp.get("key_facts") or []),
                            model_spec=model_spec,
                        )
                        if ok:
                            interpreted += 1
                    yield f"data: {json.dumps({'type':'node_done','current':i,'total':len(selected_ids),'interpreted':interpreted}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type':'nodes_complete','interpreted':interpreted}, ensure_ascii=False)}\n\n"

            communities_payload = None
            if mode in ("communities", "both"):
                comps = build_components(nodes, edges)
                yield f"data: {json.dumps({'type':'communities_start','total':min(len(comps), max_communities)}, ensure_ascii=False)}\n\n"
                comm_summaries: List[Dict[str, Any]] = []
                for idx, comp in enumerate(comps[:max_communities], start=1):
                    yield f"data: {json.dumps({'type':'community_progress','current':idx,'total':min(len(comps), max_communities)}, ensure_ascii=False)}\n\n"
                    comp_nodes = [id_to_node[c] for c in comp if c in id_to_node]
                    comp_nodes.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
                    comp_set = set(comp)
                    edge_strs = []
                    for rel in edges:
                        a = rel.get("from")
                        b = rel.get("to")
                        if a in comp_set and b in comp_set:
                            edge_strs.append(
                                f"{id_to_label.get(a,a)} -[{rel.get('label')}]-> {id_to_label.get(b,b)}"
                            )
                    summ = await summarize_community(
                        model_spec=model_spec,
                        query_language="zh",
                        community_index=idx,
                        entities=comp_nodes[:60],
                        edges=edge_strs[:80],
                        timeout=120.0,
                    )
                    if summ:
                        comm_summaries.append(summ)
                store.set_graph_community_summaries(graph_id=graph_id, summaries=comm_summaries, model_spec=model_spec)
                communities_payload = comm_summaries
                yield f"data: {json.dumps({'type':'communities_complete','communities':comm_summaries}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type':'complete','nodes_interpreted':interpreted,'communities':communities_payload}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)}, ensure_ascii=False)}\n\n"
        finally:
            store.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    if request.agent_ids is not None:
        storage.update_conversation_agents(conversation_id, request.agent_ids)
        conversation = storage.get_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.put("/api/conversations/{conversation_id}/kb/doc_ids")
async def set_conversation_kb_doc_ids(conversation_id: str, request: ConversationKBDocsRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Validate documents exist.
    missing = []
    for doc_id in request.doc_ids or []:
        did = (doc_id or "").strip()
        if not did:
            continue
        if kb.get_document(did) is None:
            missing.append(did)
    if missing:
        raise HTTPException(status_code=404, detail=f"KB 文档不存在: {', '.join(missing[:8])}")

    storage.update_conversation_kb_doc_ids(conversation_id, request.doc_ids or [])
    return {"ok": True, "kb_doc_ids": storage.get_conversation(conversation_id).get("kb_doc_ids", [])}


@app.put("/api/conversations/{conversation_id}/chairman")
async def set_conversation_chairman(conversation_id: str, request: ConversationChairmanRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Prefer agent-id (UI selection), fall back to explicit model_spec for backwards compatibility.
    if (request.chairman_agent_id or "").strip():
        storage.update_conversation_chairman_agent(conversation_id, request.chairman_agent_id)
        # Clear explicit model override to avoid ambiguity.
        storage.update_conversation_chairman_model(conversation_id, "")
    else:
        storage.update_conversation_chairman_agent(conversation_id, "")
        storage.update_conversation_chairman_model(conversation_id, request.chairman_model or "")

    conv = storage.get_conversation(conversation_id) or {}
    return {
        "ok": True,
        "chairman_agent_id": conv.get("chairman_agent_id", ""),
        "chairman_model": conv.get("chairman_model", ""),
    }


@app.put("/api/conversations/{conversation_id}/report")
async def set_conversation_report(conversation_id: str, request: ConversationReportRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.update_conversation_report_requirements(conversation_id, request.report_requirements)
    conv = storage.get_conversation(conversation_id) or {}
    return {"ok": True, "report_requirements": conv.get("report_requirements", "")}


@app.put("/api/conversations/{conversation_id}/agents")
async def set_conversation_agents(conversation_id: str, agent_ids: List[str]):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.update_conversation_agents(conversation_id, agent_ids)
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    deleted = storage.delete_conversation(conversation_id)
    trace_store.delete(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/trace")
async def get_conversation_trace(conversation_id: str):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"events": trace_store.read_events(conversation_id)}


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    export = {
        "conversation": conversation,
        "trace": trace_store.read_events(conversation_id),
        "agents": [a.__dict__ for a in agents_store.list_agents()],
        "models": agents_store.get_models(),
    }
    return export


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content, conversation_id=conversation_id)
        storage.update_conversation_title(conversation_id, title)

    # Run the full council process (includes optional extra stages)
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content, conversation_id=conversation_id
    )

    # Add assistant message with all stages (including optional extra stages)
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        stage0=metadata.get("preprocess"),
        stage2b=metadata.get("roundtable"),
        stage2c=metadata.get("fact_check"),
        stage4=metadata.get("report"),
        metadata=metadata,
    )

    # Return the complete response with metadata
    return {
        "stage0": metadata.get("preprocess"),
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage2b": metadata.get("roundtable"),
        "stage2c": metadata.get("fact_check"),
        "stage3": stage3_result,
        "stage4": metadata.get("report"),
        "metadata": metadata,
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content, conversation_id=conversation_id))

            # Stage 0: Preprocess (optional)
            yield f"data: {json.dumps({'type': 'stage0_start'})}\n\n"
            preprocess = await stage0_preprocess(request.content, conversation_id)
            yield f"data: {json.dumps({'type': 'stage0_complete', 'data': preprocess})}\n\n"

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content, conversation_id=conversation_id, preprocess=preprocess)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_agent = await stage2_collect_rankings(request.content, stage1_results, conversation_id=conversation_id)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_agent)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_agent': label_to_agent, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 2B: Roundtable (optional)
            yield f"data: {json.dumps({'type': 'stage2b_start'})}\n\n"
            roundtable = await stage2b_roundtable(request.content, stage1_results, stage2_results, conversation_id=conversation_id)
            yield f"data: {json.dumps({'type': 'stage2b_complete', 'data': roundtable})}\n\n"

            # Stage 2C: Fact-check (optional)
            yield f"data: {json.dumps({'type': 'stage2c_start'})}\n\n"
            fact_check = await stage2c_fact_check(request.content, stage1_results, stage2_results, roundtable, conversation_id=conversation_id)
            yield f"data: {json.dumps({'type': 'stage2c_complete', 'data': fact_check})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                request.content,
                stage1_results,
                stage2_results,
                roundtable=roundtable,
                fact_check=fact_check,
                conversation_id=conversation_id,
            )
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Stage 4: Chairman report (optional)
            yield f"data: {json.dumps({'type': 'stage4_start'})}\n\n"
            report = await stage4_generate_report(
                request.content,
                stage0=preprocess,
                stage1_results=stage1_results,
                stage2_results=stage2_results,
                roundtable=roundtable,
                fact_check=fact_check,
                stage3_result=stage3_result,
                conversation_id=conversation_id,
            )
            yield f"data: {json.dumps({'type': 'stage4_complete', 'data': report})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            metadata = {
                "label_to_agent": label_to_agent,
                "aggregate_rankings": aggregate_rankings,
                "preprocess": preprocess,
                "roundtable": roundtable,
                "fact_check": fact_check,
                "report": report,
            }
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                stage0=preprocess,
                stage2b=roundtable,
                stage2c=fact_check,
                stage4=report,
                metadata=metadata,
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT") or os.getenv("PORT") or "8001")
    uvicorn.run(app, host="0.0.0.0", port=port)
