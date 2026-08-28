"""Postgres-backed work queue using SELECT ... FOR UPDATE SKIP LOCKED.

At roughly 30k jobs/day Postgres handles this comfortably, and it keeps Redis, a
broker and a result backend out of the deployment. See ADR 0002.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.core.logging import get_logger
from academious.db.models.ops import Job, JobStatus

log = get_logger(__name__)

CLAIM_SQL = text(
    """
    SELECT id FROM job
    WHERE status = 'pending' AND run_after <= :now
    ORDER BY priority ASC, run_after ASC
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
    """
)


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    dedup_key: str | None = None,
    priority: int = 100,
    delay: timedelta | None = None,
    max_attempts: int = 5,
) -> Job | None:
    """Add a job. With a dedup_key, an identical pending job is not duplicated."""
    now = utcnow()
    if dedup_key is not None:
        existing = session.execute(
            select(Job).where(Job.dedup_key == dedup_key)
        ).scalars().first()
        if existing is not None and existing.status in {
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
        }:
            return None

    job = Job(
        kind=kind,
        payload=payload or {},
        dedup_key=dedup_key,
        priority=priority,
        max_attempts=max_attempts,
        run_after=now + (delay or timedelta(0)),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    return job


def claim(session: Session, limit: int = 1) -> list[Job]:
    """Atomically claim up to `limit` runnable jobs."""
    now = utcnow()
    ids = [row.id for row in session.execute(CLAIM_SQL, {"now": now, "limit": limit}).all()]
    claimed: list[Job] = []
    for job_id in ids:
        job = session.get(Job, job_id)
        if job is None:
            continue
        job.status = JobStatus.RUNNING.value
        job.attempts += 1
        job.locked_at = now
        job.updated_at = now
        claimed.append(job)
    session.flush()
    return claimed


def complete(session: Session, job: Job) -> None:
    job.status = JobStatus.SUCCEEDED.value
    job.locked_at = None
    job.last_error = None
    job.updated_at = utcnow()


def fail(session: Session, job: Job, error: str, *, retry_in: timedelta | None = None) -> None:
    """Reschedule with backoff, or mark failed once attempts are exhausted."""
    now = utcnow()
    job.last_error = error[:2000]
    job.locked_at = None
    job.updated_at = now
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.FAILED.value
        log.error("job.failed", kind=job.kind, id=str(job.id), attempts=job.attempts)
        return
    backoff = retry_in or timedelta(seconds=min(3600, 30 * 2 ** (job.attempts - 1)))
    job.status = JobStatus.PENDING.value
    job.run_after = now + backoff
    log.warning("job.retry", kind=job.kind, id=str(job.id), attempt=job.attempts)
