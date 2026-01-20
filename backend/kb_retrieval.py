"""Hybrid KB retrieval: FTS + embeddings + LLM rerank."""

from __future__ import annotations

import math
import heapq
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from .kb_store import KBStore
from .cache_utils import TTLCache
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
        self._query_embedding_cache: TTLCache[tuple[str, str], List[float]] = TTLCache(capacity=256, ttl_seconds=3600.0)
        self._search_cache: TTLCache[str, List[Dict[str, Any]]] = TTLCache(capacity=256, ttl_seconds=90.0)

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
        pool = max(0, int(pool))
        top_k = max(1, int(top_k))
        chunks = self.kb.list_chunks(
            agent_id=agent_id,
            doc_ids=doc_ids,
            categories=categories,
            limit=pool,
            include_text=False,
        )
        if not chunks:
            return []

        q_cache_key = (embedding_model_spec, query)
        qvec = self._query_embedding_cache.get(q_cache_key)
        if not qvec:
            qvecs = await embed_texts(embedding_model_spec, [query], silent=True)
            if not qvecs or not qvecs[0]:
                return []
            qvec = qvecs[0]
            if isinstance(qvec, list) and qvec:
                self._query_embedding_cache.set(q_cache_key, qvec)

        meta_by_id = {c["chunk_id"]: c for c in chunks if c.get("chunk_id")}
        chunk_ids = list(meta_by_id.keys())

        # Stream-scoring: compute cosine in batches and only keep top-K heap.
        heap: List[Tuple[float, str]] = []  # (score, chunk_id) min-heap
        batch_size = 128
        for i in range(0, len(chunk_ids), batch_size):
            batch_ids = chunk_ids[i : i + batch_size]
            embeddings = self.kb.get_chunk_embeddings(chunk_ids=batch_ids, model_spec=embedding_model_spec)
            missing = [cid for cid in batch_ids if cid not in embeddings]

            # Best-effort: fill missing embeddings (small batches) to improve recall.
            if missing:
                texts = self.kb.get_chunk_texts(chunk_ids=missing)
                text_list = [texts.get(cid, "") for cid in missing]
                vecs = await embed_texts(embedding_model_spec, text_list, silent=True)
                if vecs and len(vecs) == len(missing):
                    new_items: Dict[str, List[float]] = {}
                    for cid, v in zip(missing, vecs):
                        if isinstance(v, list) and v:
                            new_items[cid] = v
                    if new_items:
                        self.kb.set_chunk_embeddings(items=new_items, model_spec=embedding_model_spec)
                        embeddings.update(new_items)

            for cid, v in embeddings.items():
                if not v:
                    continue
                score = _cosine(qvec, v)
                if len(heap) < top_k:
                    heapq.heappush(heap, (score, cid))
                else:
                    if score > heap[0][0]:
                        heapq.heapreplace(heap, (score, cid))

        if not heap:
            return []

        scored = sorted(heap, key=lambda x: x[0], reverse=True)
        top_ids = [cid for _, cid in scored]
        score_map = {cid: float(score) for score, cid in scored}

        details = self.kb.get_chunk_details(chunk_ids=top_ids)
        out: List[Dict[str, Any]] = []
        for d in details:
            cid = d.get("chunk_id")
            if not cid:
                continue
            out.append(
                {
                    "chunk_id": cid,
                    "doc_id": d.get("doc_id"),
                    "semantic_score": score_map.get(cid, 0.0),
                    "text": d.get("text") or "",
                    "title": d.get("title") or "",
                    "source": d.get("source") or "",
                    "categories": d.get("categories") or [],
                    "agent_ids": d.get("agent_ids") or [],
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

        # Short TTL cache to reduce repeated work (embedding/rerank) in chat UIs.
        # Include kb revision so writes invalidate the cache in-process.
        try:
            cache_key = json.dumps(
                {
                    "rev": int(getattr(self.kb, "revision", 0)),
                    "q": query,
                    "agent_id": agent_id or "",
                    "doc_ids": doc_ids or [],
                    "categories": categories or [],
                    "limit": limit,
                    "mode": mode,
                    "embedding_model_spec": embedding_model_spec or "",
                    "enable_rerank": bool(enable_rerank),
                    "rerank_model_spec": rerank_model_spec or "",
                    "semantic_pool": int(semantic_pool),
                    "initial_k": int(initial_k),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except Exception:
            cache_key = ""
        if cache_key:
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                return [dict(x) for x in cached]

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
                if cache_key:
                    self._search_cache.set(cache_key, [dict(x) for x in out])
                return out

        # Fallback: heuristic top-N
        out = []
        for item in pool_items[:limit]:
            item = dict(item)
            item["retrieval"] = sorted(list(item.get("retrieval") or []))
            out.append(item)
        if cache_key:
            self._search_cache.set(cache_key, [dict(x) for x in out])
        return out

    async def index_embeddings(
        self,
        *,
        embedding_model_spec: str,
        agent_id: Optional[str] = None,
        doc_ids: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        pool: int = 5000,
        check_cancelled: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        if not embedding_model_spec:
            return {"ok": False, "error": "KB_EMBEDDING_MODEL 未配置"}

        pool = max(0, int(pool))
        chunks = self.kb.list_chunks(
            agent_id=agent_id,
            doc_ids=doc_ids,
            categories=categories,
            limit=pool,
            include_text=False,
        )
        chunk_ids = [c["chunk_id"] for c in chunks if c.get("chunk_id")]

        batch_size = 128
        embed_batch = 32
        indexed = 0
        for i in range(0, len(chunk_ids), batch_size):
            if check_cancelled:
                check_cancelled()
            batch_ids = chunk_ids[i : i + batch_size]
            existing = self.kb.get_chunk_embeddings(chunk_ids=batch_ids, model_spec=embedding_model_spec)
            missing = [cid for cid in batch_ids if cid not in existing]
            if not missing:
                continue

            texts = self.kb.get_chunk_texts(chunk_ids=missing)
            for j in range(0, len(missing), embed_batch):
                if check_cancelled:
                    check_cancelled()
                part_ids = missing[j : j + embed_batch]
                part_texts = [texts.get(cid, "") for cid in part_ids]
                vecs = await embed_texts(embedding_model_spec, part_texts)
                if not vecs or len(vecs) != len(part_ids):
                    continue
                items: Dict[str, List[float]] = {}
                for cid, v in zip(part_ids, vecs):
                    if isinstance(v, list) and v:
                        items[cid] = v
                if items:
                    self.kb.set_chunk_embeddings(items=items, model_spec=embedding_model_spec)
                    indexed += len(items)

        return {"ok": True, "indexed": indexed, "total": len(chunk_ids)}
