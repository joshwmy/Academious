"""The embedding worker: enqueue pending work, then drain it.

Transaction boundaries are the whole design here, so they are explicit:

1. **Claim** commits on its own. The attempt counter has to survive a crash,
   otherwise a job that kills its worker every time is retried forever.
2. **Execute** runs in its own transaction and commits the vectors. This is the
   expensive part, and committing it separately means a failure while completing
   the job cannot throw the inference away.
3. **Complete or fail** commits last.

A process killed between 2 and 3 leaves the job in `running` with its vectors
already saved. The reaper returns it to `pending`, it runs again, and the hash
check finds every paper already done - so the retry costs a query, not a
re-encode.
"""

from __future__ import annotations

from datetime import timedelta

from academious.core.config import Settings, get_settings
from academious.core.logging import get_logger
from academious.db.models.ops import Job
from academious.db.session import session_scope
from academious.embeddings import jobs as embed_jobs
from academious.embeddings import service
from academious.embeddings.backend import EmbeddingBackend
from academious.embeddings.registry import EmbeddingProfile, build_backend, get_profile
from academious.jobs import queue

log = get_logger(__name__)


def resolve_profile(profile_key: str | None = None) -> EmbeddingProfile:
    return get_profile(profile_key or get_settings().embedding_profile)


def build(profile: EmbeddingProfile, settings: Settings | None = None) -> EmbeddingBackend:
    """Construct the backend for a profile from configuration."""
    active = settings or get_settings()
    if profile.backend_name != "specter2":
        return build_backend(profile)
    return build_backend(
        profile,
        batch_size=active.embedding_batch_size,
        num_threads=active.embedding_torch_threads or None,
        cache_dir=active.embedding_cache_dir or None,
    )


def reap() -> int:
    """Return jobs abandoned by a dead worker to the queue."""
    settings = get_settings()
    with session_scope() as session:
        return queue.reap_stale(
            session, older_than=timedelta(minutes=settings.job_stale_after_minutes)
        )


def enqueue(
    profile: EmbeddingProfile,
    *,
    batch_size: int | None = None,
    max_papers: int | None = None,
) -> tuple[int, int]:
    """Queue jobs for every paper that still needs an embedding."""
    settings = get_settings()
    with session_scope() as session:
        return embed_jobs.enqueue_pending(
            session,
            profile,
            batch_size=batch_size or settings.embedding_job_batch_size,
            max_papers=max_papers,
        )


def work(
    profile: EmbeddingProfile,
    backend: EmbeddingBackend,
    *,
    max_jobs: int | None = None,
) -> service.EmbeddingStats:
    """Drain embedding jobs until the queue is empty or max_jobs is reached."""
    totals = service.EmbeddingStats()
    processed = 0

    while max_jobs is None or processed < max_jobs:
        with session_scope() as session:
            claimed = queue.claim(session, limit=1)
            job_id = claimed[0].id if claimed else None
        if job_id is None:
            break

        processed += 1
        try:
            with session_scope() as session:
                job = session.get(Job, job_id)
                if job is None:
                    continue
                stats = embed_jobs.handle(session, job, profile=profile, backend=backend)
            totals.merge(stats)
            with session_scope() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    queue.complete(session, job)
            log.info("embeddings.job_done", job_id=str(job_id), **stats.as_dict())
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
            totals.failed += 1
            log.exception("embeddings.job_failed", job_id=str(job_id))
            with session_scope() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    queue.fail(session, job, f"{type(exc).__name__}: {exc}")

    return totals


def run(
    profile_key: str | None = None,
    *,
    batch_size: int | None = None,
    max_papers: int | None = None,
    max_jobs: int | None = None,
    enqueue_only: bool = False,
) -> service.EmbeddingStats:
    """One full cycle: reap, enqueue, drain. The shape a cron entry wants."""
    profile = resolve_profile(profile_key)

    reaped = reap()
    if reaped:
        log.warning("embeddings.reaped_stale_jobs", count=reaped)

    queued, papers = enqueue(profile, batch_size=batch_size, max_papers=max_papers)
    log.info("embeddings.pending", model_key=profile.key, jobs=queued, papers=papers)

    if enqueue_only:
        return service.EmbeddingStats()

    backend = build(profile)
    return work(profile, backend, max_jobs=max_jobs)


def pending_count(profile_key: str | None = None) -> int:
    profile = resolve_profile(profile_key)
    with session_scope() as session:
        return service.count_pending(session, profile.key)
