"""Persistent background job queue backed by SQLite.

- Jobs survive crashes: anything left 'running' at boot is re-queued (handlers must be idempotent).
- Retries use exponential backoff (2^attempt * 5s, capped at 1h).
- `idempotency_key` makes enqueueing the same logical job twice a no-op.
- Cancellation: queued jobs are cancelled at once; running handlers poll `ctx.cancelled()`.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .models import Job

log = logging.getLogger("clippr.jobs")


class JobCancelled(Exception):
    pass


class PermanentJobError(Exception):
    """Raise from a handler to fail without retrying."""


class JobContext:
    def __init__(self, queue: "JobQueue", job_id: int):
        self.queue, self.job_id = queue, job_id

    def cancelled(self) -> bool:
        with self.queue.db.session() as s:
            return s.get(Job, self.job_id).status == "cancelled"

    def check(self) -> None:
        if self.cancelled():
            raise JobCancelled()


Handler = Callable[[JobContext, dict[str, Any]], dict[str, Any] | None]


class JobQueue:
    def __init__(self, db):
        self.db = db
        self.handlers: dict[str, Handler] = {}
        self.periodic: list[tuple[str, int, Callable[[], dict[str, Any]]]] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_periodic: dict[str, float] = {}

    def register(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def every(self, kind: str, seconds: int, payload: Callable[[], dict[str, Any]] = dict) -> None:
        self.periodic.append((kind, seconds, payload))

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None, *, idempotency_key: str | None = None,
                max_attempts: int = 5, delay: float = 0) -> int | None:
        if kind not in self.handlers:
            raise ValueError(f"No handler for job kind '{kind}'")
        try:
            with self.db.session() as s:
                job = Job(kind=kind, payload=payload or {}, idempotency_key=idempotency_key, max_attempts=max_attempts,
                          run_after=datetime.now(timezone.utc) + timedelta(seconds=delay))
                s.add(job)
                s.flush()
                return job.id
        except IntegrityError:
            return None  # same idempotency key already queued/ran

    def recover(self) -> int:
        with self.db.session() as s:
            res = s.execute(update(Job).where(Job.status == "running").values(status="queued", started_at=None))
            if res.rowcount:
                log.info("re-queued %s interrupted job(s)", res.rowcount)
            return res.rowcount

    def cancel(self, job_id: int) -> bool:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if not job or job.status not in ("queued", "running"):
                return False
            job.status, job.finished_at = "cancelled", datetime.now(timezone.utc)
            return True

    def retry(self, job_id: int) -> bool:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if not job or job.status not in ("failed", "cancelled"):
                return False
            job.status, job.attempts, job.error, job.run_after = "queued", 0, None, datetime.now(timezone.utc)
            return True

    def _claim(self) -> int | None:
        now = datetime.now(timezone.utc)
        with self.db.session() as s:
            job_id = s.scalar(select(Job.id).where(Job.status == "queued", Job.run_after <= now).order_by(Job.run_after, Job.id).limit(1))
            if job_id is None:
                return None
            # Compare-and-set so concurrent workers never run the same job.
            res = s.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                            .values(status="running", started_at=now, attempts=Job.attempts + 1))
            return job_id if res.rowcount == 1 else None

    def run_one(self) -> bool:
        job_id = self._claim()
        if job_id is None:
            return False
        with self.db.session() as s:
            job = s.get(Job, job_id)
            kind, payload, attempts, max_attempts = job.kind, dict(job.payload), job.attempts, job.max_attempts
        handler = self.handlers.get(kind)
        try:
            if not handler:
                raise PermanentJobError(f"No handler registered for '{kind}'")
            result = handler(JobContext(self, job_id), payload) or {}
            self._finish(job_id, "succeeded", result=result)
        except JobCancelled:
            self._finish(job_id, "cancelled")
        except PermanentJobError as e:
            self._finish(job_id, "failed", error=str(e))
        except Exception as e:  # retryable
            log.exception("job %s (%s) failed on attempt %s", job_id, kind, attempts)
            if attempts >= max_attempts:
                self._finish(job_id, "failed", error=f"{type(e).__name__}: {e}"[:500])
            else:
                backoff = min(3600, (2 ** attempts) * 5)
                with self.db.session() as s:
                    j = s.get(Job, job_id)
                    if j.status == "running":
                        j.status, j.error = "queued", f"{type(e).__name__}: {e}"[:500]
                        j.run_after = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        return True

    def _finish(self, job_id: int, status: str, *, result: dict | None = None, error: str | None = None) -> None:
        with self.db.session() as s:
            j = s.get(Job, job_id)
            if j.status == "cancelled" and status != "cancelled":
                return
            j.status, j.result, j.error, j.finished_at = status, result, error, datetime.now(timezone.utc)

    def _tick_periodic(self) -> None:
        now = time.time()
        for kind, seconds, payload in self.periodic:
            if now - self._last_periodic.get(kind, 0) >= seconds:
                self._last_periodic[kind] = now
                bucket = int(now // seconds)
                self.enqueue(kind, payload(), idempotency_key=f"periodic:{kind}:{bucket}", max_attempts=1)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_periodic()
                if not self.run_one():
                    self._stop.wait(1.0)
            except Exception:
                log.exception("worker loop error")
                self._stop.wait(5.0)

    def start(self, workers: int = 1) -> None:
        self.recover()
        for i in range(workers):
            t = threading.Thread(target=self._loop, name=f"clippr-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)
