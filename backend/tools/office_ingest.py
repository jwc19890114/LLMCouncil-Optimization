from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List

from .. import storage, settings_store
from ..jobs_store import Job
from ..office_extract import extract_office_text
from ..tool_context import ToolContext


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    payload = job.payload or {}
    path_raw = str(payload.get("path") or "").strip()
    if not path_raw:
        return {"ok": False, "error": "path required"}

    path = Path(path_raw)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"file not found: {path_raw}"}

    max_chars = int(payload.get("max_chars") or 2_000_000)
    max_cells = int(payload.get("max_cells") or 50_000)
    title = str(payload.get("title") or path.stem or path.name).strip() or path.name
    source = str(payload.get("source") or f"file:{path_raw}").strip()
    categories: List[str] = payload.get("categories") or ["upload"]
    agent_ids: List[str] = payload.get("agent_ids") or []
    write_kb = bool(payload.get("write_kb", True))
    doc_id = str(payload.get("doc_id") or "").strip() or uuid.uuid4().hex

    update_progress(0.1)
    try:
        text = extract_office_text(path, max_chars=max_chars, max_cells=max_cells)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not text.strip():
        return {"ok": False, "error": "no text extracted"}

    update_progress(0.55)
    kb_result = None
    if write_kb:
        try:
            # Replace deterministically if doc_id already exists.
            try:
                ctx.kb_retriever.kb.delete_document(doc_id)
            except Exception:
                pass
            kb_result = ctx.kb_retriever.kb.add_document(
                doc_id=doc_id,
                title=title,
                source=source,
                text=text,
                categories=categories,
                agent_ids=agent_ids,
            )
        except Exception as e:
            return {"ok": False, "error": f"kb add failed: {e}"}

    update_progress(0.8)
    conversation_id = str(job.conversation_id or "").strip()
    if write_kb and conversation_id:
        try:
            conv = storage.get_conversation(conversation_id)
            if conv is not None:
                existing = conv.get("kb_doc_ids") or []
                merged = list(existing) + [doc_id]
                storage.update_conversation_kb_doc_ids(conversation_id, merged)
        except Exception:
            pass

    # Optional: index embeddings for this doc (best-effort)
    settings = settings_store.get_settings()
    model = str(payload.get("embedding_model") or settings.kb_embedding_model or "").strip()
    should_index = bool(payload.get("index_embeddings", False)) and bool(model) and write_kb
    embeddings = None
    if should_index:
        try:
            embeddings = await ctx.kb_retriever.index_embeddings(
                embedding_model_spec=model,
                doc_ids=[doc_id],
                pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
            )
        except Exception:
            embeddings = None

    update_progress(1.0)
    return {
        "type": "office_ingest",
        "summary": f"Office 文档已解析：{path.name} -> KB[{doc_id}]",
        "doc_id": doc_id,
        "title": title,
        "source": source,
        "chars": len(text),
        "kb": kb_result,
        "embeddings": embeddings,
        "conversation_id": conversation_id,
    }

