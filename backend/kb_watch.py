"""Continuous KB ingestion from watched folders (polling-based).

This is a lightweight, dependency-free alternative to filesystem watchers:
- Periodically scans configured roots for allowed file extensions
- Ingests new/changed files into the KB
- Removes deleted files from KB

Designed to be safe-by-default (feature can be disabled via settings).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .kb_store import KBStore
from .kb_retrieval import KBHybridRetriever
from . import settings_store


def _norm_path(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _is_hidden_path(p: Path) -> bool:
    parts = [x for x in p.parts if x]
    for part in parts:
        if part.startswith("."):
            return True
        if part.startswith("~$"):  # common Office temp prefix
            return True
    return False


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_doc_id_for_path(path_key: str) -> str:
    # Stable ID derived from normalized path (rename will produce a new doc_id).
    return "file_" + hashlib.sha1(path_key.encode("utf-8")).hexdigest()


def _extract_text(path: Path, *, max_chars: int = 2_000_000) -> str:
    """
    Best-effort text extraction for watched files.
    Supported by default: .txt/.md/.log/.json
    Optional (if dependencies installed): .docx/.xlsx
    """
    ext = path.suffix.lower().lstrip(".")
    if ext in ("txt", "md", "log"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]
    if ext == "json":
        import json

        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            text = json.dumps(obj, ensure_ascii=False, indent=2)
            return text[:max_chars]
        except Exception:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return text[:max_chars]
    if ext in ("docx", "xlsx"):
        try:
            from .office_extract import extract_office_text

            return extract_office_text(path, max_chars=max_chars)
        except Exception:
            return ""
    # Unknown extension: fallback to UTF-8 best-effort
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]
    except Exception:
        return ""


def _derive_categories(root: Path, file_path: Path) -> List[str]:
    # Use folder names as lightweight tags (bounded to avoid explosion).
    try:
        rel = file_path.relative_to(root)
    except Exception:
        rel = file_path.name
    parts = [p for p in Path(rel).parts[:-1] if p and p not in (".", "..")]
    cats = ["kb_watch"]
    for p in parts[:6]:
        val = str(p).strip()
        if val:
            cats.append(val)
    # De-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for c in cats:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


@dataclass
class KBWatchStatus:
    running: bool
    roots: List[str]
    exts: List[str]
    interval_seconds: int
    max_file_mb: int
    last_scan_at: Optional[float]
    last_error: str
    ingested_total: int
    deleted_total: int


class KBWatchService:
    def __init__(self, kb: KBStore, kb_retriever: KBHybridRetriever):
        self.kb = kb
        self.kb_retriever = kb_retriever
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._scan_now = asyncio.Event()
        self._last_scan_at: Optional[float] = None
        self._last_error: str = ""
        self._ingested_total = 0
        self._deleted_total = 0

    def status(self) -> KBWatchStatus:
        s = settings_store.get_settings()
        return KBWatchStatus(
            running=self._task is not None and not self._task.done(),
            roots=[str(x) for x in (s.kb_watch_roots or [])],
            exts=[str(x) for x in (s.kb_watch_exts or [])],
            interval_seconds=int(s.kb_watch_interval_seconds or 10),
            max_file_mb=int(s.kb_watch_max_file_mb or 20),
            last_scan_at=self._last_scan_at,
            last_error=self._last_error,
            ingested_total=self._ingested_total,
            deleted_total=self._deleted_total,
        )

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._scan_now.clear()
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        self._scan_now.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass
        self._task = None

    async def trigger_scan(self) -> None:
        self._scan_now.set()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            s = settings_store.get_settings()
            if bool(s.kb_watch_enable):
                try:
                    await self.scan_once()
                    self._last_error = ""
                except Exception as e:
                    self._last_error = str(e)
            else:
                # If disabled at runtime, clear last error but keep the task alive
                self._last_error = ""

            interval = max(2, int(getattr(s, "kb_watch_interval_seconds", 10) or 10))
            self._scan_now.clear()
            try:
                await asyncio.wait_for(self._scan_now.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def scan_once(self) -> Dict[str, Any]:
        s = settings_store.get_settings()
        if not bool(s.kb_watch_enable):
            return {"ok": False, "skipped": True, "reason": "disabled"}

        roots = [Path(r) for r in (s.kb_watch_roots or []) if str(r).strip()]
        exts = [str(e).strip().lower().lstrip(".") for e in (s.kb_watch_exts or []) if str(e).strip()]
        if not exts:
            exts = ["txt", "md"]
        max_bytes = int(s.kb_watch_max_file_mb or 20) * 1024 * 1024

        root_keys = []
        for r in roots:
            try:
                root_keys.append(_norm_path(r) + "/")
            except Exception:
                continue
        existing_rows = self.kb.list_source_files(roots=root_keys)
        existing_by_path: Dict[str, Dict[str, Any]] = {row["path"]: row for row in existing_rows}

        seen_paths: Set[str] = set()
        ingested = 0
        deleted = 0
        to_index_doc_ids: List[str] = []

        for root in roots:
            try:
                root.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            if not root.exists() or not root.is_dir():
                continue
            for fp in root.rglob("*"):
                if not fp.is_file():
                    continue
                if _is_hidden_path(fp):
                    continue
                ext = fp.suffix.lower().lstrip(".")
                if ext not in exts:
                    continue
                try:
                    st = fp.stat()
                except Exception:
                    continue
                if int(getattr(st, "st_size", 0) or 0) > max_bytes:
                    continue

                path_key = _norm_path(fp)
                seen_paths.add(path_key)
                prev = existing_by_path.get(path_key)
                mtime = float(getattr(st, "st_mtime", 0.0) or 0.0)
                size = int(getattr(st, "st_size", 0) or 0)

                # Fast path: unchanged
                if prev and float(prev.get("mtime", 0.0)) == mtime and int(prev.get("size", -1)) == size:
                    continue

                sha = ""
                try:
                    sha = _sha256_file(fp)
                except Exception:
                    continue
                if prev and prev.get("sha256") == sha:
                    # Update metadata only
                    self.kb.upsert_source_file(
                        path=path_key,
                        doc_id=str(prev.get("doc_id") or ""),
                        sha256=sha,
                        mtime=mtime,
                        size=size,
                        title=str(prev.get("title") or fp.name),
                        source=str(prev.get("source") or path_key),
                        categories=list(prev.get("categories") or []),
                        agent_ids=list(prev.get("agent_ids") or []),
                    )
                    continue

                doc_id = _stable_doc_id_for_path(path_key)
                title = fp.stem or fp.name
                source = path_key
                categories = _derive_categories(root, fp)
                text = _extract_text(fp)
                if not text.strip():
                    continue

                # Replace previous content deterministically.
                try:
                    self.kb.delete_document(doc_id)
                except Exception:
                    pass
                self.kb.add_document(
                    doc_id=doc_id,
                    title=title,
                    source=source,
                    text=text,
                    categories=categories,
                    agent_ids=[],
                )
                self.kb.upsert_source_file(
                    path=path_key,
                    doc_id=doc_id,
                    sha256=sha,
                    mtime=mtime,
                    size=size,
                    title=title,
                    source=source,
                    categories=categories,
                    agent_ids=[],
                )
                ingested += 1
                to_index_doc_ids.append(doc_id)

        # Handle deletions
        for path_key, row in existing_by_path.items():
            if path_key in seen_paths:
                continue
            # Only delete entries that were under currently-configured roots
            if root_keys and not any(path_key.startswith(rk.rstrip("/")) for rk in root_keys):
                continue
            try:
                self.kb.delete_document(str(row.get("doc_id") or ""))
            except Exception:
                pass
            try:
                self.kb.delete_source_file(path_key)
            except Exception:
                pass
            deleted += 1

        # Optional: index embeddings proactively (best-effort)
        if bool(s.kb_watch_index_embeddings) and to_index_doc_ids:
            model = (s.kb_embedding_model or "").strip()
            if model:
                try:
                    await self.kb_retriever.index_embeddings(
                        embedding_model_spec=model,
                        doc_ids=to_index_doc_ids,
                        pool=max(int(s.kb_semantic_pool or 2000) * 10, 5000),
                    )
                except Exception:
                    pass

        self._last_scan_at = time.time()
        self._ingested_total += ingested
        self._deleted_total += deleted

        return {"ok": True, "ingested": ingested, "deleted": deleted, "seen": len(seen_paths)}
