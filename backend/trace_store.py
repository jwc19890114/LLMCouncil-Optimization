"""Conversation trace storage (JSONL)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import PROJECT_ROOT


TRACE_DIR = PROJECT_ROOT / "data" / "traces"


def _trace_path(conversation_id: str) -> Path:
    return TRACE_DIR / f"{conversation_id}.jsonl"


def append(conversation_id: str, event: Dict[str, Any]):
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.utcnow().isoformat(),
        "conversation_id": conversation_id,
        **event,
    }
    with open(_trace_path(conversation_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_events(conversation_id: str, limit: int = 5000) -> List[Dict[str, Any]]:
    path = _trace_path(conversation_id)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    if limit and len(events) > limit:
        return events[-limit:]
    return events


def stream_lines(conversation_id: str) -> Iterable[str]:
    path = _trace_path(conversation_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            yield line


def delete(conversation_id: str) -> bool:
    path = _trace_path(conversation_id)
    if not path.exists():
        return False
    path.unlink()
    return True

