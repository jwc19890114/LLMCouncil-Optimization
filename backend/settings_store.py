"""Simple persistent settings store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .config import PROJECT_ROOT
from . import config
from .file_utils import atomic_write_json


SETTINGS_FILE = PROJECT_ROOT / "data" / "settings.json"


@dataclass
class Settings:
    # Default: enforce Chinese output.
    output_language: str = "zh"

    # Real-world context
    enable_date_context: bool = True
    enable_web_search: bool = True
    web_search_results: int = 5

    # Agent-specific web search (per agent, best-effort; can be slower)
    enable_agent_web_search: bool = False
    agent_web_search_results: int = 3

    # Knowledge base retrieval
    # fts | semantic | hybrid
    kb_retrieval_mode: str = "hybrid"
    kb_embedding_model: str = field(default_factory=lambda: config.KB_EMBEDDING_MODEL or "")
    kb_enable_rerank: bool = True
    kb_rerank_model: str = field(default_factory=lambda: config.KB_RERANK_MODEL or "")
    kb_semantic_pool: int = 2000
    kb_initial_k: int = 24

    # Council pipeline extensions
    enable_preprocess: bool = True
    enable_roundtable: bool = True
    enable_fact_check: bool = True
    roundtable_rounds: int = 1

    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def _ensure_dir():
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: Dict[str, Any]):
    _ensure_dir()
    atomic_write_json(SETTINGS_FILE, data, ensure_ascii=False, indent=2)


def get_settings() -> Settings:
    data = _load_raw()
    if not data:
        s = Settings()
        _save_raw(asdict(s))
        return s
    s = Settings(
        output_language=data.get("output_language", "zh"),
        enable_date_context=bool(data.get("enable_date_context", True)),
        enable_web_search=bool(data.get("enable_web_search", True)),
        web_search_results=int(data.get("web_search_results", 5)),
        enable_agent_web_search=bool(data.get("enable_agent_web_search", False)),
        agent_web_search_results=max(0, min(10, int(data.get("agent_web_search_results", 3)))),
        kb_retrieval_mode=str(data.get("kb_retrieval_mode", "hybrid") or "hybrid").lower(),
        kb_embedding_model=str(data.get("kb_embedding_model", "") or ""),
        kb_enable_rerank=bool(data.get("kb_enable_rerank", True)),
        kb_rerank_model=str(data.get("kb_rerank_model", "") or ""),
        kb_semantic_pool=int(data.get("kb_semantic_pool", 2000)),
        kb_initial_k=int(data.get("kb_initial_k", 24)),
        enable_preprocess=bool(data.get("enable_preprocess", True)),
        enable_roundtable=bool(data.get("enable_roundtable", True)),
        enable_fact_check=bool(data.get("enable_fact_check", True)),
        roundtable_rounds=max(0, min(3, int(data.get("roundtable_rounds", 1)))),
        updated_at=data.get("updated_at") or datetime.utcnow().isoformat(),
    )
    # Env defaults (allow settings.json to omit/leave empty for these).
    if not s.kb_embedding_model and config.KB_EMBEDDING_MODEL:
        s.kb_embedding_model = config.KB_EMBEDDING_MODEL
    if not s.kb_rerank_model and config.KB_RERANK_MODEL:
        s.kb_rerank_model = config.KB_RERANK_MODEL
    return s


def update_settings(patch: Dict[str, Any]) -> Settings:
    s = get_settings()
    if "output_language" in patch:
        val = str(patch["output_language"]).strip().lower()
        if val in ("zh", "zh-cn", "cn", "chinese"):
            s.output_language = "zh"
        elif val in ("en", "english"):
            s.output_language = "en"
    if "enable_date_context" in patch:
        s.enable_date_context = bool(patch["enable_date_context"])
    if "enable_web_search" in patch:
        s.enable_web_search = bool(patch["enable_web_search"])
    if "web_search_results" in patch:
        s.web_search_results = max(0, min(20, int(patch["web_search_results"])))

    if "enable_agent_web_search" in patch:
        s.enable_agent_web_search = bool(patch["enable_agent_web_search"])

    if "agent_web_search_results" in patch:
        s.agent_web_search_results = max(0, min(10, int(patch["agent_web_search_results"])))

    if "kb_retrieval_mode" in patch:
        val = str(patch["kb_retrieval_mode"] or "").strip().lower()
        if val in ("fts", "semantic", "hybrid"):
            s.kb_retrieval_mode = val

    if "kb_embedding_model" in patch:
        s.kb_embedding_model = str(patch["kb_embedding_model"] or "").strip()

    if "kb_enable_rerank" in patch:
        s.kb_enable_rerank = bool(patch["kb_enable_rerank"])

    if "kb_rerank_model" in patch:
        s.kb_rerank_model = str(patch["kb_rerank_model"] or "").strip()

    if "kb_semantic_pool" in patch:
        s.kb_semantic_pool = max(0, min(10000, int(patch["kb_semantic_pool"])))

    if "kb_initial_k" in patch:
        s.kb_initial_k = max(1, min(200, int(patch["kb_initial_k"])))

    if "enable_preprocess" in patch:
        s.enable_preprocess = bool(patch["enable_preprocess"])

    if "enable_roundtable" in patch:
        s.enable_roundtable = bool(patch["enable_roundtable"])

    if "enable_fact_check" in patch:
        s.enable_fact_check = bool(patch["enable_fact_check"])

    if "roundtable_rounds" in patch:
        s.roundtable_rounds = max(0, min(3, int(patch["roundtable_rounds"])))

    s.updated_at = datetime.utcnow().isoformat()
    # Fill defaults from env if not set explicitly
    if not s.kb_embedding_model and config.KB_EMBEDDING_MODEL:
        s.kb_embedding_model = config.KB_EMBEDDING_MODEL
    if not s.kb_rerank_model and config.KB_RERANK_MODEL:
        s.kb_rerank_model = config.KB_RERANK_MODEL
    _save_raw(asdict(s))
    return s
