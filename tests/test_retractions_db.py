"""Applying Retraction Watch notices to ingested papers."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from academious.core.config import get_settings
from academious.db.models.paper import Paper, RetractionStatus
from academious.db.models.support import RetractionRecord
from academious.ingest import retractions
from academious.ingest.pipeline import IngestPipeline
from academious.sources.openalex.normalise import normalise as normalise_openalex
from academious.sources.retractionwatch.client import parse_csv
from tests.conftest import load_json, load_text
from tests.factories import StubConnector, raw

pytestmark = pytest.mark.db


def ingest_lancet(session):
    work = load_json("openalex", "work_retracted_lancet.json")
    connector = StubConnector(
        "openalex", [[raw("openalex", work["id"], work)]], normalise_openalex
    )
    IngestPipeline(get_settings()).run(session, connector, since=None)
    session.flush()


def import_sample(session):
    notices = list(parse_csv(load_text("retractionwatch", "sample.csv")))
    created, updated = retractions.import_notices(session, notices)
    session.flush()
    return created, updated


def test_notices_are_imported_once_and_then_updated(session):
    created, updated = import_sample(session)
    assert created > 0 and updated == 0

    created_again, updated_again = import_sample(session)
    assert created_again == 0
    assert updated_again > 0


def test_the_worst_notice_wins_for_a_paper_with_several(session):
    """The Lancet paper carries a correction, an expression of concern and a retraction."""
    ingest_lancet(session)
    import_sample(session)

    changed = retractions.apply_to_papers(session)
    session.flush()

    paper = session.execute(select(Paper)).scalars().one()
    assert changed == 1
    assert paper.retraction_status == RetractionStatus.RETRACTED.value
    assert paper.retraction_checked_at is not None


def test_applying_retractions_twice_changes_nothing_the_second_time(session):
    ingest_lancet(session)
    import_sample(session)

    assert retractions.apply_to_papers(session) == 1
    session.flush()
    assert retractions.apply_to_papers(session) == 0


def test_notices_for_papers_we_have_not_ingested_are_stored_but_applied_to_nothing(session):
    import_sample(session)
    assert retractions.apply_to_papers(session) == 0
    assert session.execute(select(RetractionRecord)).scalars().all()


def test_a_clean_paper_keeps_status_none(session):
    work = load_json("openalex", "work_published_integron.json")
    connector = StubConnector(
        "openalex", [[raw("openalex", work["id"], work)]], normalise_openalex
    )
    IngestPipeline(get_settings()).run(session, connector, since=None)
    import_sample(session)
    retractions.apply_to_papers(session)
    session.flush()

    paper = session.execute(
        select(Paper).where(Paper.canonical_doi == "10.1038/s41564-023-01548-y")
    ).scalars().one()
    assert paper.retraction_status == RetractionStatus.NONE.value
