from __future__ import annotations

import uuid
from typing import Any, Dict, List

from .. import agents_store
from ..entity_type_normalizer import canonicalize_entity_type
from ..jobs_store import Job
from ..kg_extractor import DEFAULT_ONTOLOGY, extract_kg_incremental
from ..kg_utils import stable_uuid_fallback
from ..neo4j_store import KGChunk, KGEntity, KGRelation
from ..tool_context import ToolContext


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    payload = job.payload or {}
    graph_id = str(payload.get("graph_id") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not graph_id or not text:
        return {"ok": False, "error": "graph_id/text required"}

    models = agents_store.get_models()
    model_spec = str(payload.get("model_spec") or models.get("chairman_model") or "").strip()
    ontology = payload.get("ontology") or DEFAULT_ONTOLOGY

    update_progress(0.05)
    extracted = await extract_kg_incremental(model_spec=model_spec, text=text, ontology=ontology)
    update_progress(0.45)

    store = ctx.get_neo4j()
    total_entities = 0
    total_relations = 0
    try:
        chunks = extracted.get("chunks") or []
        for c in chunks:
            chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
            chunk_text = str((c.get("text") or "")) if isinstance(c, dict) else ""
            store.upsert_chunk(KGChunk(graph_id=graph_id, chunk_id=chunk_id, text=chunk_text))

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
                    graph_id=graph_id,
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
                store.link_mentions(chunk_id=chunk_id, entity_uuids=entity_uuids, graph_id=graph_id)
                total_entities += len(entities)

            relations: List[KGRelation] = []
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
                s_uuid = uuid_by_key.get(s_key) or stable_uuid_fallback(graph_id, s_type, s_name)
                t_uuid = uuid_by_key.get(t_key) or stable_uuid_fallback(graph_id, t_type, t_name)
                if s_key not in uuid_by_key:
                    missing_endpoint_entities.append(
                        KGEntity(
                            graph_id=graph_id,
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
                            graph_id=graph_id,
                            name=t_name,
                            entity_type=t_type,
                            summary="",
                            attributes={},
                            source_entity_types=[str(t_type_raw).strip()] if t_type_raw else [],
                        )
                    )
                relations.append(
                    KGRelation(
                        graph_id=graph_id,
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
    finally:
        store.close()

    update_progress(1.0)
    return {
        "type": "kg_extract",
        "summary": f"图谱抽取完成：graph_id={graph_id}，entities≈{total_entities}，relations≈{total_relations}",
        "graph_id": graph_id,
        "entities": total_entities,
        "relations": total_relations,
    }

