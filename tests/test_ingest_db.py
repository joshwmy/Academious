"""Phase 1 acceptance criteria, exercised against real PostgreSQL.

Marked `db` and skipped when no database is configured, so a bare `pytest` on a
fresh checkout is still green. Fuzzy deduplication is SQL (pg_trgm), so it
cannot be honestly tested any other way.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from tests.conftest import load_json, load_text
from tests.factories import StubConnector, raw

from academious.core.config import get_settings
from academious.db.models.ops import RunStatus
from academious.db.models.paper import Paper, PaperRelation, RelationType
from academious.db.models.support import OaLocation, SourceRecord
from academious.ingest.pipeline import IngestPipeline
from academious.sources.arxiv.normalise import normalise as normalise_arxiv
from academious.sources.biorxiv.normalise import normalise as normalise_biorxiv
from academious.sources.openalex.normalise import normalise as normalise_openalex

pytestmark = pytest.mark.db


def openalex_raw(name: str):
    work = load_json("openalex", f"{name}.json")
    return raw("openalex", work["id"], work)


def biorxiv_raw():
    payload = load_json("biorxiv", "details_integron.json")["collection"][-1]
    return raw("biorxiv", "10.1101/2022.09.11.507474v2", {**payload, "server": "biorxiv"})


def arxiv_raw():
    from academious.sources.arxiv.client import parse_list_records

    records, _ = parse_list_records(load_text("arxiv", "getrecord_1706.03762.xml"))
    return raw("arxiv", records[0]["id"], records[0])


def run_pipeline(session, connector):
    return IngestPipeline(get_settings()).run(session, connector, since=None)


def count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_ingests_a_paper_from_one_source(session):
    connector = StubConnector(
        "openalex", [[openalex_raw("work_published_integron")]], normalise_openalex
    )
    run = run_pipeline(session, connector)

    assert run.status == RunStatus.SUCCEEDED.value
    assert run.records_fetched == 1
    assert run.papers_created == 1
    paper = session.execute(select(Paper)).scalars().one()
    assert paper.canonical_doi == "10.1038/s41564-023-01548-y"
    assert paper.title.startswith("Integron cassettes integrate")
    assert paper.first_author_surname == "loot"


def test_rerunning_the_same_harvest_is_idempotent(session):
    records = [[openalex_raw("work_published_integron")]]
    first = run_pipeline(session, StubConnector("openalex", records, normalise_openalex))
    second = run_pipeline(session, StubConnector("openalex", records, normalise_openalex))

    assert first.papers_created == 1
    assert second.papers_created == 0
    assert second.records_skipped == 1
    assert count(session, Paper) == 1
    assert count(session, SourceRecord) == 1


def test_same_paper_from_two_sources_becomes_one_canonical_paper(session):
    """OpenAlex and arXiv both describe 'Attention Is All You Need'."""
    arxiv_record = arxiv_raw()
    openalex_payload = {
        "id": "https://openalex.org/W2963403868",
        "title": "Attention Is All You Need",
        "type": "preprint",
        "publication_date": "2017-06-12",
        "authorships": [
            {"author": {"display_name": "Ashish Vaswani", "id": "https://openalex.org/A1"}}
        ],
        "locations": [
            {
                "is_oa": True,
                "landing_page_url": "https://arxiv.org/abs/1706.03762",
                "version": "submittedVersion",
                "source": {"display_name": "arXiv", "type": "repository"},
            }
        ],
        "open_access": {"oa_status": "green"},
    }

    run_pipeline(session, StubConnector("arxiv", [[arxiv_record]], normalise_arxiv))
    run_pipeline(
        session,
        StubConnector("openalex", [[raw("openalex", openalex_payload["id"], openalex_payload)]],
                      normalise_openalex),
    )

    assert count(session, Paper) == 1
    paper = session.execute(select(Paper)).scalars().one()
    identifiers = {(i.id_type, i.value) for i in paper.identifiers}
    assert ("arxiv", "1706.03762") in identifiers
    assert ("openalex", "W2963403868") in identifiers


def test_preprint_and_published_versions_are_never_merged(session):
    """Different DOIs mean different records, even for the same research."""
    connector = StubConnector(
        "openalex",
        [[openalex_raw("work_preprint_integron"), openalex_raw("work_published_integron")]],
        normalise_openalex,
    )
    run_pipeline(session, connector)

    assert count(session, Paper) == 2
    dois = {paper.canonical_doi for paper in session.execute(select(Paper)).scalars()}
    assert dois == {"10.1101/2022.09.11.507474", "10.1038/s41564-023-01548-y"}


def test_preprint_is_linked_to_its_published_version(session):
    run_pipeline(
        session,
        StubConnector("openalex", [[openalex_raw("work_published_integron")]], normalise_openalex),
    )
    run_pipeline(session, StubConnector("biorxiv", [[biorxiv_raw()]], normalise_biorxiv))

    relation = session.execute(select(PaperRelation)).scalars().one()
    assert relation.relation_type == RelationType.PREPRINT_OF.value

    preprint = session.get(Paper, relation.from_paper_id)
    published = session.get(Paper, relation.to_paper_id)
    assert preprint.canonical_doi == "10.1101/2022.09.11.507474"
    assert published.canonical_doi == "10.1038/s41564-023-01548-y"
    assert published.is_preprint is False


def test_open_access_metadata_is_captured_with_a_best_location(session):
    run_pipeline(
        session,
        StubConnector("openalex", [[openalex_raw("work_retracted_lancet")]], normalise_openalex),
    )
    paper = session.execute(select(Paper)).scalars().one()
    locations = session.execute(select(OaLocation)).scalars().all()

    assert paper.oa_status == "bronze"
    assert len(locations) >= 1
    assert sum(1 for location in locations if location.is_best) == 1
    assert paper.best_oa_location_id is not None
    assert paper.fulltext_status == "linked"
