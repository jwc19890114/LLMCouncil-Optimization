from __future__ import annotations

from typing import Any, Dict

from .. import settings_store
from ..jobs_store import Job
from ..tool_context import ToolContext


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    ctx.check_job_cancelled(job.id)
    payload = job.payload or {}
    settings = settings_store.get_settings()
    model = str(payload.get("embedding_model") or settings.kb_embedding_model or "").strip()
    if not model:
        return {"ok": False, "error": "KB embedding model not configured"}

    update_progress(0.1)
    out = await ctx.kb_retriever.index_embeddings(
        embedding_model_spec=model,
        agent_id=(payload.get("agent_id") or "").strip() or None,
        doc_ids=payload.get("doc_ids"),
        categories=payload.get("categories"),
        pool=int(payload.get("pool") or 5000),
        check_cancelled=lambda: ctx.check_job_cancelled(job.id),
    )
    update_progress(1.0)
    return {
        "type": "kb_index",
        "summary": f"知识库 embedding 已完成：indexed={out.get('indexed',0)} / total={out.get('total',0)}（model={model}）",
        "data": out,
    }
