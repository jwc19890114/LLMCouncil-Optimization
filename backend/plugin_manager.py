"""Tool/plugin manager (VCP-inspired, local friendly).

Current scope:
- Manage built-in tools as "plugins"
- Persist enabled/disabled + config
- Rebuild ToolRegistry used by JobRunner

Future extension:
- Load external plugins from a folder with manifests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .plugins_store import get_plugins_settings, patch_plugin_state
from .tools.registry import ToolRegistry
from .tools.builtins import register_builtin_tools


@dataclass(frozen=True)
class PluginInfo:
    name: str
    title: str
    description: str
    enabled: bool
    config: Dict[str, Any]
    locked: bool = False


BUILTIN_META: Dict[str, Dict[str, str]] = {
    "kb_index": {"title": "KB 索引", "description": "为知识库分块预先生成 embedding，加速语义检索。"},
    "kg_extract": {"title": "图谱抽取", "description": "从文本抽取实体/关系并写入 Neo4j 图谱。"},
    "web_search": {"title": "网页检索", "description": "基于 DDG 的网页检索，返回标题/URL/摘要。"},
    "evidence_pack": {"title": "证据整理", "description": "网页检索 + 本会话绑定 KB（FTS）证据打包，便于后续引用。"},
    "office_ingest": {"title": "Office 导入", "description": "读取 .docx/.xlsx 文档，提取为纯文本并写入知识库（可选索引 embedding）。"},
}


class PluginManager:
    def __init__(self):
        self._registry: ToolRegistry = ToolRegistry()
        self.reload()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def list_plugins(self) -> List[PluginInfo]:
        s = get_plugins_settings()
        out: List[PluginInfo] = []
        for name in sorted(BUILTIN_META.keys()):
            state = s.plugins.get(name)
            enabled = True if state is None else bool(state.enabled)
            config = {} if state is None else (state.config or {})
            meta = BUILTIN_META.get(name) or {}
            out.append(
                PluginInfo(
                    name=name,
                    title=meta.get("title") or name,
                    description=meta.get("description") or "",
                    enabled=enabled,
                    config=config,
                    locked=False,
                )
            )
        return out

    def set_enabled(self, name: str, enabled: bool) -> PluginInfo:
        patch_plugin_state(name, enabled=enabled)
        self.reload()
        return next((p for p in self.list_plugins() if p.name == name), None)  # type: ignore[return-value]

    def set_config(self, name: str, config: Dict[str, Any]) -> PluginInfo:
        patch_plugin_state(name, config=config)
        self.reload()
        return next((p for p in self.list_plugins() if p.name == name), None)  # type: ignore[return-value]

    def reload(self) -> ToolRegistry:
        s = get_plugins_settings()
        reg = ToolRegistry()
        register_builtin_tools(reg)

        # Filter disabled built-ins by rebuilding a fresh registry that only keeps enabled.
        enabled: set[str] = set()
        for name in BUILTIN_META.keys():
            st = s.plugins.get(name)
            if st is None or bool(st.enabled):
                enabled.add(name)
        filtered = ToolRegistry()
        for name in reg.list():
            if name in BUILTIN_META and name not in enabled:
                continue
            tool = reg.get(name)
            if tool:
                filtered.register(tool)

        self._registry = filtered
        return self._registry
