"""JSON-based storage for projects (conversation grouping + shared KB scope)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PROJECT_ROOT
from .file_utils import atomic_write_json


PROJECTS_PATH = Path(PROJECT_ROOT) / "data" / "projects.json"


def _ensure_dir() -> None:
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_all() -> List[Dict[str, Any]]:
    _ensure_dir()
    if not PROJECTS_PATH.exists():
        return []
    try:
        with open(PROJECTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict)]
    except Exception:
        return []
    return []


def _save_all(projects: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    atomic_write_json(PROJECTS_PATH, projects, ensure_ascii=False, indent=2)


def _normalize_project(p: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(p or {})
    out["id"] = str(out.get("id") or "").strip() or uuid.uuid4().hex
    out["created_at"] = str(out.get("created_at") or "").strip() or datetime.utcnow().isoformat()
    out["name"] = str(out.get("name") or "").strip() or "Untitled Project"
    out["description"] = str(out.get("description") or "").strip()
    kb_doc_ids = out.get("kb_doc_ids")
    if not isinstance(kb_doc_ids, list):
        kb_doc_ids = []
    cleaned = []
    seen = set()
    for d in kb_doc_ids:
        if not isinstance(d, str):
            continue
        s = d.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    out["kb_doc_ids"] = cleaned
    return out


def list_projects() -> List[Dict[str, Any]]:
    projects = [_normalize_project(p) for p in _load_all()]
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    pid = str(project_id or "").strip()
    if not pid:
        return None
    for p in _load_all():
        if str(p.get("id") or "").strip() == pid:
            return _normalize_project(p)
    return None


def create_project(*, name: str, description: str = "") -> Dict[str, Any]:
    projects = _load_all()
    project = _normalize_project(
        {
            "id": uuid.uuid4().hex,
            "created_at": datetime.utcnow().isoformat(),
            "name": str(name or "").strip() or "Untitled Project",
            "description": str(description or "").strip(),
            "kb_doc_ids": [],
        }
    )
    projects.append(project)
    _save_all(projects)
    return project


def update_project(project_id: str, *, name: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("project_id required")
    projects = _load_all()
    for idx, raw in enumerate(projects):
        if str(raw.get("id") or "").strip() != pid:
            continue
        p = _normalize_project(raw)
        if name is not None:
            p["name"] = str(name or "").strip() or p.get("name") or "Untitled Project"
        if description is not None:
            p["description"] = str(description or "").strip()
        projects[idx] = p
        _save_all(projects)
        return p
    raise KeyError("Project not found")


def delete_project(project_id: str) -> bool:
    pid = str(project_id or "").strip()
    if not pid:
        return False
    projects = _load_all()
    new_projects = [p for p in projects if str(p.get("id") or "").strip() != pid]
    if len(new_projects) == len(projects):
        return False
    _save_all(new_projects)
    return True


def add_project_kb_doc_ids(project_id: str, doc_ids: List[str]) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("project_id required")
    ids = [str(d).strip() for d in (doc_ids or []) if isinstance(d, str) and str(d).strip()]
    if not ids:
        p = get_project(pid)
        if p is None:
            raise KeyError("Project not found")
        return p

    projects = _load_all()
    for idx, raw in enumerate(projects):
        if str(raw.get("id") or "").strip() != pid:
            continue
        p = _normalize_project(raw)
        existing = p.get("kb_doc_ids") or []
        merged = list(existing) + list(ids)
        p["kb_doc_ids"] = _normalize_project({"kb_doc_ids": merged}).get("kb_doc_ids", [])
        projects[idx] = p
        _save_all(projects)
        return p
    raise KeyError("Project not found")


def add_project_kb_doc_id(project_id: str, doc_id: str) -> Dict[str, Any]:
    return add_project_kb_doc_ids(project_id, [doc_id])

