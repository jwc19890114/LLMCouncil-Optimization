"""Async job runner for long tasks.

This keeps the API responsive and persists results for later "refill" into prompts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime
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


class JobCancelled(Exception):
    pass


class JobRunner:
    def __init__(self, store: JobsStore, *, workers: int = 1, tools: ToolRegistry | None = None, ctx: ToolContext | None = None):
        self.store = store
        self.workers = max(1, min(8, int(workers)))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._enqueued: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self._handlers: Dict[str, JobHandler] = {}
        self._tools = tools
        self._ctx = ctx
        self._stop = asyncio.Event()
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._tool_limits: Dict[str, asyncio.Semaphore] = {}
        self._tool_limit_values: Dict[str, int] = {
            "kg_extract": 1,
            "kb_index": 1,
            "office_ingest": 1,
            "web_search": 2,
            "evidence_pack": 2,
            "paper_search": 2,
        }
        self._default_timeouts: Dict[str, int] = {
            "kg_extract": 60 * 30,
            "kb_index": 60 * 20,
            "office_ingest": 60 * 10,
            "web_search": 60 * 5,
            "evidence_pack": 60 * 8,
            "paper_search": 60 * 5,
        }
        self._result_ttls: Dict[str, int] = {
            "web_search": 300,
            "evidence_pack": 600,
            "kb_index": 0,
            "kg_extract": 0,
            "office_ingest": 0,
            "paper_search": 600,
        }

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
        # Crash recovery: requeue unfinished jobs and load persisted queue.
        try:
            self.store.requeue_running_jobs()
            for jid in self.store.list_queued_job_ids(limit=2000):
                self.enqueue(jid)
        except Exception:
            pass
        self._tasks = [asyncio.create_task(self._worker_loop(i)) for i in range(self.workers)]

    async def stop(self) -> None:
        self._stop.set()
        # Unblock workers
        for _ in range(len(self._tasks) + 1):
            self._queue.put_nowait("")
        # Cancel running tasks (best-effort).
        for t in list(self._running_tasks.values()):
            try:
                t.cancel()
            except Exception:
                pass
        for t in self._tasks:
            try:
                await t
            except Exception:
                pass
        self._tasks = []
        self._running_tasks = {}
        self._cancel_events = {}
        self._enqueued = set()

    def enqueue(self, job_id: str) -> None:
        job_id = str(job_id or "").strip()
        if not job_id:
            return
        if job_id in self._enqueued:
            return
        self._enqueued.add(job_id)
        self._queue.put_nowait(job_id)

    def is_job_cancelled(self, job_id: str) -> bool:
        job_id = str(job_id or "").strip()
        if not job_id:
            return False
        ev = self._cancel_events.get(job_id)
        if ev and ev.is_set():
            return True
        try:
            job = self.store.get_job(job_id)
            return bool(job and job.status == "canceled")
        except Exception:
            return False

    def check_job_cancelled(self, job_id: str) -> None:
        if self.is_job_cancelled(job_id):
            raise JobCancelled(f"Job {job_id} canceled")

    def cancel(self, job_id: str) -> bool:
        job_id = str(job_id or "").strip()
        if not job_id:
            return False
        ok = self.store.cancel_job(job_id)
        ev = self._cancel_events.get(job_id)
        if ev:
            try:
                ev.set()
            except Exception:
                pass
        t = self._running_tasks.get(job_id)
        if t and not t.done():
            try:
                t.cancel()
            except Exception:
                pass
        return ok

    def create_and_enqueue(
        self,
        *,
        job_type: str,
        payload: Dict[str, Any],
        conversation_id: str = "",
        idempotency_key: str = "",
        max_attempts: int = 0,
        reuse_ttl_seconds: Optional[int] = None,
        force_new: bool = False,
    ) -> Job:
        idempotency_key = (idempotency_key or "").strip()
        force_new = bool(force_new)
        if not idempotency_key:
            # Best-effort default: stable hash of payload to avoid accidental duplicates.
            try:
                payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                idempotency_key = hashlib.sha1(f"{job_type}:{conversation_id}:{payload_json}".encode("utf-8")).hexdigest()
            except Exception:
                idempotency_key = ""

        ttl = int(self._result_ttls.get(job_type, 0))
        if reuse_ttl_seconds is not None:
            try:
                ttl = max(0, int(reuse_ttl_seconds))
            except Exception:
                ttl = ttl

        if idempotency_key and not force_new:
            existing = self.store.get_by_idempotency(job_type=job_type, idempotency_key=idempotency_key)
            if existing:
                if existing.status in ("queued", "running"):
                    return existing
                if existing.status == "succeeded" and ttl > 0:
                    try:
                        updated_at = datetime.fromisoformat(str(existing.updated_at))
                        age = (datetime.utcnow() - updated_at).total_seconds()
                        if age >= 0 and age <= ttl:
                            return existing
                    except Exception:
                        # If parsing fails, be conservative and reuse.
                        return existing
        job_id = uuid.uuid4().hex
        job = self.store.create_job(
            job_id=job_id,
            job_type=job_type,
            conversation_id=conversation_id,
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )
        self.enqueue(job.id)
        return job

    def _get_tool_semaphore(self, job_type: str) -> asyncio.Semaphore:
        """
        Per-tool concurrency limit (VCP-like throttling). Default 1 for expensive tools.
        """
        job_type = str(job_type or "").strip()
        sem = self._tool_limits.get(job_type)
        if sem:
            return sem
        limit = max(1, int(self._tool_limit_values.get(job_type, self.workers)))
        sem = asyncio.Semaphore(limit)
        self._tool_limits[job_type] = sem
        return sem

    def configure(self, *, tool_limits: Dict[str, int] | None = None, default_timeouts: Dict[str, int] | None = None) -> None:
        """
        Update runtime limits/timeouts (best-effort). Safe to call multiple times.
        """
        if tool_limits is not None:
            cleaned: Dict[str, int] = {}
            for k, v in (tool_limits or {}).items():
                key = str(k or "").strip()
                if not key:
                    continue
                try:
                    cleaned[key] = max(1, min(32, int(v)))
                except Exception:
                    continue
            if cleaned:
                self._tool_limit_values = cleaned
                # Rebuild semaphores so changes take effect for future tasks.
                self._tool_limits = {}

        if default_timeouts is not None:
            cleaned: Dict[str, int] = {}
            for k, v in (default_timeouts or {}).items():
                key = str(k or "").strip()
                if not key:
                    continue
                try:
                    cleaned[key] = max(1, min(24 * 60 * 60, int(v)))
                except Exception:
                    continue
            if cleaned:
                self._default_timeouts = cleaned

    def configure_result_ttls(self, *, result_ttls: Dict[str, int] | None = None) -> None:
        if result_ttls is None:
            return
        cleaned: Dict[str, int] = {}
        for k, v in (result_ttls or {}).items():
            key = str(k or "").strip()
            if not key:
                continue
            try:
                cleaned[key] = max(0, min(24 * 60 * 60, int(v)))
            except Exception:
                continue
        if cleaned:
            self._result_ttls = cleaned

    def _should_retry(self, job: Job) -> bool:
        return bool(job.max_attempts and job.attempts < job.max_attempts and job.status != "canceled")

    def _schedule_retry(self, job: Job, *, error: str) -> None:
        # Exponential backoff with cap (seconds): 2,4,8,... up to 30 min.
        next_attempt = int(job.attempts or 0) + 1
        delay = min(30 * 60, 2 ** min(15, next_attempt))
        run_after = time.time() + float(delay)
        self.store.update_job(
            job.id,
            status="queued",
            progress=0.0,
            result={},
            error=str(error or ""),
            attempts=next_attempt,
            run_after_ts=run_after,
        )
        self.enqueue(job.id)

    async def _worker_loop(self, worker_idx: int) -> None:
        while not self._stop.is_set():
            job_id = await self._queue.get()
            if not job_id:
                continue
            self._enqueued.discard(job_id)
            job = self.store.get_job(job_id)
            if not job:
                continue
            if job.status == "canceled":
                continue
            if job.status != "queued":
                continue
            if float(job.run_after_ts or 0.0) > 0 and time.time() < float(job.run_after_ts):
                # Not ready yet; re-enqueue after the delay (best-effort).
                delay = max(0.0, float(job.run_after_ts) - time.time())

                async def _delay_enqueue(jid: str, d: float) -> None:
                    try:
                        await asyncio.sleep(d)
                        self.enqueue(jid)
                    except Exception:
                        pass

                asyncio.create_task(_delay_enqueue(job.id, min(delay, 3600.0)))
                continue

            # Claim the job for this worker.
            if not self.store.claim_job(job_id):
                continue
            job = self.store.get_job(job_id) or job

            tool = self._tools.get(job.job_type) if self._tools else None
            handler = self._handlers.get(job.job_type)
            if not tool and not handler:
                self.store.update_job(job.id, status="failed", error=f"Unknown job type: {job.job_type}")
                continue

            # Execute
            cancel_ev = self._cancel_events.get(job.id) or asyncio.Event()
            cancel_ev.clear()
            self._cancel_events[job.id] = cancel_ev
            self.store.update_job(job.id, progress=0.01, error="", run_after_ts=0.0)
            try:
                sem = self._get_tool_semaphore(job.job_type)
                async with sem:
                    if tool:
                        if not self._ctx:
                            raise RuntimeError("ToolContext is not configured for JobRunner")

                        def update_progress(p: float) -> None:
                            self.check_job_cancelled(job.id)
                            try:
                                self.store.update_job(job.id, progress=max(0.0, min(1.0, float(p))))
                            except Exception:
                                pass

                        timeout_seconds = float(
                            (job.payload or {}).get("timeout_seconds") or self._default_timeouts.get(job.job_type, 0) or 0.0
                        )
                        task = asyncio.create_task(tool.run(job, self._ctx, update_progress))
                        self._running_tasks[job.id] = task
                        if timeout_seconds > 0:
                            result = await asyncio.wait_for(task, timeout=timeout_seconds)
                        else:
                            result = await task
                        if isinstance(result, dict) and result.get("ok") is False:
                            self.store.update_job(
                                job.id,
                                status="failed",
                                error=str(result.get("error") or "tool failed"),
                                progress=1.0,
                                result=result,
                            )
                        else:
                            self.store.update_job(job.id, status="succeeded", progress=1.0, result=result or {})
                    else:
                        timeout_seconds = float(
                            (job.payload or {}).get("timeout_seconds") or self._default_timeouts.get(job.job_type, 0) or 0.0
                        )
                        task = asyncio.create_task(handler(job))
                        self._running_tasks[job.id] = task
                        if timeout_seconds > 0:
                            await asyncio.wait_for(task, timeout=timeout_seconds)
                        else:
                            await task
                        # Handler is responsible for final status/result; enforce success if missing.
                        done = self.store.get_job(job.id)
                        if done and done.status == "running":
                            self.store.update_job(job.id, status="succeeded", progress=1.0)
            except JobCancelled:
                self.store.update_job(job.id, status="canceled", progress=1.0, error="")
            except asyncio.CancelledError:
                self.store.update_job(job.id, status="canceled", progress=1.0, error="")
            except asyncio.TimeoutError:
                if self._should_retry(job):
                    self._schedule_retry(job, error="timeout")
                else:
                    self.store.update_job(job.id, status="failed", error="timeout", progress=1.0)
            except Exception as e:
                if self.is_job_cancelled(job.id):
                    self.store.update_job(job.id, status="canceled", progress=1.0, error="")
                else:
                    if self._should_retry(job):
                        self._schedule_retry(job, error=str(e))
                    else:
                        self.store.update_job(job.id, status="failed", error=str(e), progress=1.0)
            finally:
                self._running_tasks.pop(job.id, None)
                self._cancel_events.pop(job.id, None)
