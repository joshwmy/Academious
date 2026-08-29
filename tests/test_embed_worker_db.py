"""The embedding worker loop: transaction boundaries and failure handling.

`tests/test_embeddings_db.py` covers the service and the job handler. This file
covers the thing wrapped around them - claim, execute, complete - because the
separation of those three into distinct transactions is the entire reason a
killed worker is recoverable, and that property is invisible from either side
alone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from academious.core.clock import utcnow
from academious.db.models.embedding import PaperEmbedding
from academious.db.models.ops import Job, JobStatus
from academious.embeddings.hashing import HashingBackend
from academious.embeddings.registry import HASHING_AUTO
from academious.workers import embed as embed_worker
from tests.factories import make_paper

pytestmark = pytest.mark.db

PROFILE = HASHING_AUTO
ABSTRACT = (
    "Message passing over molecular graphs predicts quantum chemical properties "
    "at a fraction of the cost of density functional theory."
)


class ExplodingBackend(HashingBackend):
    """Fails every document batch, the way a model that will not load would."""

    def encode_documents(self, texts):
        raise RuntimeError("simulated inference failure")


def test_resolve_profile_uses_the_key_it_is_given():
    assert embed_worker.resolve_profile(PROFILE.key).key == PROFILE.key


def test_resolve_profile_rejects_an_unknown_key():
    with pytest.raises(KeyError, match="unknown embedding profile"):
        embed_worker.resolve_profile("not-a-real-profile@v9")


def test_build_returns_a_backend_without_loading_a_model():
    backend = embed_worker.build(PROFILE)
    assert backend.dimension == 768


def test_enqueue_then_work_embeds_the_corpus(session):
    for index in range(5):
        make_paper(session, f"Worker paper {index}", abstract=ABSTRACT)
    session.commit()

    jobs, papers = embed_worker.enqueue(PROFILE, batch_size=2)
    assert (jobs, papers) == (3, 5)

    stats = embed_worker.work(PROFILE, HashingBackend())
    assert stats.embedded == 5
    assert stats.failed == 0

    session.expire_all()
    stored = session.execute(select(PaperEmbedding)).scalars().all()
    assert len(stored) == 5
    assert embed_worker.pending_count(PROFILE.key) == 0


def test_working_an_empty_queue_is_a_no_op(session):
    stats = embed_worker.work(PROFILE, HashingBackend())
    assert stats.embedded == 0
    assert stats.failed == 0


def test_max_jobs_bounds_a_run(session):
    for index in range(6):
        make_paper(session, f"Bounded {index}", abstract=ABSTRACT)
    session.commit()
    embed_worker.enqueue(PROFILE, batch_size=2)

    stats = embed_worker.work(PROFILE, HashingBackend(), max_jobs=1)

    assert stats.embedded == 2
    session.expire_all()
    assert embed_worker.pending_count(PROFILE.key) == 4


def test_a_failing_job_is_recorded_and_does_not_stop_the_worker(session):
    make_paper(session, "Poison paper", abstract=ABSTRACT)
    session.commit()
    embed_worker.enqueue(PROFILE, batch_size=10)

    stats = embed_worker.work(PROFILE, ExplodingBackend())

    assert stats.failed == 1
    assert stats.embedded == 0
    session.expire_all()
    job = session.execute(select(Job)).scalars().one()
    # A first failure schedules a retry rather than giving up, and backs off so
    # a permanently broken model cannot spin the worker.
    assert job.status == JobStatus.PENDING.value
    assert job.run_after > utcnow()
    assert "simulated inference failure" in job.last_error
    # And ingestion is untouched: the paper is still there, just unembedded.
    assert embed_worker.pending_count(PROFILE.key) == 1


def _clear_backoff(session):
    """Make a backed-off job claimable now, so a retry can be tested without waiting."""
    session.expire_all()
    job = session.execute(select(Job)).scalars().one()
    job.run_after = utcnow()
    session.commit()
    return job


def test_a_job_that_keeps_failing_ends_up_failed(session):
    make_paper(session, "Persistently poisonous", abstract=ABSTRACT)
    session.commit()
    embed_worker.enqueue(PROFILE, batch_size=10)

    for _ in range(6):
        embed_worker.work(PROFILE, ExplodingBackend())
        _clear_backoff(session)

    session.expire_all()
    job = session.execute(select(Job)).scalars().one()
    assert job.status == JobStatus.FAILED.value
    assert job.attempts >= job.max_attempts


def test_a_recovered_backend_finishes_what_the_failure_left(session):
    make_paper(session, "Recovers on retry", abstract=ABSTRACT)
    session.commit()
    embed_worker.enqueue(PROFILE, batch_size=10)

    embed_worker.work(PROFILE, ExplodingBackend())
    _clear_backoff(session)
    stats = embed_worker.work(PROFILE, HashingBackend())

    assert stats.embedded == 1
    session.expire_all()
    assert embed_worker.pending_count(PROFILE.key) == 0


def test_run_is_one_full_cycle(session):
    for index in range(3):
        make_paper(session, f"Full cycle {index}", abstract=ABSTRACT)
    session.commit()

    stats = embed_worker.run(PROFILE.key, batch_size=2)

    assert stats.embedded == 3
    session.expire_all()
    assert embed_worker.pending_count(PROFILE.key) == 0


def test_run_can_stop_after_enqueueing(session):
    """--enqueue-only never loads the model, so it is cheap to run often."""
    make_paper(session, "Queued only", abstract=ABSTRACT)
    session.commit()

    stats = embed_worker.run(PROFILE.key, enqueue_only=True)

    assert stats.embedded == 0
    session.expire_all()
    assert session.execute(select(Job)).scalars().all()
    assert embed_worker.pending_count(PROFILE.key) == 1


def test_run_is_idempotent(session):
    make_paper(session, "Run twice", abstract=ABSTRACT)
    session.commit()

    embed_worker.run(PROFILE.key)
    second = embed_worker.run(PROFILE.key)

    assert second.embedded == 0
    session.expire_all()
    assert len(session.execute(select(PaperEmbedding)).scalars().all()) == 1


def test_reap_returns_nothing_when_no_worker_has_died(session):
    assert embed_worker.reap() == 0
