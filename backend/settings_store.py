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

    # Agent auto tool calls (opt-in): agents may request background tools via a tool block.
    enable_agent_auto_tools: bool = False

    # Knowledge base retrieval
    # fts | semantic | hybrid
    kb_retrieval_mode: str = "hybrid"
    kb_embedding_model: str = field(default_factory=lambda: config.KB_EMBEDDING_MODEL or "")
    kb_enable_rerank: bool = True
    kb_rerank_model: str = field(default_factory=lambda: config.KB_RERANK_MODEL or "")
    kb_semantic_pool: int = 400
    kb_initial_k: int = 24

    # Knowledge base continuous ingestion (watch folders + incremental import)
    kb_watch_enable: bool = field(default_factory=lambda: bool(config.KB_WATCH_ENABLE))
    kb_watch_roots: list[str] = field(default_factory=lambda: list(config.KB_WATCH_ROOTS or []))
    kb_watch_exts: list[str] = field(default_factory=lambda: list(config.KB_WATCH_EXTS or ["txt", "md"]))
    kb_watch_interval_seconds: int = field(default_factory=lambda: int(config.KB_WATCH_INTERVAL_SECONDS or 10))
    kb_watch_max_file_mb: int = field(default_factory=lambda: int(config.KB_WATCH_MAX_FILE_MB or 20))
    kb_watch_index_embeddings: bool = True

    # Council pipeline extensions
    enable_preprocess: bool = True
    enable_roundtable: bool = True
    enable_fact_check: bool = True
    roundtable_rounds: int = 1

    # Report generation + persistence
    enable_report_generation: bool = True
    report_instructions: str = (
        "请撰写一份完整分析报告（Markdown），至少包含：\n"
        "1) 背景与目标\n"
        "2) 关键材料摘要（如有上传文档/网页信息）\n"
        "3) 主要观点与分歧（引用专家名称）\n"
        "4) 事实核查结论（如有 claims JSON，按证据归因）\n"
        "5) 可执行结论与行动清单\n"
        "6) 风险与不确定性\n"
        "7) 附录：引用的 URL 与 KB[doc_id]\n"
    )
    auto_save_report_to_kb: bool = True
    auto_bind_report_to_conversation: bool = True
    report_kb_category: str = "council_reports"

    # Conversation history injection (for new agents / continuity)
    enable_history_context: bool = True
    history_max_messages: int = 12

    # Job runner (VCP-like long tasks)
    # Per-tool concurrency limits (job_type -> max concurrent runs)
    job_tool_limits: Dict[str, int] = field(
        default_factory=lambda: {
            "kg_extract": 1,
            "kb_index": 1,
            "office_ingest": 1,
            "web_search": 2,
            "evidence_pack": 2,
            "paper_search": 2,
        }
    )
    # Per-tool default timeout seconds (job_type -> seconds). Payload can override with timeout_seconds.
    job_default_timeouts: Dict[str, int] = field(
        default_factory=lambda: {
            "kg_extract": 60 * 30,
            "kb_index": 60 * 20,
            "office_ingest": 60 * 10,
            "web_search": 60 * 5,
            "evidence_pack": 60 * 8,
            "paper_search": 60 * 5,
        }
    )
    # Per-tool "successful result reuse" TTL (seconds). If >0 and an idempotent job succeeded recently,
    # new create requests will reuse the existing result instead of re-running.
    job_result_ttls: Dict[str, int] = field(
        default_factory=lambda: {
            "web_search": 300,
            "evidence_pack": 600,
            "kb_index": 0,
            "kg_extract": 0,
            "office_ingest": 0,
            "paper_search": 300,
        }
    )

    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def _ensure_dir():
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    # Be tolerant of UTF-8 BOM (common when edited by some Windows tools).
    with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
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
        enable_agent_auto_tools=bool(data.get("enable_agent_auto_tools", False)),
        kb_retrieval_mode=str(data.get("kb_retrieval_mode", "hybrid") or "hybrid").lower(),
        kb_embedding_model=str(data.get("kb_embedding_model", "") or ""),
        kb_enable_rerank=bool(data.get("kb_enable_rerank", True)),
        kb_rerank_model=str(data.get("kb_rerank_model", "") or ""),
        kb_semantic_pool=int(data.get("kb_semantic_pool", 400)),
        kb_initial_k=int(data.get("kb_initial_k", 24)),
        kb_watch_enable=bool(data.get("kb_watch_enable", bool(config.KB_WATCH_ENABLE))),
        kb_watch_roots=list(data.get("kb_watch_roots", list(config.KB_WATCH_ROOTS or [])) or []),
        kb_watch_exts=list(data.get("kb_watch_exts", list(config.KB_WATCH_EXTS or ["txt", "md"])) or []),
        kb_watch_interval_seconds=max(2, int(data.get("kb_watch_interval_seconds", int(config.KB_WATCH_INTERVAL_SECONDS or 10)))),
        kb_watch_max_file_mb=max(1, int(data.get("kb_watch_max_file_mb", int(config.KB_WATCH_MAX_FILE_MB or 20)))),
        kb_watch_index_embeddings=bool(data.get("kb_watch_index_embeddings", True)),
        enable_preprocess=bool(data.get("enable_preprocess", True)),
        enable_roundtable=bool(data.get("enable_roundtable", True)),
        enable_fact_check=bool(data.get("enable_fact_check", True)),
        roundtable_rounds=max(0, min(3, int(data.get("roundtable_rounds", 1)))),
        enable_report_generation=bool(data.get("enable_report_generation", True)),
        report_instructions=str(data.get("report_instructions", Settings().report_instructions) or Settings().report_instructions),
        auto_save_report_to_kb=bool(data.get("auto_save_report_to_kb", True)),
        auto_bind_report_to_conversation=bool(data.get("auto_bind_report_to_conversation", True)),
        report_kb_category=str(data.get("report_kb_category", "council_reports") or "council_reports"),
        enable_history_context=bool(data.get("enable_history_context", True)),
        history_max_messages=max(0, min(50, int(data.get("history_max_messages", 12)))),
        job_tool_limits=dict(data.get("job_tool_limits", Settings().job_tool_limits) or Settings().job_tool_limits),
        job_default_timeouts=dict(
            data.get("job_default_timeouts", Settings().job_default_timeouts) or Settings().job_default_timeouts
        ),
        job_result_ttls=dict(data.get("job_result_ttls", Settings().job_result_ttls) or Settings().job_result_ttls),
        updated_at=data.get("updated_at") or datetime.utcnow().isoformat(),
    )
    # Env defaults (allow settings.json to omit/leave empty for these).
    if not s.kb_embedding_model and config.KB_EMBEDDING_MODEL:
        s.kb_embedding_model = config.KB_EMBEDDING_MODEL
    if not s.kb_rerank_model and config.KB_RERANK_MODEL:
        s.kb_rerank_model = config.KB_RERANK_MODEL
    if not s.kb_watch_roots and config.KB_WATCH_ROOTS:
        s.kb_watch_roots = list(config.KB_WATCH_ROOTS)
    if not s.kb_watch_exts and config.KB_WATCH_EXTS:
        s.kb_watch_exts = list(config.KB_WATCH_EXTS)
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

    if "enable_agent_auto_tools" in patch:
        s.enable_agent_auto_tools = bool(patch["enable_agent_auto_tools"])

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

    if "kb_watch_enable" in patch:
        s.kb_watch_enable = bool(patch["kb_watch_enable"])

    if "kb_watch_roots" in patch:
        roots = patch.get("kb_watch_roots") or []
        if isinstance(roots, str):
            roots = [r.strip() for r in roots.replace(";", ",").split(",") if r.strip()]
        if isinstance(roots, list):
            s.kb_watch_roots = [str(r).strip() for r in roots if str(r).strip()]

    if "kb_watch_exts" in patch:
        exts = patch.get("kb_watch_exts") or []
        if isinstance(exts, str):
            exts = [e.strip() for e in exts.split(",") if e.strip()]
        if isinstance(exts, list):
            cleaned: list[str] = []
            seen = set()
            for e in exts:
                val = str(e).strip().lower().lstrip(".")
                if not val or val in seen:
                    continue
                seen.add(val)
                cleaned.append(val)
            s.kb_watch_exts = cleaned

    if "kb_watch_interval_seconds" in patch:
        s.kb_watch_interval_seconds = max(2, min(3600, int(patch["kb_watch_interval_seconds"])))

    if "kb_watch_max_file_mb" in patch:
        s.kb_watch_max_file_mb = max(1, min(500, int(patch["kb_watch_max_file_mb"])))

    if "kb_watch_index_embeddings" in patch:
        s.kb_watch_index_embeddings = bool(patch["kb_watch_index_embeddings"])

    if "enable_preprocess" in patch:
        s.enable_preprocess = bool(patch["enable_preprocess"])

    if "enable_roundtable" in patch:
        s.enable_roundtable = bool(patch["enable_roundtable"])

    if "enable_fact_check" in patch:
        s.enable_fact_check = bool(patch["enable_fact_check"])

    if "roundtable_rounds" in patch:
        s.roundtable_rounds = max(0, min(3, int(patch["roundtable_rounds"])))

    if "enable_report_generation" in patch:
        s.enable_report_generation = bool(patch["enable_report_generation"])

    if "report_instructions" in patch:
        s.report_instructions = str(patch["report_instructions"] or "").strip()

    if "auto_save_report_to_kb" in patch:
        s.auto_save_report_to_kb = bool(patch["auto_save_report_to_kb"])

    if "auto_bind_report_to_conversation" in patch:
        s.auto_bind_report_to_conversation = bool(patch["auto_bind_report_to_conversation"])

    if "report_kb_category" in patch:
        s.report_kb_category = str(patch["report_kb_category"] or "").strip() or "council_reports"

    if "enable_history_context" in patch:
        s.enable_history_context = bool(patch["enable_history_context"])

    if "history_max_messages" in patch:
        s.history_max_messages = max(0, min(50, int(patch["history_max_messages"])))

    if "job_tool_limits" in patch:
        val = patch.get("job_tool_limits") or {}
        if isinstance(val, dict):
            cleaned: Dict[str, int] = {}
            for k, v in val.items():
                key = str(k or "").strip()
                if not key:
                    continue
                try:
                    cleaned[key] = max(1, min(32, int(v)))
                except Exception:
                    continue
            if cleaned:
                s.job_tool_limits = cleaned

    if "job_default_timeouts" in patch:
        val = patch.get("job_default_timeouts") or {}
        if isinstance(val, dict):
            cleaned: Dict[str, int] = {}
            for k, v in val.items():
                key = str(k or "").strip()
                if not key:
                    continue
                try:
                    cleaned[key] = max(1, min(24 * 60 * 60, int(v)))
                except Exception:
                    continue
            if cleaned:
                s.job_default_timeouts = cleaned

    if "job_result_ttls" in patch:
        val = patch.get("job_result_ttls") or {}
        if isinstance(val, dict):
            cleaned: Dict[str, int] = {}
            for k, v in val.items():
                key = str(k or "").strip()
                if not key:
                    continue
                try:
                    cleaned[key] = max(0, min(24 * 60 * 60, int(v)))
                except Exception:
                    continue
            if cleaned:
                s.job_result_ttls = cleaned

    s.updated_at = datetime.utcnow().isoformat()
    # Fill defaults from env if not set explicitly
    if not s.kb_embedding_model and config.KB_EMBEDDING_MODEL:
        s.kb_embedding_model = config.KB_EMBEDDING_MODEL
    if not s.kb_rerank_model and config.KB_RERANK_MODEL:
        s.kb_rerank_model = config.KB_RERANK_MODEL
    if not s.kb_watch_roots and config.KB_WATCH_ROOTS:
        s.kb_watch_roots = list(config.KB_WATCH_ROOTS)
    if not s.kb_watch_exts and config.KB_WATCH_EXTS:
        s.kb_watch_exts = list(config.KB_WATCH_EXTS)
    _save_raw(asdict(s))
    return s
