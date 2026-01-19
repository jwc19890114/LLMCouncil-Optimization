from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import storage
from ..jobs_store import Job
from ..tool_context import ToolContext
from ..web_search import ddg_search


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    payload = job.payload or {}
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}

    conversation_id = str(job.conversation_id or "").strip()
    doc_ids: Optional[List[str]] = None
    if conversation_id:
        conv = storage.get_conversation(conversation_id) or {}
        ids = conv.get("kb_doc_ids") or []
        if isinstance(ids, list) and ids:
            doc_ids = [str(x).strip() for x in ids if str(x).strip()]

    max_web = max(0, min(20, int(payload.get("max_web_results") or 5)))
    max_kb = max(1, min(20, int(payload.get("max_kb_chunks") or 6)))

    update_progress(0.05)
    web_results = await ddg_search(query, max_results=max_web) if max_web > 0 else []
    update_progress(0.45)

    # KB evidence: stable FTS-only (no embeddings/rerank) for speed and determinism.
    kb_hits = ctx.kb_retriever.kb.search(query=query, doc_ids=doc_ids, agent_id=None, categories=None, limit=max_kb)
    update_progress(0.85)

    web = [r.__dict__ for r in web_results]
    kb = [
        {
            "chunk_id": h.get("chunk_id"),
            "doc_id": h.get("doc_id"),
            "title": h.get("title"),
            "source": h.get("source"),
            "score": h.get("score"),
            "text": (h.get("text") or "")[:900],
        }
        for h in (kb_hits or [])
    ]

    summary_lines = [f"证据整理完成：网页 {len(web)} 条，KB 片段 {len(kb)} 条。"]
    if web:
        summary_lines.append(f"- Web Top1: {web[0].get('title','')} ({web[0].get('url','')})")
    if kb:
        summary_lines.append(f"- KB Top1: KB[{kb[0].get('doc_id')}] chunk={kb[0].get('chunk_id')}")

    update_progress(1.0)
    return {
        "type": "evidence_pack",
        "summary": "\n".join(summary_lines),
        "query": query,
        "web": web,
        "kb": kb,
        "scoped_doc_ids": doc_ids or [],
    }

