"""Graph interpretation: per-entity interpretation and community summaries."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .llm_client import query_model


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def build_components(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[List[str]]:
    """Undirected connected components over entity uuids."""
    adj: Dict[str, List[str]] = {n["id"]: [] for n in nodes if n.get("id")}
    for e in edges or []:
        a = e.get("from")
        b = e.get("to")
        if a in adj and b in adj:
            adj[a].append(b)
            adj[b].append(a)

    seen = set()
    comps: List[List[str]] = []
    for nid in adj.keys():
        if nid in seen:
            continue
        stack = [nid]
        seen.add(nid)
        comp = []
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj.get(x, []):
                if y in seen:
                    continue
                seen.add(y)
                stack.append(y)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps


async def interpret_entity(
    *,
    model_spec: str,
    query_language: str,
    entity: Dict[str, Any],
    neighbors: List[str],
    mentions: List[str],
    timeout: float = 120.0,
) -> Optional[Dict[str, Any]]:
    """
    Returns {"summary": str, "key_facts": [str,...]}.
    """
    name = (entity.get("label") or "").strip()
    etype = (entity.get("type") or "").strip()
    if not name:
        return None

    # Enforce Chinese output; keep `query_language` for future extension.
    system = (
        "你是知识图谱节点解读器。你的输出必须是严格 JSON，不要输出任何额外文字。\n"
        "请用简体中文给出该实体的简介与关键事实。\n"
        '输出格式：{"summary":"...","key_facts":["...","..."]}\n'
        "要求：summary 1~3 句；key_facts 3~8 条，尽量基于证据，不要猜。\n"
    )

    user = {
        "entity": {"name": name, "type": etype},
        "neighbors": neighbors[:25],
        "evidence": mentions[:5],
    }

    resp = await query_model(
        model_spec,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
        ],
        timeout=timeout,
    )
    content = (resp or {}).get("content") or ""
    data = _parse_json_object(content)
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    key_facts = data.get("key_facts") or []
    if not isinstance(key_facts, list):
        key_facts = []
    key_facts = [str(x).strip() for x in key_facts if str(x).strip()]
    if not summary and not key_facts:
        return None
    return {"summary": summary, "key_facts": key_facts}


async def summarize_community(
    *,
    model_spec: str,
    query_language: str,
    community_index: int,
    entities: List[Dict[str, Any]],
    edges: List[str],
    timeout: float = 120.0,
) -> Optional[Dict[str, Any]]:
    """
    Returns {"title": str, "summary": str, "key_entities":[...], "key_relations":[...]}.
    """
    # Enforce Chinese output; keep `query_language` for future extension.
    system = (
        "你是知识图谱社区/主题摘要生成器。输出必须是严格 JSON，不要输出任何额外文字。\n"
        '输出格式：{"title":"...","summary":"...","key_entities":["..."],"key_relations":["..."]}\n'
        "要求：title 不超过 20 字；summary 3~6 句；key_entities 5~12 个；key_relations 3~10 条。\n"
    )

    payload = {
        "community_index": community_index,
        "entities": [{"name": e.get("label"), "type": e.get("type")} for e in entities[:40]],
        "relations": edges[:60],
    }
    resp = await query_model(
        model_spec,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        timeout=timeout,
    )
    data = _parse_json_object((resp or {}).get("content") or "")
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    key_entities = data.get("key_entities") or []
    key_relations = data.get("key_relations") or []
    if not isinstance(key_entities, list):
        key_entities = []
    if not isinstance(key_relations, list):
        key_relations = []
    key_entities = [str(x).strip() for x in key_entities if str(x).strip()]
    key_relations = [str(x).strip() for x in key_relations if str(x).strip()]
    if not title and not summary:
        return None
    return {
        "community_index": community_index,
        "title": title,
        "summary": summary,
        "key_entities": key_entities,
        "key_relations": key_relations,
        "size": len(entities),
    }
