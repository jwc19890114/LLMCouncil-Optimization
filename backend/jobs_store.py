"""Persistent job store (SQLite).

Implements VCP-like "long task" primitives:
- Create a job with payload
- Update status/progress/result/error
- List jobs (optionally scoped to conversation)
- Mark completed results as injected into conversation context ("refill")
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import PROJECT_ROOT


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "jobs.sqlite")


@dataclass(frozen=True)
class Job:
    id: str
    job_type: str
    status: str
    conversation_id: str
    payload: Dict[str, Any]
    progress: float
    result: Dict[str, Any]
    error: str
    idempotency_key: str
    attempts: int
    max_attempts: int
    run_after_ts: float
    created_at: str
    updated_at: str
    injected: bool


class JobsStore:
    def __init__(self, db_path: str = JOBS_DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._listeners: List[Callable[[Job], None]] = []
        self._last_notify: Dict[str, tuple[str, int]] = {}

    def subscribe(self, listener: Callable[[Job], None]) -> None:
        self._listeners.append(listener)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            # NOTE: Keep migration order safe for older DBs.
            # If a legacy `jobs` table exists without newer columns, creating indexes that reference
            # missing columns will fail before the ALTER TABLE migration runs.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  job_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  conversation_id TEXT NOT NULL DEFAULT '',
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  progress REAL NOT NULL DEFAULT 0.0,
                  result_json TEXT NOT NULL DEFAULT '{}',
                  error TEXT NOT NULL DEFAULT '',
                  idempotency_key TEXT NOT NULL DEFAULT '',
                  attempts INTEGER NOT NULL DEFAULT 0,
                  max_attempts INTEGER NOT NULL DEFAULT 0,
                  run_after_ts REAL NOT NULL DEFAULT 0,
                  injected INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            # Lightweight migration for older DBs.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "idempotency_key" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''")
            if "attempts" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "max_attempts" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 0")
            if "run_after_ts" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN run_after_ts REAL NOT NULL DEFAULT 0")
            if "injected" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN injected INTEGER NOT NULL DEFAULT 0")
            if "created_at" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

            # Indexes (best-effort).
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS jobs_conversation_id ON jobs(conversation_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS jobs_updated_at ON jobs(updated_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS jobs_idempotency_key ON jobs(job_type, idempotency_key)")
                conn.execute("CREATE INDEX IF NOT EXISTS jobs_run_after_ts ON jobs(run_after_ts)")
            except Exception:
                pass

    def get_by_idempotency(self, *, job_type: str, idempotency_key: str) -> Optional[Job]:
        job_type = str(job_type or "").strip()
        idempotency_key = str(idempotency_key or "").strip()
        if not job_type or not idempotency_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_type=? AND idempotency_key=? ORDER BY created_at DESC LIMIT 1",
                (job_type, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def create_job(
        self,
        *,
        job_id: str,
        job_type: str,
        conversation_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: str = "",
        max_attempts: int = 0,
    ) -> Job:
        created_at = _now_iso()
        updated_at = created_at
        payload = payload or {}
        idempotency_key = str(idempotency_key or "").strip()
        max_attempts = max(0, min(20, int(max_attempts)))
        if idempotency_key:
            existing = self.get_by_idempotency(job_type=job_type, idempotency_key=idempotency_key)
            if existing and existing.status not in ("failed", "canceled"):
                return existing
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(id,job_type,status,conversation_id,payload_json,progress,result_json,error,idempotency_key,attempts,max_attempts,run_after_ts,injected,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    job_type,
                    "queued",
                    conversation_id or "",
                    json.dumps(payload, ensure_ascii=False),
                    0.0,
                    "{}",
                    "",
                    idempotency_key,
                    0,
                    max_attempts,
                    0.0,
                    0,
                    created_at,
                    updated_at,
                ),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(
        self,
        *,
        conversation_id: str = "",
        status: str = "",
        limit: int = 50,
    ) -> List[Job]:
        limit = max(1, min(500, int(limit)))
        where = []
        params: List[Any] = []
        if conversation_id:
            where.append("conversation_id=?")
            params.append(conversation_id)
        if status:
            where.append("status=?")
            params.append(status)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {where_sql} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        injected: Optional[bool] = None,
        attempts: Optional[int] = None,
        max_attempts: Optional[int] = None,
        run_after_ts: Optional[float] = None,
    ) -> bool:
        updated_at = _now_iso()
        fields = []
        params: List[Any] = []
        if status is not None:
            fields.append("status=?")
            params.append(status)
        if progress is not None:
            fields.append("progress=?")
            params.append(float(progress))
        if result is not None:
            fields.append("result_json=?")
            params.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            fields.append("error=?")
            params.append(str(error))
        if injected is not None:
            fields.append("injected=?")
            params.append(1 if injected else 0)
        if attempts is not None:
            fields.append("attempts=?")
            params.append(max(0, int(attempts)))
        if max_attempts is not None:
            fields.append("max_attempts=?")
            params.append(max(0, min(20, int(max_attempts))))
        if run_after_ts is not None:
            fields.append("run_after_ts=?")
            params.append(max(0.0, float(run_after_ts)))
        if not fields:
            return False
        fields.append("updated_at=?")
        params.append(updated_at)
        params.append(job_id)
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", (*params,))
            ok = cur.rowcount > 0

        if ok and self._listeners:
            job = self.get_job(job_id)
            if job:
                should_notify = False
                # Notify on status change, or on result/error updates.
                bucket = int(max(0.0, min(1.0, job.progress)) * 20)  # 5% buckets
                last = self._last_notify.get(job.id)
                if status is not None and (not last or last[0] != job.status):
                    should_notify = True
                if result is not None or error is not None:
                    should_notify = True
                if progress is not None and (not last or last[1] != bucket):
                    # Throttle progress updates.
                    should_notify = True

                if should_notify:
                    self._last_notify[job.id] = (job.status, bucket)
                    for cb in list(self._listeners):
                        try:
                            cb(job)
                        except Exception:
                            pass

        return ok

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        if job.status in ("succeeded", "failed", "canceled"):
            return False
        return self.update_job(job_id, status="canceled")

    def requeue_running_jobs(self) -> int:
        """
        Best-effort crash recovery: move jobs stuck in 'running' back to 'queued'.
        Returns the number of jobs requeued.
        """
        updated_at = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='queued', updated_at=? WHERE status='running'",
                (updated_at,),
            )
            return int(cur.rowcount or 0)

    def list_queued_job_ids(self, *, limit: int = 2000) -> List[str]:
        limit = max(1, min(20000, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(r["id"]) for r in rows if r and r["id"]]

    def claim_job(self, job_id: str) -> bool:
        """
        Atomically claim a queued job for execution.
        Prevents duplicate execution when multiple workers are running.
        """
        updated_at = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
                (updated_at, job_id),
            )
            return bool(cur.rowcount and int(cur.rowcount) > 0)

    def cleanup_terminal_jobs(self, *, max_age_days: int = 14) -> int:
        """
        Delete old terminal jobs to keep the DB small and avoid unbounded growth.
        Returns number of deleted rows.
        """
        from datetime import timedelta

        days = max(1, int(max_age_days))
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM jobs WHERE status IN ('succeeded','failed','canceled') AND updated_at < ?",
                (cutoff,),
            )
            return int(cur.rowcount or 0)

    def fetch_injectable_summaries(self, *, conversation_id: str, limit: int = 4) -> List[Dict[str, Any]]:
        """
        Return completed job summaries that haven't been injected into prompt yet.
        Marks them as injected to avoid repeated prompt bloat.
        """
        conversation_id = (conversation_id or "").strip()
        if not conversation_id:
            return []
        limit = max(1, min(20, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE conversation_id=? AND status='succeeded' AND injected=0
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        jobs = [self._row_to_job(r) for r in rows]
        if not jobs:
            return []

        out: List[Dict[str, Any]] = []
        for j in jobs:
            summary = str((j.result or {}).get("summary") or "").strip()
            if not summary:
                # Best-effort fallback
                summary = f"Job {j.id} ({j.job_type}) 已完成。"
            out.append({"job_id": j.id, "job_type": j.job_type, "summary": summary, "result": j.result})

        # Mark injected (best-effort).
        for j in jobs:
            self.update_job(j.id, injected=True)
        return out

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        payload = {}
        result = {}
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        try:
            result = json.loads(row["result_json"] or "{}")
        except Exception:
            result = {}

        return Job(
            id=row["id"],
            job_type=row["job_type"],
            status=row["status"],
            conversation_id=row["conversation_id"] or "",
            payload=payload if isinstance(payload, dict) else {},
            progress=float(row["progress"] or 0.0),
            result=result if isinstance(result, dict) else {},
            error=row["error"] or "",
            idempotency_key=str(row["idempotency_key"] or ""),
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or 0),
            run_after_ts=float(row["run_after_ts"] or 0.0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            injected=bool(int(row["injected"] or 0)),
        )
