"""Tool registry (plugin-friendly, VCP-inspired)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from ..jobs_store import Job
from ..tool_context import ToolContext


ProgressUpdater = Callable[[float], None]
ToolRun = Callable[[Job, ToolContext, ProgressUpdater], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    run: ToolRun


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list(self) -> list[str]:
        return sorted(self._tools.keys())

