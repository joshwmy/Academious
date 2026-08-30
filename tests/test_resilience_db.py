"""Surviving source failures, and the job queue that carries retries."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from academious.core.clock import utcnow
from academious.core.config import get_settings
from academious.db.models.ops import Job, JobStatus, RunStatus
from academious.db.models.paper import Paper
from academious.ingest.pipeline import IngestPipeline, load_cursor
from academious.jobs import queue
from academious.sources.openalex.normalise import normalise as normalise_openalex
from tests.conftest import load_json
from tests.factories import StubConnector, raw

pytestmark = pytest.mark.db


def openalex_raw(name: str):
    work = load_json("openalex", f"{name}.json")
    return raw("openalex", work["id"], work)


def test_a_source_outage_keeps_the_records_already_ingested(session):
    connector = StubConnector(
        "openalex",
        [[openalex_raw("work_published_integron")], [openalex_raw("work_retracted_lancet")]],
        normalise_openalex,
        fail_after_pages=1,
        cursors=["cursor-1", "cursor-2"],
    )
    run = IngestPipeline(get_settings()).run(session, connector, since=None)

    assert run.status == RunStatus.FAILED.value
    assert run.errors == 1
    assert run.papers_created == 1
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 1
    assert run.detail["error_samples"]


def test_a_failed_run_does_not_advance_the_stored_cursor(session):
    """So the next run retries the same window instead of skipping it."""
    connector = StubConnector(
        "openalex",
        [[openalex_raw("work_published_integron")]],
        normalise_openalex,
        fail_after_pages=0,
    )
    IngestPipeline(get_settings()).run(session, connector, since=None)
    session.flush()
    assert load_cursor(session, "openalex") is None


def test_a_successful_run_stores_its_cursor_for_resumption(session):
    connector = StubConnector(
        "openalex",
        [[openalex_raw("work_published_integron")]],
        normalise_openalex,
        cursors=["cursor-abc"],
    )
    IngestPipeline(get_settings()).run(session, connector, since=None)
    session.flush()
    assert load_cursor(session, "openalex") == "cursor-abc"


def test_one_unparseable_record_does_not_abort_the_run(session):
    def explode(record):
        if record.source_id == "bad":
            raise ValueError("malformed payload")
        return normalise_openalex(record)

    connector = StubConnector(
        "openalex",
        [[raw("openalex", "bad", {"id": "bad"}), openalex_raw("work_published_integron")]],
        explode,
    )
    run = IngestPipeline(get_settings()).run(session, connector, since=None)

    assert run.status == RunStatus.PARTIAL.value
    assert run.errors == 1
    assert run.papers_created == 1


def test_max_records_caps_a_run(session):
    connector = StubConnector(
        "openalex",
        [[openalex_raw("work_published_integron")], [openalex_raw("work_retracted_lancet")]],
        normalise_openalex,
    )
    run = IngestPipeline(get_settings()).run(session, connector, since=None, max_records=1)
    assert run.records_fetched == 1


def test_jobs_are_claimed_once_and_only_once(session):
    queue.enqueue(session, "harvest", {"source": "openalex"})
    queue.enqueue(session, "harvest", {"source": "arxiv"})
    session.flush()

    first = queue.claim(session, limit=1)
    second = queue.claim(session, limit=5)

    assert len(first) == 1
    assert len(second) == 1
    assert {job.id for job in first}.isdisjoint({job.id for job in second})
    assert all(job.status == JobStatus.RUNNING.value for job in first + second)


def test_a_dedup_key_prevents_duplicate_pending_jobs(session):
    assert queue.enqueue(session, "harvest", dedup_key="harvest:openalex") is not None
    assert queue.enqueue(session, "harvest", dedup_key="harvest:openalex") is None
    session.flush()
    assert session.execute(select(func.count()).select_from(Job)).scalar_one() == 1


def test_the_same_work_can_be_queued_again_once_the_previous_job_finished(session):
    """A dedup key reserves work in flight, not for ever.

    `enqueue` deliberately only suppresses a duplicate while the existing job is
    pending or running - work that legitimately recurs (the same batch of papers
    becoming stale again, a re-embed pass after a migration) must be queueable
    once the previous attempt is done. The unique constraint on `dedup_key` did
    not agree with that, so the permitted path raised IntegrityError instead of
    queueing, and the worker died on it.
    """
    first = queue.enqueue(session, "harvest", dedup_key="harvest:openalex")
    assert first is not None
    session.flush()
    queue.claim(session, limit=1)
    queue.complete(session, first)
    session.flush()
    assert first.status == JobStatus.SUCCEEDED.value

    second = queue.enqueue(session, "harvest", dedup_key="harvest:openalex")
    session.flush()

    assert second is not None, "finished work must be queueable again"
    assert second.status == JobStatus.PENDING.value
    assert session.execute(select(func.count()).select_from(Job)).scalar_one() == 1, (
        "and it must not violate the unique constraint by inserting a second row"
    )


def test_work_that_exhausted_its_attempts_can_be_queued_again(session):
    job = queue.enqueue(session, "harvest", dedup_key="harvest:arxiv", max_attempts=1)
    session.flush()
    queue.claim(session, limit=1)
    queue.fail(session, job, "boom")
    session.flush()
    assert job.status == JobStatus.FAILED.value

    again = queue.enqueue(session, "harvest", dedup_key="harvest:arxiv")
    session.flush()
    assert again is not None
    assert again.status == JobStatus.PENDING.value
    assert again.attempts == 0, "a re-queue is a fresh attempt, not a continuation"
    assert again.last_error is None


def test_a_failed_job_is_retried_with_backoff_then_gives_up(session):
    job = queue.enqueue(session, "harvest", max_attempts=2)
    session.flush()

    queue.claim(session, limit=1)
    queue.fail(session, job, "boom")
    assert job.status == JobStatus.PENDING.value
    assert job.run_after > utcnow()

    job.run_after = utcnow() - timedelta(seconds=1)
    session.flush()
    queue.claim(session, limit=1)
    queue.fail(session, job, "boom again")
    assert job.status == JobStatus.FAILED.value
    assert job.last_error == "boom again"


def test_jobs_scheduled_for_later_are_not_claimed_yet(session):
    queue.enqueue(session, "harvest", delay=timedelta(hours=1))
    session.flush()
    assert queue.claim(session, limit=5) == []
