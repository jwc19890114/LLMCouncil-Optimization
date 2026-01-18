"""Hybrid KB retrieval: FTS + embeddings + LLM rerank."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .kb_store import KBStore
from .llm_client import embed_texts
from .rerank import rerank


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom <= 0:
        return 0.0
    return dot / denom


def _fts_quality(score: float) -> float:
    # SQLite bm25: lower is better. Convert into (0,1] where higher is better.
    s = float(score)
    return 1.0 / (1.0 + abs(s))


class KBHybridRetriever:
    def __init__(self, kb: KBStore):
        self.kb = kb

    async def _semantic_search(
        self,
        *,
        query: str,
        embedding_model_spec: str,
        agent_id: Optional[str],
        doc_ids: Optional[List[str]],
        categories: Optional[List[str]],
        pool: int,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        chunks = self.kb.list_chunks(agent_id=agent_id, doc_ids=doc_ids, categories=categories, limit=pool)
        if not chunks:
            return []

        qvecs = await embed_texts(embedding_model_spec, [query])
        if not qvecs or not qvecs[0]:
            return []
        qvec = qvecs[0]

        chunk_ids = [c["chunk_id"] for c in chunks]
        existing = self.kb.get_chunk_embeddings(chunk_ids=chunk_ids, model_spec=embedding_model_spec)
        missing = [cid for cid in chunk_ids if cid not in existing]

        # Best-effort: fill missing embeddings in batches.
        if missing:
            id_to_text = {c["chunk_id"]: (c.get("text") or "") for c in chunks}
            batch_size = 32
            new_items: Dict[str, List[float]] = {}
            for i in range(0, len(missing), batch_size):
                batch_ids = missing[i : i + batch_size]
                batch_texts = [id_to_text.get(cid, "") for cid in batch_ids]
                vecs = await embed_texts(embedding_model_spec, batch_texts)
                if not vecs or len(vecs) != len(batch_ids):
                    continue
                for cid, v in zip(batch_ids, vecs):
                    if isinstance(v, list) and v:
                        new_items[cid] = v
            if new_items:
                self.kb.set_chunk_embeddings(items=new_items, model_spec=embedding_model_spec)
                existing.update(new_items)

        scored: List[Tuple[str, float]] = []
        for cid in chunk_ids:
            v = existing.get(cid)
            if not v:
                continue
            scored.append((cid, _cosine(qvec, v)))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = {cid for cid, _ in scored[:top_k]}
        score_map = {cid: s for cid, s in scored[:top_k]}

        out: List[Dict[str, Any]] = []
        for c in chunks:
            if c["chunk_id"] not in top:
                continue
            out.append(
                {
                    "chunk_id": c["chunk_id"],
                    "doc_id": c["doc_id"],
                    "semantic_score": score_map.get(c["chunk_id"], 0.0),
                    "text": c.get("text") or "",
                    "title": c.get("title") or "",
                    "source": c.get("source") or "",
                    "categories": c.get("categories") or [],
                    "agent_ids": c.get("agent_ids") or [],
                }
            )
        out.sort(key=lambda x: x.get("semantic_score", 0.0), reverse=True)
        return out[:top_k]

    async def search(
        self,
        *,
        query: str,
        agent_id: Optional[str],
        doc_ids: Optional[List[str]],
        categories: Optional[List[str]],
        limit: int,
        mode: str,
        embedding_model_spec: str,
        enable_rerank: bool,
        rerank_model_spec: str,
        semantic_pool: int,
        initial_k: int,
    ) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        mode = (mode or "hybrid").strip().lower()
        limit = max(1, min(50, int(limit)))
        initial_k = max(limit, int(initial_k or max(limit * 4, 24)))

        fts_hits: List[Dict[str, Any]] = []
        sem_hits: List[Dict[str, Any]] = []

        if mode in ("fts", "hybrid"):
            fts_hits = self.kb.search(
                query=query, agent_id=agent_id, doc_ids=doc_ids, categories=categories, limit=initial_k
            )

        if mode in ("semantic", "hybrid") and embedding_model_spec:
            try:
                sem_hits = await self._semantic_search(
                    query=query,
                    embedding_model_spec=embedding_model_spec,
                    agent_id=agent_id,
                    doc_ids=doc_ids,
                    categories=categories,
                    pool=semantic_pool,
                    top_k=initial_k,
                )
            except Exception:
                sem_hits = []

        combined: Dict[str, Dict[str, Any]] = {}
        for h in fts_hits:
            cid = h.get("chunk_id")
            if not cid:
                continue
            item = combined.setdefault(cid, {})
            item.update(h)
            item["fts_score"] = float(h.get("score", 0.0))
            item["fts_quality"] = _fts_quality(item["fts_score"])
            item.setdefault("semantic_score", 0.0)
            item.setdefault("retrieval", set()).add("fts")

        for h in sem_hits:
            cid = h.get("chunk_id")
            if not cid:
                continue
            item = combined.setdefault(cid, {})
            item.setdefault("chunk_id", cid)
            item.setdefault("doc_id", h.get("doc_id"))
            item.setdefault("text", h.get("text") or "")
            item.setdefault("title", h.get("title") or "")
            item.setdefault("source", h.get("source") or "")
            item.setdefault("categories", h.get("categories") or [])
            item.setdefault("agent_ids", h.get("agent_ids") or [])
            item["semantic_score"] = float(h.get("semantic_score", 0.0))
            item.setdefault("fts_score", 0.0)
            item.setdefault("fts_quality", 0.0)
            item.setdefault("retrieval", set()).add("semantic")

        if not combined:
            return []

        def heuristic_score(x: Dict[str, Any]) -> float:
            # Blend with a slight preference to semantic when present.
            return 0.65 * float(x.get("semantic_score", 0.0)) + 0.35 * float(x.get("fts_quality", 0.0))

        pool_items = list(combined.values())
        pool_items.sort(key=heuristic_score, reverse=True)
        pool_items = pool_items[: max(initial_k, limit * 6)]

        # Optional rerank (best-effort)
        if enable_rerank and rerank_model_spec:
            try:
                rr = await rerank(
                    model_spec=rerank_model_spec,
                    query=query,
                    candidates=pool_items,
                    top_k=limit,
                )
            except Exception:
                rr = []
            if rr:
                out = []
                for r in rr:
                    idx = r["index"]
                    score = r["score"]
                    item = dict(pool_items[idx])
                    item["rerank_score"] = score
                    item["retrieval"] = sorted(list(item.get("retrieval") or []))
                    out.append(item)
                return out

        # Fallback: heuristic top-N
        out = []
        for item in pool_items[:limit]:
            item = dict(item)
            item["retrieval"] = sorted(list(item.get("retrieval") or []))
            out.append(item)
        return out

    async def index_embeddings(
        self,
        *,
        embedding_model_spec: str,
        agent_id: Optional[str] = None,
        doc_ids: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        pool: int = 5000,
    ) -> Dict[str, Any]:
        if not embedding_model_spec:
            return {"ok": False, "error": "KB_EMBEDDING_MODEL 未配置"}

        chunks = self.kb.list_chunks(agent_id=agent_id, doc_ids=doc_ids, categories=categories, limit=pool)
        chunk_ids = [c["chunk_id"] for c in chunks]
        existing = self.kb.get_chunk_embeddings(chunk_ids=chunk_ids, model_spec=embedding_model_spec)
        missing = [cid for cid in chunk_ids if cid not in existing]
        if not missing:
            return {"ok": True, "indexed": 0, "total": len(chunk_ids)}

        id_to_text = {c["chunk_id"]: (c.get("text") or "") for c in chunks}
        batch_size = 32
        indexed = 0
        for i in range(0, len(missing), batch_size):
            batch_ids = missing[i : i + batch_size]
            batch_texts = [id_to_text.get(cid, "") for cid in batch_ids]
            vecs = await embed_texts(embedding_model_spec, batch_texts)
            if not vecs or len(vecs) != len(batch_ids):
                continue
            items: Dict[str, List[float]] = {}
            for cid, v in zip(batch_ids, vecs):
                if isinstance(v, list) and v:
                    items[cid] = v
            if items:
                self.kb.set_chunk_embeddings(items=items, model_spec=embedding_model_spec)
                indexed += len(items)

        return {"ok": True, "indexed": indexed, "total": len(chunk_ids)}
