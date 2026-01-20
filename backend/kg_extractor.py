"""LLM-based entity/relation extractor (GraphRAG-style, incremental).

Ported to align with MiroFish-Optimize strategy:
- strict JSON schema
- best-effort safe-mode retry on failure
- chunked incremental extraction (upstream decides how to upsert/merge)
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from .llm_client import query_model
from .settings_store import get_settings


DEFAULT_ONTOLOGY = {
    "entity_types": [{"name": "Person"}, {"name": "Organization"}, {"name": "Location"}, {"name": "Product"}, {"name": "Event"}, {"name": "Concept"}],
    "edge_types": [
        {"name": "RELATED_TO"},
        {"name": "PART_OF"},
        {"name": "LOCATED_IN"},
        {"name": "WORKS_FOR"},
        {"name": "CREATED_BY"},
        {"name": "CAUSES"},
        {"name": "OWNS"},
        {"name": "MENTIONS"},
    ],
}


def split_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 120) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    step = max(1, int(chunk_size) - int(chunk_overlap))
    out: List[str] = []
    i = 0
    while i < len(text):
        chunk = text[i : i + int(chunk_size)].strip()
        if chunk:
            out.append(chunk)
        i += step
    return out


def iter_split_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 120):
    """
    Generator version of split_text to avoid materializing all chunks in memory.

    Yields chunks as strings.
    """
    text = (text or "").strip()
    if not text:
        return
    step = max(1, int(chunk_size) - int(chunk_overlap))
    i = 0
    n = len(text)
    while i < n:
        chunk = text[i : i + int(chunk_size)].strip()
        if chunk:
            yield chunk
        i += step


def _extract_allowed_types(ontology: Dict[str, Any]) -> tuple[list[str], list[str]]:
    entity_types = [e.get("name") for e in (ontology or {}).get("entity_types", []) if isinstance(e, dict) and e.get("name")]
    edge_types = [e.get("name") for e in (ontology or {}).get("edge_types", []) if isinstance(e, dict) and e.get("name")]
    # Backward-compat if someone passes {"entity_types":["A"],"relation_types":["R"]}
    if not entity_types:
        entity_types = [str(x) for x in (ontology or {}).get("entity_types", []) if x]
    if not edge_types:
        edge_types = [str(x) for x in (ontology or {}).get("relation_types", []) if x]
    return entity_types, edge_types


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


async def _extract_one(
    *,
    model_spec: str,
    text: str,
    ontology: Dict[str, Any],
    timeout: float,
    safe_mode: bool,
) -> Dict[str, Any]:
    settings = get_settings()
    entity_types, edge_types = _extract_allowed_types(ontology)

    if settings.output_language == "en":
        system = (
            "You are a strict JSON-only information extractor.\n"
            "Return ONLY a valid JSON object.\n"
        )
    else:
        system = (
            "你是一个严格输出 JSON 的信息抽取器。\n"
            "只允许输出一个 JSON 对象，不要输出任何额外文字。\n"
        )

    if safe_mode:
        system += (
            "Safety: do not output explicit/sexual/violent/hateful/self-harm content.\n"
            "If the input might trigger moderation, redact details using '[REDACTED]' and keep outputs minimal.\n"
        )

    user = {
        "text": text,
        "allowed_entity_types": entity_types,
        "allowed_relation_types": edge_types,
        "requirements": {
            "only_use_allowed_types": True,
            "deduplicate_entities_by_name_and_type": True,
            "do_not_guess": True,
            "return_empty_when_none": True,
            "avoid_quoting_input": True,
        },
        "output_schema": {
            "entities": [{"name": "string", "type": "string", "summary": "", "attributes": {}}],
            "relations": [
                {
                    "source": "string",
                    "source_type": "string",
                    "target": "string",
                    "target_type": "string",
                    "relation": "string",
                    "fact": "",
                    "attributes": {},
                }
            ],
        },
    }

    resp = await query_model(
        model_spec,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        timeout=timeout,
    )
    content = (resp or {}).get("content") or ""
    data = _parse_json_object(content)
    if not isinstance(data, dict):
        return {"entities": [], "relations": []}
    return data


async def extract_kg(
    *,
    model_spec: str,
    text: str,
    ontology: Optional[Dict[str, Any]] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "entities":[{"name":"...","type":"...","summary":"","attributes":{}}],
        "relations":[{"source":"...","source_type":"...","target":"...","target_type":"...","relation":"...","fact":"","attributes":{}}]
      }
    """
    ont = ontology or DEFAULT_ONTOLOGY
    entity_types, edge_types = _extract_allowed_types(ont)
    allowed_entities = set(entity_types)
    allowed_relations = set(edge_types)

    data = await _extract_one(model_spec=model_spec, text=text, ontology=ont, timeout=timeout, safe_mode=False)
    if not data.get("entities") and not data.get("relations") and text:
        # Best-effort fallback: retry in safe mode when provider/moderation blocks or output is malformed.
        data = await _extract_one(model_spec=model_spec, text=text, ontology=ont, timeout=timeout, safe_mode=True)

    entities = data.get("entities") or []
    relations = data.get("relations") or []

    cleaned_entities: List[Dict[str, Any]] = []
    for e in entities:
        name = (e or {}).get("name")
        etype = (e or {}).get("type")
        if not name or not etype:
            continue
        etype = str(etype).strip()
        if allowed_entities and etype not in allowed_entities:
            continue
        cleaned_entities.append(
            {
                "name": str(name).strip(),
                "type": etype,
                "summary": str((e or {}).get("summary") or "").strip(),
                "attributes": (e or {}).get("attributes") or {},
            }
        )

    cleaned_relations: List[Dict[str, Any]] = []
    for r in relations:
        rr = r or {}
        source = rr.get("source")
        target = rr.get("target")
        source_type = rr.get("source_type")
        target_type = rr.get("target_type")
        rel = rr.get("relation")
        if not source or not target or not source_type or not target_type or not rel:
            continue
        rel = str(rel).strip()
        if allowed_relations and rel not in allowed_relations:
            continue
        cleaned_relations.append(
            {
                "source": str(source).strip(),
                "source_type": str(source_type).strip(),
                "target": str(target).strip(),
                "target_type": str(target_type).strip(),
                "relation": rel,
                "fact": str(rr.get("fact") or "").strip(),
                "attributes": rr.get("attributes") or {},
            }
        )

    return {"entities": cleaned_entities, "relations": cleaned_relations, "ontology": ont}


async def extract_kg_incremental(
    *,
    model_spec: str,
    text: str,
    ontology: Optional[Dict[str, Any]] = None,
    timeout: float = 120.0,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
) -> Dict[str, Any]:
    """Extract KG from long text by chunking and aggregating results."""
    ont = ontology or DEFAULT_ONTOLOGY
    chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        return {"chunks": [], "entities": [], "relations": [], "ontology": ont}

    all_entities: List[Dict[str, Any]] = []
    all_relations: List[Dict[str, Any]] = []
    per_chunk: List[Dict[str, Any]] = []
    for idx, c in enumerate(chunks):
        extracted = await extract_kg(model_spec=model_spec, text=c, ontology=ont, timeout=timeout)
        ents = extracted.get("entities") or []
        rels = extracted.get("relations") or []
        per_chunk.append({"index": idx, "text": c, "text_len": len(c), "entities": ents, "relations": rels})
        all_entities.extend(ents)
        all_relations.extend(rels)

    return {"chunks": per_chunk, "entities": all_entities, "relations": all_relations, "ontology": ont}


async def iter_extract_kg_chunks(
    *,
    model_spec: str,
    text: str,
    ontology: Optional[Dict[str, Any]] = None,
    timeout: float = 120.0,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Memory-efficient incremental extractor.

    Yields per-chunk extraction results without accumulating all chunks/entities/relations in memory.

    Yields:
      {"index": int, "text": str, "text_len": int, "entities": [...], "relations": [...], "ontology": {...}}
    """
    ont = ontology or DEFAULT_ONTOLOGY
    for idx, c in enumerate(iter_split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
        extracted = await extract_kg(model_spec=model_spec, text=c, ontology=ont, timeout=timeout)
        ents = extracted.get("entities") or []
        rels = extracted.get("relations") or []
        yield {"index": idx, "text": c, "text_len": len(c), "entities": ents, "relations": rels, "ontology": ont}
