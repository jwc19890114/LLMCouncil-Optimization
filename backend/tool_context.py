"""Dependency container passed to tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .kb_retrieval import KBHybridRetriever
from .neo4j_store import Neo4jKGStore


@dataclass(frozen=True)
class ToolContext:
    kb_retriever: KBHybridRetriever
    get_neo4j: Callable[[], Neo4jKGStore]
    is_job_cancelled: Callable[[str], bool] = lambda _job_id: False
    check_job_cancelled: Callable[[str], None] = lambda _job_id: None
