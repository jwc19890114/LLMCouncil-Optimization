from __future__ import annotations

from .registry import Tool, ToolRegistry
from . import kb_index as kb_index_tool
from . import kg_extract as kg_extract_tool
from . import web_search as web_search_tool
from . import evidence_pack as evidence_pack_tool
from . import office_ingest as office_ingest_tool


def register_builtin_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(name="kb_index", run=kb_index_tool.run))
    reg.register(Tool(name="kg_extract", run=kg_extract_tool.run))
    reg.register(Tool(name="web_search", run=web_search_tool.run))
    reg.register(Tool(name="evidence_pack", run=evidence_pack_tool.run))
    reg.register(Tool(name="office_ingest", run=office_ingest_tool.run))
    return reg
