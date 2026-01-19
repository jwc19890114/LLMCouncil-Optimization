from __future__ import annotations

from typing import Any, Dict

from ..jobs_store import Job
from ..tool_context import ToolContext
from ..web_search import ddg_search


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    payload = job.payload or {}
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}
    max_results = int(payload.get("max_results") or 5)
    max_results = max(0, min(20, max_results))

    update_progress(0.1)
    results = await ddg_search(query, max_results=max_results)
    update_progress(1.0)

    data = [r.__dict__ for r in results]
    summary = f"网页检索完成：{len(data)} 条结果。"
    if data:
        summary += f" Top1: {data[0].get('title','')} ({data[0].get('url','')})"

    return {
        "type": "web_search",
        "summary": summary,
        "query": query,
        "results": data,
    }

