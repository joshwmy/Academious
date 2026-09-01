"""Phase 1 acceptance criteria, exercised against real PostgreSQL.

Marked `db` and skipped when no database is configured, so a bare `pytest` on a
fresh checkout is still green. Fuzzy deduplication is SQL (pg_trgm), so it
cannot be honestly tested any other way.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from academious.core.config import get_settings
from academious.db.models.ops import RunStatus
from academious.db.models.paper import Paper, PaperRelation, RelationType
from academious.db.models.support import OaLocation, SourceRecord
from academious.ingest.pipeline import IngestPipeline
from academious.ingest.scope import WorkType
from academious.sources.arxiv.normalise import normalise as normalise_arxiv
from academious.sources.biorxiv.normalise import normalise as normalise_biorxiv
from academious.sources.europepmc.normalise import normalise as normalise_europepmc
from academious.sources.openalex.normalise import normalise as normalise_openalex
from tests.conftest import load_json, load_text
from tests.factories import StubConnector, raw

pytestmark = pytest.mark.db


def openalex_raw(name: str):
    work = load_json("openalex", f"{name}.json")
    return raw("openalex", work["id"], work)


def europepmc_raw(overrides: dict | None = None):
    result = load_json("europepmc", "preprint_biorxiv.json") | (overrides or {})
    return raw("europepmc", f"{result['source']}:{result['id']}", result)


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


def test_europepmc_enriches_a_biorxiv_preprint_rather_than_duplicating_it(session):
    """The shape the first live harvest produced: same DOI, two sources, one paper.

    Europe PMC indexes bioRxiv and medRxiv preprints under the same DOI the
    preprint server issues, so the identifier path has to recognise them. A
    second paper row here would show the reader the same preprint twice.
    """
    preprint_doi = "10.64898/2026.08.11.744224"
    biorxiv_payload = {
        "doi": preprint_doi,
        "version": "1",
        "server": "biorxiv",
        "title": "Photometallobiocatalytic Asymmetric Radical-Mediated Cross-Coupling",
        "authors": "Wang, H.; Yang, Y.",
        "date": "2026-08-11",
        "license": "cc_by_nc_nd",
        "abstract": "Short server abstract.",
    }
    run_pipeline(
        session,
        StubConnector(
            "biorxiv", [[raw("biorxiv", f"{preprint_doi}v1", biorxiv_payload)]], normalise_biorxiv
        ),
    )
    assert count(session, Paper) == 1

    run_pipeline(
        session, StubConnector("europepmc", [[europepmc_raw()]], normalise_europepmc)
    )

    assert count(session, Paper) == 1
    paper = session.execute(select(Paper)).scalars().one()
    assert paper.canonical_doi == preprint_doi
    assert paper.is_preprint is True
    assert paper.is_peer_reviewed is False
    # Europe PMC outranks bioRxiv for the abstract, and both locations survive.
    assert paper.abstract_source == "europepmc"
    assert {location.discovered_via for location in paper.oa_locations} == {
        "biorxiv",
        "europepmc",
    }
    assert {(record.source_key) for record in session.execute(
        select(SourceRecord)).scalars().all()} == {"biorxiv", "europepmc"}


def test_europepmc_records_without_a_doi_still_reconcile_on_pmid(session):
    """Two thirds of the first live harvest had no DOI; MED records carry a PMID.

    Without this the identifier path would fall through to the fuzzy matcher for
    the majority of Europe PMC records, which is a far weaker guarantee.
    """
    no_doi = {
        "doi": None,
        "pmid": "40000001",
        "pmcid": None,
        "source": "MED",
        "id": "40000001",
        "pubTypeList": {"pubType": ["Journal Article"]},
    }
    first = europepmc_raw(no_doi)
    run_pipeline(session, StubConnector("europepmc", [[first]], normalise_europepmc))
    assert count(session, Paper) == 1

    # The same record seen again under a different Europe PMC database id.
    again = europepmc_raw(no_doi | {"source": "PMC", "id": "PMC9999999", "pmcid": "PMC9999999"})
    run_pipeline(session, StubConnector("europepmc", [[again]], normalise_europepmc))

    assert count(session, Paper) == 1
    paper = session.execute(select(Paper)).scalars().one()
    identifiers = {(i.id_type, i.value) for i in paper.identifiers}
    assert ("pmid", "40000001") in identifiers
    assert ("pmcid", "PMC9999999") in identifiers


def test_a_reference_chapter_never_reaches_the_corpus(session):
    """Bookshelf chapters are refused, whatever else the record looks like."""
    connector = StubConnector(
        "europepmc", [[europepmc_raw()]], normalise_europepmc
    )
    chapter = load_json("europepmc", "chapter_statpearls.json")
    run = run_pipeline(
        session,
        StubConnector(
            "europepmc",
            [[raw("europepmc", f"MED:{chapter['id']}", chapter)]],
            normalise_europepmc,
        ),
    )
    assert run.records_fetched == 1
    assert run.records_skipped == 1
    assert count(session, Paper) == 0
    # The payload is still stored, so a re-run is a hash-skip rather than a refetch.
    assert count(session, SourceRecord) == 1

    # A preprint through the same connector still lands.
    run_pipeline(session, connector)
    assert count(session, Paper) == 1


def test_the_admission_policy_is_enforced_for_any_source_not_only_europe_pmc(session):
    """A connector that forgets to apply the policy cannot widen the corpus.

    This is what a future PubMed connector inherits: the type vocabulary is
    shared, and the pipeline refuses tertiary material regardless of which
    source produced it.
    """

    def normalise_reference_entry(record):
        candidate = normalise_openalex(record)
        if candidate is not None:
            candidate.work_type = WorkType.REFERENCE_ENTRY
        return candidate

    run = run_pipeline(
        session,
        StubConnector(
            "some_new_source",
            [[openalex_raw("work_published_integron")]],
            normalise_reference_entry,
        ),
    )
    assert run.records_skipped == 1
    assert count(session, Paper) == 0


def test_an_unknown_work_type_from_a_new_source_is_still_admitted(session):
    """The conservative fallback, enforced end to end."""

    def normalise_unknown(record):
        candidate = normalise_openalex(record)
        if candidate is not None:
            candidate.work_type = "some-new-crossref-type"
        return candidate

    run = run_pipeline(
        session,
        StubConnector(
            "some_new_source", [[openalex_raw("work_published_integron")]], normalise_unknown
        ),
    )
    assert run.papers_created == 1
    assert count(session, Paper) == 1
