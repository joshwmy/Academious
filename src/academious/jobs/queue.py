"""Postgres-backed work queue using SELECT ... FOR UPDATE SKIP LOCKED.

At roughly 30k jobs/day Postgres handles this comfortably, and it keeps Redis, a
broker and a result backend out of the deployment. See ADR 0002.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    """Add a job. With a dedup_key, work already in flight is not duplicated.

    A dedup key reserves work while it is pending or running; it does not retire
    that work for ever. The same batch legitimately recurs - papers go stale
    again, a migration re-checks the corpus - so once the previous attempt has
    finished the key is reusable.

    `dedup_key` is UNIQUE, so "reusable" has to mean reusing the row. Inserting a
    second row with the same key raises IntegrityError, which is what this did
    before: the status guard permitted the re-queue and the constraint then
    killed the worker on it.
    """
    now = utcnow()
    if dedup_key is not None:
        existing = (
            session.execute(select(Job).where(Job.dedup_key == dedup_key)).scalars().first()
        )
        if existing is not None:
            if existing.status in {JobStatus.PENDING.value, JobStatus.RUNNING.value}:
                return None
            # Finished. Reset it to a fresh attempt rather than inserting a
            # duplicate: a re-queue starts from zero attempts and no error, so
            # backoff and give-up behaviour do not inherit the last run's state.
            existing.payload = payload or {}
            existing.priority = priority
            existing.max_attempts = max_attempts
            existing.status = JobStatus.PENDING.value
            existing.attempts = 0
            existing.locked_at = None
            existing.last_error = None
            existing.run_after = now + (delay or timedelta(0))
            existing.updated_at = now
            return existing

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


#: A worker that dies mid-job leaves its row in `running` with `locked_at` set and
#: no process to finish it. Nothing else will ever claim that row, because the
#: claim query only looks at `pending`. This is the only mechanism that returns
#: such a job to the queue, so embedding work survives an OOM kill or a Ctrl-C.
DEFAULT_STALE_AFTER = timedelta(minutes=30)


def reap_stale(
    session: Session, *, older_than: timedelta = DEFAULT_STALE_AFTER, now: datetime | None = None
) -> int:
    """Requeue jobs left `running` by a worker that never came back.

    The job's attempt was already counted when it was claimed, so a job whose
    worker keeps dying still exhausts `max_attempts` and lands in `failed`
    rather than looping forever.
    """
    moment = now or utcnow()
    cutoff = moment - older_than
    stale = session.execute(
        select(Job).where(
            Job.status == JobStatus.RUNNING.value,
            Job.locked_at.is_not(None),
            Job.locked_at < cutoff,
        )
    ).scalars().all()

    for job in stale:
        job.locked_at = None
        job.updated_at = moment
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED.value
            job.last_error = "worker did not report back before the stale-job timeout"
            log.error("job.reaped_failed", kind=job.kind, id=str(job.id), attempts=job.attempts)
        else:
            job.status = JobStatus.PENDING.value
            job.run_after = moment
            log.warning("job.reaped", kind=job.kind, id=str(job.id), attempts=job.attempts)

    session.flush()
    return len(stale)
