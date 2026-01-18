"""Stable local knowledge base (SQLite + FTS5)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import KB_DB_PATH


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass(frozen=True)
class KBDocument:
    id: str
    title: str
    source: str
    agent_ids: List[str]
    created_at: str


@dataclass(frozen=True)
class KBChunk:
    id: str
    doc_id: str
    text: str
    created_at: str


class KBStore:
    def __init__(self, db_path: str = KB_DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  source TEXT NOT NULL,
                  text TEXT NOT NULL DEFAULT '',
                  categories_json TEXT NOT NULL DEFAULT '[]',
                  agent_ids_json TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kb_chunks (
                  id TEXT PRIMARY KEY,
                  doc_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                  text TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                -- FTS5 virtual table for chunk text search
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
                  chunk_id UNINDEXED,
                  doc_id UNINDEXED,
                  text,
                  tokenize = 'unicode61'
                );

                CREATE TABLE IF NOT EXISTS kb_chunk_embeddings (
                  chunk_id TEXT PRIMARY KEY,
                  model_spec TEXT NOT NULL,
                  vector_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS kb_chunks_doc_id ON kb_chunks(doc_id);
                CREATE INDEX IF NOT EXISTS kb_chunk_embeddings_model ON kb_chunk_embeddings(model_spec);
                """
            )
            # Lightweight migration for older DBs.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(kb_documents)").fetchall()}
            if "text" not in cols:
                conn.execute("ALTER TABLE kb_documents ADD COLUMN text TEXT NOT NULL DEFAULT ''")
            if "categories_json" not in cols:
                conn.execute("ALTER TABLE kb_documents ADD COLUMN categories_json TEXT NOT NULL DEFAULT '[]'")

    def add_document(
        self,
        *,
        doc_id: str,
        title: str,
        source: str,
        text: str,
        categories: Optional[List[str]] = None,
        agent_ids: Optional[List[str]] = None,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> Dict[str, Any]:
        import json
        import uuid

        agent_ids = agent_ids or []
        categories = categories or []
        created_at = _now_iso()
        chunks = _chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kb_documents(id,title,source,text,categories_json,agent_ids_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (doc_id, title, source, text, json.dumps(categories, ensure_ascii=False), json.dumps(agent_ids, ensure_ascii=False), created_at),
            )
            for c in chunks:
                chunk_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO kb_chunks(id,doc_id,text,created_at) VALUES(?,?,?,?)",
                    (chunk_id, doc_id, c, created_at),
                )
                conn.execute(
                    "INSERT INTO kb_chunks_fts(chunk_id,doc_id,text) VALUES(?,?,?)",
                    (chunk_id, doc_id, c),
                )

        return {"doc_id": doc_id, "chunks": len(chunks)}

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        import json

        with self._connect() as conn:
            doc = conn.execute(
                "SELECT id,title,source,text,categories_json,agent_ids_json,created_at FROM kb_documents WHERE id=?",
                (doc_id,),
            ).fetchone()
            if doc is None:
                return None

            text = doc["text"] or ""
            if not text:
                # Backfill for older rows: reconstruct from chunks (may include overlap).
                rows = conn.execute(
                    "SELECT text FROM kb_chunks WHERE doc_id=? ORDER BY created_at ASC",
                    (doc_id,),
                ).fetchall()
                text = "\n".join([r["text"] for r in rows])

        return {
            "id": doc["id"],
            "title": doc["title"],
            "source": doc["source"],
            "text": text,
            "categories": json.loads(doc["categories_json"] or "[]"),
            "agent_ids": json.loads(doc["agent_ids_json"] or "[]"),
            "created_at": doc["created_at"],
        }

    def list_documents(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,title,source,categories_json,agent_ids_json,created_at FROM kb_documents ORDER BY created_at DESC"
            ).fetchall()
        out: List[Dict[str, Any]] = []
        import json

        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "source": r["source"],
                    "categories": json.loads(r["categories_json"] or "[]"),
                    "agent_ids": json.loads(r["agent_ids_json"] or "[]"),
                    "created_at": r["created_at"],
                }
            )
        return out

    def delete_document(self, doc_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM kb_chunks_fts WHERE doc_id=?", (doc_id,))
            cur = conn.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
            return cur.rowcount > 0

    def set_document_agents(self, doc_id: str, agent_ids: List[str]) -> bool:
        import json

        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE kb_documents SET agent_ids_json=? WHERE id=?",
                (json.dumps(agent_ids, ensure_ascii=False), doc_id),
            )
            return cur.rowcount > 0

    def set_document_categories(self, doc_id: str, categories: List[str]) -> bool:
        import json

        cats = [c.strip() for c in (categories or []) if (c or "").strip()]
        # De-duplicate while preserving order
        seen = set()
        deduped = []
        for c in cats:
            if c in seen:
                continue
            seen.add(c)
            deduped.append(c)

        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE kb_documents SET categories_json=? WHERE id=?",
                (json.dumps(deduped, ensure_ascii=False), doc_id),
            )
            return cur.rowcount > 0

    def search(
        self,
        *,
        query: str,
        agent_id: Optional[str] = None,
        doc_ids: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search chunks. Returns top chunks with doc metadata.
        Note: FTS5 BM25 ranking is stable and does not require embeddings.
        """
        import json

        with self._connect() as conn:
            where = []
            params: List[Any] = []
            if doc_ids:
                placeholders = ",".join(["?"] * len(doc_ids))
                where.append(f"d.id IN ({placeholders})")
                params.extend(doc_ids)

            # Filter by agent_id via document metadata
            if agent_id:
                where.append("d.agent_ids_json LIKE ?")
                params.append(f'%"{agent_id}"%')

            if categories:
                cats = [c.strip() for c in categories if (c or "").strip()]
                if cats:
                    where.append("(" + " OR ".join(["d.categories_json LIKE ?"] * len(cats)) + ")")
                    params.extend([f'%"{c}"%' for c in cats])

            where_sql = ("WHERE " + " AND ".join(where)) if where else ""

            match = _fts_query(query)
            if not match:
                return []
            rows = conn.execute(
                f"""
                SELECT f.chunk_id AS chunk_id, f.doc_id AS doc_id, f.text AS text,
                       bm25(kb_chunks_fts) AS score,
                       d.title AS title, d.source AS source, d.categories_json AS categories_json, d.agent_ids_json AS agent_ids_json
                FROM kb_chunks_fts f
                JOIN kb_documents d ON d.id = f.doc_id
                {where_sql}
                AND kb_chunks_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (*params, match, limit),
            ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "chunk_id": r["chunk_id"],
                    "doc_id": r["doc_id"],
                    "score": float(r["score"]),
                    "text": r["text"],
                    "title": r["title"],
                    "source": r["source"],
                    "categories": json.loads(r["categories_json"] or "[]"),
                    "agent_ids": json.loads(r["agent_ids_json"] or "[]"),
                }
            )
        return out

    def list_chunks(
        self,
        *,
        agent_id: Optional[str] = None,
        doc_ids: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        """
        List chunks with doc metadata. Used for semantic search.
        """
        import json

        with self._connect() as conn:
            where = []
            params: List[Any] = []

            if doc_ids:
                placeholders = ",".join(["?"] * len(doc_ids))
                where.append(f"d.id IN ({placeholders})")
                params.extend(doc_ids)

            if agent_id:
                where.append("d.agent_ids_json LIKE ?")
                params.append(f'%\"{agent_id}\"%')

            if categories:
                cats = [c.strip() for c in categories if (c or "").strip()]
                if cats:
                    where.append("(" + " OR ".join(["d.categories_json LIKE ?"] * len(cats)) + ")")
                    params.extend([f'%\"{c}\"%' for c in cats])

            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            rows = conn.execute(
                f"""
                SELECT c.id AS chunk_id, c.doc_id AS doc_id, c.text AS text, c.created_at AS created_at,
                       d.title AS title, d.source AS source, d.categories_json AS categories_json, d.agent_ids_json AS agent_ids_json
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.doc_id
                {where_sql}
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "chunk_id": r["chunk_id"],
                    "doc_id": r["doc_id"],
                    "text": r["text"],
                    "title": r["title"],
                    "source": r["source"],
                    "categories": json.loads(r["categories_json"] or "[]"),
                    "agent_ids": json.loads(r["agent_ids_json"] or "[]"),
                    "created_at": r["created_at"],
                }
            )
        return out

    def get_chunk_embeddings(self, *, chunk_ids: List[str], model_spec: str) -> Dict[str, List[float]]:
        import json

        if not chunk_ids:
            return {}
        placeholders = ",".join(["?"] * len(chunk_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, vector_json FROM kb_chunk_embeddings WHERE model_spec=? AND chunk_id IN ({placeholders})",
                (model_spec, *chunk_ids),
            ).fetchall()
        out: Dict[str, List[float]] = {}
        for r in rows:
            try:
                out[r["chunk_id"]] = list(json.loads(r["vector_json"]))
            except Exception:
                continue
        return out

    def set_chunk_embeddings(self, *, items: Dict[str, List[float]], model_spec: str) -> int:
        import json

        if not items:
            return 0
        created_at = _now_iso()
        with self._connect() as conn:
            for chunk_id, vec in items.items():
                conn.execute(
                    """
                    INSERT INTO kb_chunk_embeddings(chunk_id,model_spec,vector_json,created_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                      model_spec=excluded.model_spec,
                      vector_json=excluded.vector_json,
                      created_at=excluded.created_at
                    """,
                    (chunk_id, model_spec, json.dumps(vec), created_at),
                )
        return len(items)


def _chunk_text(text: str, *, chunk_size: int, overlap: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Simple stable chunker by character length.
    chunks: List[str] = []
    i = 0
    step = max(1, chunk_size - overlap)
    while i < len(text):
        chunk = text[i : i + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        i += step
    return chunks


def _fts_query(q: str) -> str:
    # Safe fallback: phrase query.
    q = (q or "").strip().replace('"', " ")
    if not q:
        return ""
    return f"\"{q}\""
