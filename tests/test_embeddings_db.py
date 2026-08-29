"""Embedding persistence, idempotency, versioning and crash safety.

These run against a real PostgreSQL with pgvector, because halfvec storage and
the anti-join that finds unembedded papers are both SQL behaviour that a fake
would not exercise. Model inference is the only thing stubbed: HashingBackend
produces real, deterministic vectors without loading 440 MB of weights.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from academious.core.clock import utcnow
from academious.db.models.embedding import PaperEmbedding
from academious.db.models.ops import Job, JobStatus
from academious.embeddings import jobs as embed_jobs
from academious.embeddings import service
from academious.embeddings.hashing import HashingBackend
from academious.embeddings.registry import HASHING_AUTO, EmbeddingProfile
from academious.embeddings.text import InputMode, InputStrategy
from academious.jobs import queue
from tests.factories import make_paper

pytestmark = pytest.mark.db

PROFILE = HASHING_AUTO
TITLE_ONLY_PROFILE = EmbeddingProfile(
    key="hashing-title-only@v1", backend_name="hashing", input_mode=InputMode.TITLE_ONLY
)
ABSTRACT = (
    "We train a convolutional network on tumour sequencing data and show that it "
    "predicts driver mutations more accurately than existing baselines."
)


class CountingBackend:
    """Wraps a backend and records how much inference was actually asked for."""

    def __init__(self, inner=None):
        self._inner = inner or HashingBackend()
        self.model_id = self._inner.model_id
        self.dimension = self._inner.dimension
        self.max_sequence_length = self._inner.max_sequence_length
        self.document_batches = 0
        self.documents_encoded = 0

    def encode_documents(self, texts):
        self.document_batches += 1
        self.documents_encoded += len(texts)
        return self._inner.encode_documents(texts)

    def encode_queries(self, texts):
        return self._inner.encode_queries(texts)


def embed_all(session, backend, profile=PROFILE):
    pending = service.select_pending_paper_ids(session, profile.key, limit=1000)
    return service.embed_papers(session, pending, profile=profile, backend=backend)


# --------------------------------------------------------------- persistence


def test_a_vector_is_stored_for_an_ingested_paper(session):
    paper = make_paper(session, "Deep learning for cancer genomics", abstract=ABSTRACT)
    backend = CountingBackend()

    stats = embed_all(session, backend)
    session.commit()

    row = session.get(PaperEmbedding, (paper.id, PROFILE.key))
    assert stats.embedded == 1
    assert row is not None
    assert row.dim == 768
    assert len(row.embedding) == 768
    assert row.input_strategy == InputStrategy.TITLE_ABSTRACT.value
    assert row.truncated is False
    assert row.token_count > 0


def test_a_paper_with_no_abstract_still_gets_an_embedding(session):
    """A paper absent from the index cannot be discovered at all."""
    paper = make_paper(session, "An arXiv record with a title and nothing else")

    stats = embed_all(session, CountingBackend())
    session.commit()

    row = session.get(PaperEmbedding, (paper.id, PROFILE.key))
    assert row is not None
    assert row.input_strategy == InputStrategy.TITLE_ONLY.value
    assert stats.strategy_counts == {InputStrategy.TITLE_ONLY.value: 1}


def test_an_unembedded_paper_is_detected_and_then_is_not(session):
    make_paper(session, "Graph neural networks for molecules", abstract=ABSTRACT)
    assert service.count_pending(session, PROFILE.key) == 1

    embed_all(session, CountingBackend())
    session.commit()

    assert service.count_pending(session, PROFILE.key) == 0


# --------------------------------------------------------------- idempotency


def test_re_running_performs_no_inference(session):
    make_paper(session, "Retrieval augmented generation", abstract=ABSTRACT)
    make_paper(session, "Efficient transformer inference")
    first = CountingBackend()
    embed_all(session, first)
    session.commit()
    assert first.documents_encoded == 2

    second = CountingBackend()
    stats = embed_all(session, second)
    session.commit()

    assert second.documents_encoded == 0
    assert stats.embedded == 0
    assert len(session.execute(select(PaperEmbedding)).scalars().all()) == 2


def test_an_update_that_does_not_change_the_text_is_dismissed_without_inference(session):
    paper = make_paper(session, "Alzheimer disease genetics", abstract=ABSTRACT)
    embed_all(session, CountingBackend())
    session.commit()

    # A citation count refresh touches the row but not the embedded text.
    paper.citation_count = 42
    session.commit()
    assert service.count_pending(session, PROFILE.key) == 1

    backend = CountingBackend()
    stats = service.embed_papers(session, [paper.id], profile=PROFILE, backend=backend)
    session.commit()

    assert backend.documents_encoded == 0
    assert stats.skipped_unchanged == 1
    # And the paper stops queueing, rather than reappearing on every pass.
    assert service.count_pending(session, PROFILE.key) == 0


def test_gaining_an_abstract_forces_a_re_embed(session):
    paper = make_paper(session, "Public health diabetes risk prediction")
    embed_all(session, CountingBackend())
    session.commit()
    original_hash = session.get(PaperEmbedding, (paper.id, PROFILE.key)).input_text_hash

    paper.abstract = ABSTRACT
    session.commit()

    backend = CountingBackend()
    stats = service.embed_papers(session, [paper.id], profile=PROFILE, backend=backend)
    session.commit()

    row = session.get(PaperEmbedding, (paper.id, PROFILE.key))
    assert backend.documents_encoded == 1
    assert stats.embedded == 1
    assert row.input_text_hash != original_hash
    assert row.input_strategy == InputStrategy.TITLE_ABSTRACT.value


# ---------------------------------------------------------------- versioning


def test_a_second_profile_stores_its_own_vector_for_the_same_paper(session):
    paper = make_paper(session, "Reinforcement learning robotics", abstract=ABSTRACT)

    service.embed_papers(session, [paper.id], profile=PROFILE, backend=HashingBackend())
    service.embed_papers(
        session, [paper.id], profile=TITLE_ONLY_PROFILE, backend=HashingBackend()
    )
    session.commit()

    rows = {
        row.model_key: row
        for row in session.execute(
            select(PaperEmbedding).where(PaperEmbedding.paper_id == paper.id)
        ).scalars()
    }
    assert set(rows) == {PROFILE.key, TITLE_ONLY_PROFILE.key}
    assert rows[PROFILE.key].input_text_hash != rows[TITLE_ONLY_PROFILE.key].input_text_hash
    assert rows[TITLE_ONLY_PROFILE.key].input_strategy == InputStrategy.TITLE_ONLY.value


def test_pending_work_is_tracked_per_profile(session):
    make_paper(session, "Only embedded under one profile", abstract=ABSTRACT)
    embed_all(session, HashingBackend(), profile=PROFILE)
    session.commit()

    assert service.count_pending(session, PROFILE.key) == 0
    assert service.count_pending(session, TITLE_ONLY_PROFILE.key) == 1


# --------------------------------------------------------------------- jobs


def test_enqueue_creates_jobs_covering_every_pending_paper(session):
    for index in range(5):
        make_paper(session, f"Paper number {index}", abstract=ABSTRACT)
    session.flush()

    jobs, papers = embed_jobs.enqueue_pending(session, PROFILE, batch_size=2)
    session.commit()

    assert papers == 5
    assert jobs == 3
    queued = session.execute(select(Job).where(Job.kind == embed_jobs.JOB_KIND)).scalars().all()
    assert len(queued) == 3


def test_enqueueing_twice_does_not_duplicate_identical_batches(session):
    for index in range(4):
        make_paper(session, f"Duplicate check {index}", abstract=ABSTRACT)
    session.flush()

    embed_jobs.enqueue_pending(session, PROFILE, batch_size=2)
    session.commit()
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=2)
    session.commit()

    queued = session.execute(select(Job).where(Job.kind == embed_jobs.JOB_KIND)).scalars().all()
    assert len(queued) == 2


def test_a_job_for_another_model_is_refused_rather_than_silently_mixed(session):
    paper = make_paper(session, "Wrong model key", abstract=ABSTRACT)
    job = queue.enqueue(
        session,
        embed_jobs.JOB_KIND,
        {"model_key": "some-other-model@v9", "paper_ids": [str(paper.id)]},
    )
    session.flush()

    with pytest.raises(ValueError, match="some-other-model@v9"):
        embed_jobs.handle(session, job, profile=PROFILE, backend=HashingBackend())


def test_running_a_job_twice_does_no_second_encode(session):
    paper = make_paper(session, "Idempotent job", abstract=ABSTRACT)
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=10)
    session.commit()
    job = session.execute(select(Job).where(Job.kind == embed_jobs.JOB_KIND)).scalars().one()

    first = CountingBackend()
    embed_jobs.handle(session, job, profile=PROFILE, backend=first)
    session.commit()
    second = CountingBackend()
    stats = embed_jobs.handle(session, job, profile=PROFILE, backend=second)
    session.commit()

    assert first.documents_encoded == 1
    assert second.documents_encoded == 0
    assert stats.skipped_unchanged == 1
    assert session.get(PaperEmbedding, (paper.id, PROFILE.key)) is not None


# ------------------------------------------------------------- crash safety


def test_a_job_abandoned_by_a_dead_worker_is_returned_to_the_queue(session):
    make_paper(session, "Crashed worker", abstract=ABSTRACT)
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=10)
    session.commit()

    claimed = queue.claim(session, limit=1)[0]
    session.commit()
    assert claimed.status == JobStatus.RUNNING.value

    # Simulate the worker dying: the row keeps its lock and nobody reports back.
    claimed.locked_at = utcnow() - timedelta(hours=2)
    session.commit()

    reaped = queue.reap_stale(session, older_than=timedelta(minutes=30))
    session.commit()

    assert reaped == 1
    assert session.get(Job, claimed.id).status == JobStatus.PENDING.value
    assert queue.claim(session, limit=1)


def test_a_job_that_keeps_killing_its_worker_ends_in_an_explicit_failed_state(session):
    make_paper(session, "Poison job", abstract=ABSTRACT)
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=10)
    session.commit()
    job = session.execute(select(Job).where(Job.kind == embed_jobs.JOB_KIND)).scalars().one()

    job.attempts = job.max_attempts
    job.status = JobStatus.RUNNING.value
    job.locked_at = utcnow() - timedelta(hours=2)
    session.commit()

    queue.reap_stale(session, older_than=timedelta(minutes=30))
    session.commit()

    reaped = session.get(Job, job.id)
    assert reaped.status == JobStatus.FAILED.value
    assert "stale-job timeout" in reaped.last_error


def test_a_healthy_running_job_is_not_reaped(session):
    make_paper(session, "Still working", abstract=ABSTRACT)
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=10)
    session.commit()
    claimed = queue.claim(session, limit=1)[0]
    session.commit()

    assert queue.reap_stale(session, older_than=timedelta(minutes=30)) == 0
    assert session.get(Job, claimed.id).status == JobStatus.RUNNING.value


def test_vectors_committed_before_a_crash_survive_it(session):
    """Ingestion and earlier batches must not be rolled back by a later failure."""
    done = make_paper(session, "Already embedded", abstract=ABSTRACT)
    service.embed_papers(session, [done.id], profile=PROFILE, backend=HashingBackend())
    session.commit()

    class ExplodingBackend(CountingBackend):
        def encode_documents(self, texts):
            raise RuntimeError("out of memory")

    pending = make_paper(session, "Never embedded", abstract=ABSTRACT)
    session.commit()

    with pytest.raises(RuntimeError, match="out of memory"):
        service.embed_papers(session, [pending.id], profile=PROFILE, backend=ExplodingBackend())
    session.rollback()

    assert session.get(PaperEmbedding, (done.id, PROFILE.key)) is not None
    assert session.get(PaperEmbedding, (pending.id, PROFILE.key)) is None
    # The paper is still ingested and still queued for a later attempt.
    assert service.count_pending(session, PROFILE.key) == 1


# --------------------------------------------------------- metrics endpoint


def _client():
    from fastapi.testclient import TestClient

    from academious.api.main import app

    return TestClient(app)


def test_embedding_metrics_report_coverage_per_model(session):
    make_paper(session, "Embedded paper", abstract=ABSTRACT)
    make_paper(session, "Unembedded paper", abstract=ABSTRACT)
    session.commit()
    first = service.select_pending_paper_ids(session, PROFILE.key, limit=1)
    service.embed_papers(session, first, profile=PROFILE, backend=HashingBackend())
    session.commit()

    payload = _client().get("/metrics/embeddings").json()

    assert payload["papers"] == 2
    by_key = {entry["model_key"]: entry for entry in payload["models"]}
    assert by_key[PROFILE.key]["vectors"] == 1
    assert by_key[PROFILE.key]["pending"] == 1
    assert by_key[PROFILE.key]["coverage"] == 0.5


def test_embedding_metrics_name_the_active_profile_even_with_no_vectors(session):
    make_paper(session, "Nothing embedded yet", abstract=ABSTRACT)
    session.commit()

    payload = _client().get("/metrics/embeddings").json()

    active = payload["active_profile"]
    entry = next(e for e in payload["models"] if e["model_key"] == active)
    assert entry["vectors"] == 0
    assert entry["pending"] == 1


def test_embedding_metrics_count_the_title_only_fallback(session):
    make_paper(session, "A title with no abstract at all")
    session.commit()
    embed_all(session, HashingBackend())
    session.commit()

    payload = _client().get("/metrics/embeddings").json()
    entry = next(e for e in payload["models"] if e["model_key"] == PROFILE.key)
    assert entry["title_only"] == 1


def test_embedding_metrics_report_queue_state(session):
    make_paper(session, "Queued but not drained", abstract=ABSTRACT)
    embed_jobs.enqueue_pending(session, PROFILE, batch_size=10)
    session.commit()

    payload = _client().get("/metrics/embeddings").json()
    assert payload["jobs"].get("pending") == 1
