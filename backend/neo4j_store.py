"""Neo4j knowledge graph store for LLM Council."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from neo4j import GraphDatabase, Driver

from .config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _stable_entity_uuid(graph_id: str, entity_type: str, name: str) -> str:
    normalized = (name or "").strip().lower()
    base = f"{graph_id}:{entity_type}:{normalized}".encode("utf-8")
    digest = hashlib.sha1(base).hexdigest()[:16]
    return f"ent_{digest}"


@dataclass(frozen=True)
class KGEntity:
    graph_id: str
    name: str
    entity_type: str = "Entity"
    summary: str = ""
    attributes: Optional[Dict[str, Any]] = None
    source_entity_types: Optional[List[str]] = None
    created_at: Optional[str] = None

    @property
    def uuid(self) -> str:
        return _stable_entity_uuid(self.graph_id, self.entity_type, self.name)


@dataclass(frozen=True)
class KGRelation:
    graph_id: str
    source_uuid: str
    target_uuid: str
    relation_name: str
    fact: str = ""
    attributes: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    uuid: str = ""


@dataclass(frozen=True)
class KGChunk:
    graph_id: str
    chunk_id: str
    text_preview: str = ""
    kb_doc_id: str = ""
    kb_chunk_id: str = ""
    source: str = ""
    created_at: Optional[str] = None


class Neo4jKGStore:
    def __init__(self):
        if not NEO4J_PASSWORD:
            raise RuntimeError("NEO4J_PASSWORD is not set")
        self._driver: Driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self._database = NEO4J_DATABASE
        self._ensure_schema()

    def close(self):
        try:
            self._driver.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT kg_graph_id_unique IF NOT EXISTS FOR (g:KGGraph) REQUIRE g.graph_id IS UNIQUE",
            "CREATE CONSTRAINT kg_entity_uuid_unique IF NOT EXISTS FOR (e:KGEntity) REQUIRE e.uuid IS UNIQUE",
            "CREATE CONSTRAINT kg_chunk_unique IF NOT EXISTS FOR (c:KGChunk) REQUIRE (c.chunk_id, c.graph_id) IS UNIQUE",
            "CREATE INDEX kg_entity_graph_id IF NOT EXISTS FOR (e:KGEntity) ON (e.graph_id)",
            "CREATE INDEX kg_rel_graph_id IF NOT EXISTS FOR ()-[r:KG_REL]-() ON (r.graph_id)",
            "CREATE INDEX kg_chunk_graph_id IF NOT EXISTS FOR (c:KGChunk) ON (c.graph_id)",
            "CREATE INDEX kg_chunk_chunk_id IF NOT EXISTS FOR (c:KGChunk) ON (c.chunk_id)",
            "CREATE INDEX kg_chunk_kb_chunk_id IF NOT EXISTS FOR (c:KGChunk) ON (c.kb_chunk_id)",
        ]
        with self._driver.session(database=self._database) as session:
            for c in stmts:
                try:
                    session.run(c)
                except Exception:
                    continue

    def create_graph(self, name: str, *, agent_id: str = "") -> str:
        graph_id = f"kg_{uuid.uuid4().hex[:16]}"
        created_at = _now_iso()
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                CREATE (g:KGGraph {graph_id:$graph_id, name:$name, agent_id:$agent_id, created_at:$created_at})
                """,
                graph_id=graph_id,
                name=name,
                agent_id=agent_id,
                created_at=created_at,
            )
        return graph_id

    def list_graphs(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._driver.session(database=self._database) as session:
            if agent_id:
                rows = session.run(
                    "MATCH (g:KGGraph {agent_id:$agent_id}) RETURN g ORDER BY g.created_at DESC",
                    agent_id=agent_id,
                )
            else:
                rows = session.run("MATCH (g:KGGraph) RETURN g ORDER BY g.created_at DESC")
            out = []
            for r in rows:
                g = r["g"]
                out.append(dict(g))
            return out

    def upsert_entities(self, entities: Iterable[KGEntity]) -> List[str]:
        uuids: List[str] = []
        with self._driver.session(database=self._database) as session:
            for e in entities:
                uuids.append(e.uuid)
                session.run(
                    """
                    MERGE (n:KGEntity {uuid:$uuid})
                    SET n.graph_id=$graph_id,
                        n.name=$name,
                        n.entity_type=$entity_type,
                        n.summary = CASE
                            WHEN $summary IS NULL OR $summary = "" THEN n.summary
                            ELSE $summary
                        END,
                        n.attributes_json = CASE
                            WHEN $attributes_json IS NULL OR $attributes_json = "{}" THEN n.attributes_json
                            ELSE $attributes_json
                        END,
                        n.source_entity_types = CASE
                            WHEN n.source_entity_types IS NULL THEN $source_entity_types
                            ELSE n.source_entity_types + [t IN $source_entity_types WHERE NOT t IN n.source_entity_types]
                        END,
                        n.created_at=COALESCE(n.created_at,$created_at)
                    """,
                    uuid=e.uuid,
                    graph_id=e.graph_id,
                    name=e.name,
                    entity_type=e.entity_type,
                    summary=e.summary or "",
                    attributes_json=json.dumps(e.attributes or {}, ensure_ascii=False),
                    source_entity_types=list(dict.fromkeys([t for t in (e.source_entity_types or []) if t])),
                    created_at=e.created_at or _now_iso(),
                )
        return uuids

    def upsert_chunk(self, chunk: KGChunk) -> None:
        preview = (chunk.text_preview or "").strip()
        # Keep Neo4j lean: store only a short preview; fetch full text from KB by kb_chunk_id when needed.
        if len(preview) > 480:
            preview = preview[:480] + "…"
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                MERGE (c:KGChunk {chunk_id:$chunk_id, graph_id:$graph_id})
                SET c.text_preview=$text_preview,
                    c.kb_doc_id=$kb_doc_id,
                    c.kb_chunk_id=$kb_chunk_id,
                    c.source=$source,
                    c.created_at=COALESCE(c.created_at,$created_at)
                WITH c
                MATCH (g:KGGraph {graph_id:$graph_id})
                MERGE (g)-[:HAS_CHUNK]->(c)
                """,
                chunk_id=chunk.chunk_id,
                graph_id=chunk.graph_id,
                text_preview=preview,
                kb_doc_id=(chunk.kb_doc_id or "").strip(),
                kb_chunk_id=(chunk.kb_chunk_id or "").strip(),
                source=(chunk.source or "").strip(),
                created_at=chunk.created_at or _now_iso(),
            )

    def link_mentions(self, *, chunk_id: str, entity_uuids: Iterable[str], graph_id: str) -> None:
        uuids = [u for u in entity_uuids if u]
        if not uuids:
            return
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                MATCH (c:KGChunk {chunk_id:$chunk_id, graph_id:$graph_id})
                UNWIND $entity_uuids AS uuid
                MATCH (e:KGEntity {uuid: uuid, graph_id:$graph_id})
                MERGE (c)-[:MENTIONS]->(e)
                """,
                chunk_id=chunk_id,
                graph_id=graph_id,
                entity_uuids=uuids,
            )

    def get_entity_mentions(self, *, graph_id: str, entity_uuid: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._driver.session(database=self._database) as session:
            rows = session.run(
                """
                MATCH (c:KGChunk {graph_id:$graph_id})-[:MENTIONS]->(e:KGEntity {uuid:$uuid, graph_id:$graph_id})
                RETURN c.chunk_id AS chunk_id,
                       COALESCE(c.text_preview, '') AS text_preview,
                       COALESCE(c.kb_doc_id, '') AS kb_doc_id,
                       COALESCE(c.kb_chunk_id, '') AS kb_chunk_id,
                       COALESCE(c.source, '') AS source,
                       c.created_at AS created_at
                ORDER BY c.created_at DESC
                LIMIT $limit
                """,
                graph_id=graph_id,
                uuid=entity_uuid,
                limit=int(limit),
            )
            out = []
            for r in rows:
                out.append(
                    {
                        "chunk_id": r["chunk_id"],
                        "text_preview": r["text_preview"],
                        "kb_doc_id": r["kb_doc_id"],
                        "kb_chunk_id": r["kb_chunk_id"],
                        "source": r["source"],
                        "created_at": r["created_at"],
                    }
                )
            return out

    def set_entity_interpretation(
        self,
        *,
        graph_id: str,
        entity_uuid: str,
        summary: str,
        key_facts: List[str],
        model_spec: str = "",
    ) -> bool:
        summary = (summary or "").strip()
        facts = [f.strip() for f in (key_facts or []) if (f or "").strip()]
        attrs = {"key_facts": facts}
        if model_spec:
            attrs["interpreted_by"] = model_spec
        attrs_json = json.dumps(attrs, ensure_ascii=False)

        with self._driver.session(database=self._database) as session:
            cur = session.run(
                """
                MATCH (e:KGEntity {uuid:$uuid, graph_id:$graph_id})
                SET e.summary=$summary,
                    e.attributes_json=$attributes_json,
                    e.interpreted_at=$interpreted_at
                RETURN count(e) AS n
                """,
                uuid=entity_uuid,
                graph_id=graph_id,
                summary=summary,
                attributes_json=attrs_json,
                interpreted_at=_now_iso(),
            ).single()
            return bool(cur and cur["n"] and int(cur["n"]) > 0)

    def set_graph_community_summaries(self, *, graph_id: str, summaries: List[Dict[str, Any]], model_spec: str = "") -> bool:
        payload = {"summaries": summaries, "model_spec": model_spec, "updated_at": _now_iso()}
        with self._driver.session(database=self._database) as session:
            cur = session.run(
                """
                MATCH (g:KGGraph {graph_id:$graph_id})
                SET g.community_summaries_json=$json,
                    g.community_summaries_updated_at=$updated_at
                RETURN count(g) AS n
                """,
                graph_id=graph_id,
                json=json.dumps(payload, ensure_ascii=False),
                updated_at=_now_iso(),
            ).single()
            return bool(cur and cur["n"] and int(cur["n"]) > 0)

    def get_graph_community_summaries(self, *, graph_id: str) -> Optional[Dict[str, Any]]:
        with self._driver.session(database=self._database) as session:
            row = session.run(
                "MATCH (g:KGGraph {graph_id:$graph_id}) RETURN g.community_summaries_json AS j",
                graph_id=graph_id,
            ).single()
            if not row:
                return None
            raw = row["j"]
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None

    def upsert_relations(self, relations: Iterable[KGRelation]) -> None:
        with self._driver.session(database=self._database) as session:
            for rel in relations:
                rel_uuid = rel.uuid or f"rel_{uuid.uuid4().hex[:16]}"
                session.run(
                    """
                    MATCH (s:KGEntity {uuid:$source_uuid})
                    MATCH (t:KGEntity {uuid:$target_uuid})
                    MERGE (s)-[r:KG_REL {uuid:$uuid}]->(t)
                    SET r.graph_id=$graph_id,
                        r.name=$name,
                        r.fact=$fact,
                        r.attributes_json=$attributes_json,
                        r.created_at=COALESCE(r.created_at,$created_at)
                    """,
                    uuid=rel_uuid,
                    graph_id=rel.graph_id,
                    source_uuid=rel.source_uuid,
                    target_uuid=rel.target_uuid,
                    name=rel.relation_name,
                    fact=rel.fact or "",
                    attributes_json=json.dumps(rel.attributes or {}, ensure_ascii=False),
                    created_at=rel.created_at or _now_iso(),
                )

    def get_graph_data(self, graph_id: str, limit: int = 1500) -> Dict[str, Any]:
        with self._driver.session(database=self._database) as session:
            node_rows = session.run(
                """
                MATCH (e:KGEntity {graph_id:$graph_id})
                RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type, e.summary AS summary, e.attributes_json AS attributes_json
                LIMIT $limit
                """,
                graph_id=graph_id,
                limit=limit,
            )
            nodes = []
            name_map = {}
            for r in node_rows:
                attrs = {}
                try:
                    attrs = json.loads(r["attributes_json"] or "{}")
                except Exception:
                    attrs = {}
                name_map[r["uuid"]] = r["name"] or ""
                nodes.append(
                    {
                        "id": r["uuid"],
                        "label": r["name"] or r["uuid"],
                        "type": r["entity_type"] or "Entity",
                        "summary": r["summary"] or "",
                        "attributes": attrs,
                    }
                )

            edge_rows = session.run(
                """
                MATCH (s:KGEntity {graph_id:$graph_id})-[r:KG_REL {graph_id:$graph_id}]->(t:KGEntity {graph_id:$graph_id})
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact, r.attributes_json AS attributes_json,
                       s.uuid AS source_uuid, t.uuid AS target_uuid
                LIMIT $limit
                """,
                graph_id=graph_id,
                limit=limit,
            )
            edges = []
            for r in edge_rows:
                attrs = {}
                try:
                    attrs = json.loads(r["attributes_json"] or "{}")
                except Exception:
                    attrs = {}
                edges.append(
                    {
                        "id": r["uuid"],
                        "from": r["source_uuid"],
                        "to": r["target_uuid"],
                        "label": r["name"] or "",
                        "fact": r["fact"] or "",
                        "attributes": attrs,
                    }
                )

        return {"graph_id": graph_id, "nodes": nodes, "edges": edges}

    def query_subgraph(self, graph_id: str, q: str, limit_nodes: int = 30) -> Dict[str, Any]:
        q = (q or "").strip().lower()
        if not q:
            return {"graph_id": graph_id, "nodes": [], "edges": []}
        with self._driver.session(database=self._database) as session:
            # First pick seed nodes by name contains.
            seed_rows = session.run(
                """
                MATCH (e:KGEntity {graph_id:$graph_id})
                WHERE toLower(e.name) CONTAINS $q
                RETURN e.uuid AS uuid
                LIMIT $limit
                """,
                graph_id=graph_id,
                q=q,
                limit=limit_nodes,
            )
            seeds = [r["uuid"] for r in seed_rows]
            if not seeds:
                return {"graph_id": graph_id, "nodes": [], "edges": []}

            rows = session.run(
                """
                MATCH (a:KGEntity {graph_id:$graph_id})
                WHERE a.uuid IN $seeds
                OPTIONAL MATCH (a)-[r:KG_REL {graph_id:$graph_id}]-(b:KGEntity {graph_id:$graph_id})
                RETURN a, r, b
                """,
                graph_id=graph_id,
                seeds=seeds,
            )
            nodes = {}
            edges = {}
            for rec in rows:
                for key in ("a", "b"):
                    n = rec.get(key)
                    if n is None:
                        continue
                    nodes[n["uuid"]] = {"id": n["uuid"], "label": n.get("name") or n["uuid"], "type": n.get("entity_type") or "Entity"}
                r = rec.get("r")
                if r is not None:
                    edges[r["uuid"]] = {
                        "id": r["uuid"],
                        "from": rec["a"]["uuid"],
                        "to": rec["b"]["uuid"],
                        "label": r.get("name") or "",
                        "fact": r.get("fact") or "",
                    }
            return {"graph_id": graph_id, "nodes": list(nodes.values()), "edges": list(edges.values())}
