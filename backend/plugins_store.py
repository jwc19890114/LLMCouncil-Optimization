"""Persistent plugin/tool settings (enabled + config).

For personal/local use, this is intentionally simple and file-based.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PROJECT_ROOT
from .file_utils import atomic_write_json


PLUGINS_FILE = PROJECT_ROOT / "data" / "plugins.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class PluginState:
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginsSettings:
    plugins: Dict[str, PluginState] = field(default_factory=dict)
    updated_at: str = field(default_factory=_now_iso)


def _load_raw() -> Dict[str, Any]:
    if not PLUGINS_FILE.exists():
        return {}
    try:
        with open(PLUGINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(settings: PluginsSettings) -> None:
    atomic_write_json(PLUGINS_FILE, asdict(settings), ensure_ascii=False, indent=2)


def get_plugins_settings() -> PluginsSettings:
    raw = _load_raw()
    plugins_raw = raw.get("plugins") if isinstance(raw, dict) else {}
    plugins: Dict[str, PluginState] = {}
    if isinstance(plugins_raw, dict):
        for name, v in plugins_raw.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(v, dict):
                continue
            plugins[name] = PluginState(enabled=bool(v.get("enabled", True)), config=v.get("config") or {})
    return PluginsSettings(plugins=plugins, updated_at=str(raw.get("updated_at") or _now_iso()))


def get_plugin_state(name: str) -> PluginState:
    name = (name or "").strip()
    s = get_plugins_settings()
    return s.plugins.get(name) or PluginState()


def patch_plugin_state(
    name: str,
    *,
    enabled: Optional[bool] = None,
    config: Optional[Dict[str, Any]] = None,
) -> PluginState:
    name = (name or "").strip()
    if not name:
        raise ValueError("plugin name is empty")
    s = get_plugins_settings()
    cur = s.plugins.get(name) or PluginState()
    if enabled is not None:
        cur.enabled = bool(enabled)
    if config is not None and isinstance(config, dict):
        cur.config = config
    s.plugins[name] = cur
    s.updated_at = _now_iso()
    _save(s)
    return cur

