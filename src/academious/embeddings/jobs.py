"""Embedding work as queue jobs.

Duplicate work is prevented at two levels, because each catches what the other
cannot:

* `dedup_key` stops the *same batch* being queued twice, which is what happens
  when the enqueue pass runs again before the previous one has drained.
* `input_text_hash`, checked inside `embed_papers`, stops the same *paper* being
  re-encoded when it arrives through a differently-shaped batch. This is the
  guarantee that actually matters, since it holds no matter how work was
  partitioned.

A job carries paper ids rather than a range or an offset. Ids are stable, so a
job means the same thing whenever it eventually runs - including after a crash,
after new papers are ingested, or after another worker has taken the papers that
would have sat in the same offset window.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from academious.core.logging import get_logger
from academious.db.models.ops import Job
from academious.embeddings import service
from academious.embeddings.backend import EmbeddingBackend
from academious.embeddings.registry import EmbeddingProfile
from academious.jobs import queue

log = get_logger(__name__)

JOB_KIND = "embed_papers"

#: Embeddings are not latency-critical and must never crowd out ingestion, which
#: has source-side rate limits it cannot defer. Higher number, lower priority.
JOB_PRIORITY = 200


def batch_dedup_key(model_key: str, paper_ids: Sequence[uuid.UUID]) -> str:
    """Stable key for a batch, independent of the order ids arrived in."""
    joined = ",".join(sorted(str(paper_id) for paper_id in paper_ids))
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]
    return f"embed:{model_key}:{digest}"


def enqueue_pending(
    session: Session,
    profile: EmbeddingProfile,
    *,
    batch_size: int = service.DEFAULT_BATCH_SIZE,
    max_papers: int | None = None,
) -> tuple[int, int]:
    """Queue embedding jobs for papers that need one. Returns (jobs, papers).

    Papers already covered by a queued-but-undrained job are still returned by
    the pending query - nothing marks a paper as claimed before its job runs.
    The dedup key absorbs that when the batching is identical; when it is not,
    the hash check absorbs it at execution time. Neither case does model work
    twice.

    One pass queues at most MAX_PENDING_SCAN papers. Call it again to queue
    more; there is no state to carry between calls.
    """
    jobs = 0
    papers = 0
    for batch in service.iter_pending_batches(
        session, profile.key, batch_size=batch_size, max_papers=max_papers
    ):
        job = queue.enqueue(
            session,
            JOB_KIND,
            {"model_key": profile.key, "paper_ids": [str(paper_id) for paper_id in batch]},
            dedup_key=batch_dedup_key(profile.key, batch),
            priority=JOB_PRIORITY,
        )
        papers += len(batch)
        if job is not None:
            jobs += 1

    log.info("embeddings.enqueued", model_key=profile.key, jobs=jobs, papers=papers)
    return jobs, papers


def paper_ids_from_payload(payload: dict[str, object]) -> list[uuid.UUID]:
    raw = payload.get("paper_ids") or []
    if not isinstance(raw, list):
        raise ValueError(f"embed job payload has a non-list paper_ids: {type(raw).__name__}")
    return [uuid.UUID(str(value)) for value in raw]


def handle(
    session: Session,
    job: Job,
    *,
    profile: EmbeddingProfile,
    backend: EmbeddingBackend,
) -> service.EmbeddingStats:
    """Execute one embed job. Raises on failure so the caller can retry it."""
    payload = job.payload or {}
    model_key = payload.get("model_key")
    if model_key != profile.key:
        raise ValueError(
            f"job {job.id} is for model_key {model_key!r}, but this worker runs {profile.key!r}"
        )
    paper_ids = paper_ids_from_payload(payload)
    return service.embed_papers(session, paper_ids, profile=profile, backend=backend)
