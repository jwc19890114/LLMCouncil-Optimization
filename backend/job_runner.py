"""Async job runner for long tasks.

This keeps the API responsive and persists results for later "refill" into prompts.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from .jobs_store import JobsStore, Job
from .tool_context import ToolContext
from .tools.registry import ToolRegistry


JobHandler = Callable[[Job], Awaitable[None]]


@dataclass
class JobRunnerStatus:
    running: bool
    queue_size: int
    workers: int


class JobRunner:
    def __init__(self, store: JobsStore, *, workers: int = 1, tools: ToolRegistry | None = None, ctx: ToolContext | None = None):
        self.store = store
        self.workers = max(1, min(8, int(workers)))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._handlers: Dict[str, JobHandler] = {}
        self._tools = tools
        self._ctx = ctx
        self._stop = asyncio.Event()

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[str(job_type)] = handler

    def set_tools(self, tools: ToolRegistry, ctx: ToolContext) -> None:
        self._tools = tools
        self._ctx = ctx

    def status(self) -> JobRunnerStatus:
        return JobRunnerStatus(
            running=bool(self._tasks) and any(not t.done() for t in self._tasks),
            queue_size=self._queue.qsize(),
            workers=self.workers,
        )

    async def start(self) -> None:
        if self._tasks and any(not t.done() for t in self._tasks):
            return
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._worker_loop(i)) for i in range(self.workers)]

    async def stop(self) -> None:
        self._stop.set()
        # Unblock workers
        for _ in range(len(self._tasks) + 1):
            self._queue.put_nowait("")
        for t in self._tasks:
            try:
                await t
            except Exception:
                pass
        self._tasks = []

    def enqueue(self, job_id: str) -> None:
        self._queue.put_nowait(job_id)

    def create_and_enqueue(
        self,
        *,
        job_type: str,
        payload: Dict[str, Any],
        conversation_id: str = "",
    ) -> Job:
        job_id = uuid.uuid4().hex
        self.store.create_job(job_id=job_id, job_type=job_type, conversation_id=conversation_id, payload=payload)
        self.enqueue(job_id)
        return self.store.get_job(job_id)  # type: ignore[return-value]

    async def _worker_loop(self, worker_idx: int) -> None:
        while not self._stop.is_set():
            job_id = await self._queue.get()
            if not job_id:
                continue
            job = self.store.get_job(job_id)
            if not job:
                continue
            if job.status == "canceled":
                continue

            tool = self._tools.get(job.job_type) if self._tools else None
            handler = self._handlers.get(job.job_type)
            if not tool and not handler:
                self.store.update_job(job.id, status="failed", error=f"Unknown job type: {job.job_type}")
                continue

            # Execute
            self.store.update_job(job.id, status="running", progress=0.01, error="")
            try:
                if tool:
                    if not self._ctx:
                        raise RuntimeError("ToolContext is not configured for JobRunner")

                    def update_progress(p: float) -> None:
                        try:
                            self.store.update_job(job.id, progress=max(0.0, min(1.0, float(p))))
                        except Exception:
                            pass

                    result = await tool.run(job, self._ctx, update_progress)
                    if isinstance(result, dict) and result.get("ok") is False:
                        self.store.update_job(job.id, status="failed", error=str(result.get("error") or "tool failed"), progress=1.0, result=result)
                    else:
                        self.store.update_job(job.id, status="succeeded", progress=1.0, result=result or {})
                else:
                    await handler(job)
                    # Handler is responsible for final status/result; enforce success if missing.
                    done = self.store.get_job(job.id)
                    if done and done.status == "running":
                        self.store.update_job(job.id, status="succeeded", progress=1.0)
            except Exception as e:
                self.store.update_job(job.id, status="failed", error=str(e), progress=1.0)
