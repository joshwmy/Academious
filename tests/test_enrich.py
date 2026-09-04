"""Enrichment: batching DOIs into OpenAlex lookups, and folding the answers in.

Two tiers, as everywhere else in this suite. The batching half is pure and runs
anywhere; the half that proves a Europe PMC paper actually gains a field is
marked `db`, because "did the merge derive a field" is a question about a row.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from academious.core.config import Settings
from academious.core.ids import IdType
from academious.sources.base import RawRecord
from academious.sources.openalex.client import (
    MAX_OR_VALUES,
    OpenAlexClient,
    _batched,
    is_filterable_doi,
)
from tests.conftest import load_json
from tests.factories import WHEN

INTEGRON_DOI = "10.1038/s41564-023-01548-y"


class StubLookupClient:
    """Answers `fetch_by_doi` from a DOI-keyed table, and records what was asked.

    Deliberately batches the way the real client does, so a test can assert on
    request *count* - which is the whole point of the OR filter - rather than
    only on the records that came back.
    """

    def __init__(self, works: dict[str, dict]) -> None:
        self._works = works
        self.batches: list[list[str]] = []

    def fetch_by_doi(self, dois: Iterable[str]) -> Iterator[RawRecord]:
        for batch in _batched(dois, MAX_OR_VALUES):
            self.batches.append(batch)
            for doi in batch:
                work = self._works.get(doi)
                if work is not None:
                    yield RawRecord("openalex", str(work["id"]), work, WHEN)

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


# --- batching ----------------------------------------------------------------


def test_batches_are_capped_at_the_or_limit():
    dois = [f"10.1000/{n}" for n in range(125)]
    batches = list(_batched(dois, MAX_OR_VALUES))

    assert [len(batch) for batch in batches] == [50, 50, 25]
    assert [doi for batch in batches for doi in batch] == dois


def test_a_repeated_doi_does_not_spend_a_slot():
    """Two papers can carry one DOI: dedup keeps conflicting records apart."""
    assert list(_batched(["10.1/a", "10.1/b", "10.1/a"], MAX_OR_VALUES)) == [["10.1/a", "10.1/b"]]


def test_a_doi_containing_a_filter_delimiter_is_refused():
    """`|` separates OR values and `,` separates filter keys.

    Sending one inside a value does not error - it silently rewrites the query
    into a different, well-formed one - so such a DOI must never be sent.
    """
    assert is_filterable_doi("10.1000/plain") is True
    assert is_filterable_doi("10.1000/a|b") is False
    assert is_filterable_doi("10.1000/a,b") is False
    assert list(_batched(["10.1000/a|b", "10.1000/ok"], MAX_OR_VALUES)) == [["10.1000/ok"]]


def test_lookup_asks_for_doi_urls_and_carries_the_key():
    client = OpenAlexClient(settings=Settings(openalex_api_key="secret"))
    params = client.lookup_params(["10.1/a", "10.1/b"])

    assert params["filter"] == "doi:https://doi.org/10.1/a|https://doi.org/10.1/b"
    assert params["api_key"] == "secret"
    # A lookup is not a window: at most 50 works can match, so there is nothing
    # to page through and no ordering worth making the API honour.
    assert "cursor" not in params
    assert "sort" not in params


# --- enrichment --------------------------------------------------------------


@pytest.mark.db
def test_a_paper_with_no_topics_gains_a_field(session):
    """The point of the exercise: a paper reaches a field it never carried.

    Europe PMC assigns MeSH only once MEDLINE has indexed the record, months
    after the paper arrives, so this paper is classified by nothing at all
    until something asks a source that classifies on publication.
    """
    from academious.db.models.paper import PaperIdentifier
    from academious.ingest.enrich import count_candidates, enrich_missing_fields

    paper = _europepmc_paper(session, doi=INTEGRON_DOI)
    assert paper.fields == []
    assert count_candidates(session) == 1

    client = StubLookupClient({INTEGRON_DOI: _work()})
    report = enrich_missing_fields(session, apply=True, client=client)

    session.refresh(paper)
    assert paper.fields == ["biochemistry-genetics-and-molecular-biology"]
    assert report.gained_fields == 1
    assert report.returned == 1
    assert report.still_without_fields == 0
    assert client.batches == [[INTEGRON_DOI]]
    # Merged onto the paper already held, rather than founding a second one.
    owner = session.get(PaperIdentifier, (IdType.DOI.value, INTEGRON_DOI))
    assert owner is not None and owner.paper_id == paper.id


@pytest.mark.db
def test_a_dry_run_asks_but_writes_nothing(session):
    from academious.ingest.enrich import enrich_missing_fields

    paper = _europepmc_paper(session, doi=INTEGRON_DOI)
    client = StubLookupClient({INTEGRON_DOI: _work()})

    report = enrich_missing_fields(session, apply=False, client=client)

    assert report.gained_fields == 1, "a dry run still reports what it would do"
    assert client.batches, "and it has to ask upstream in order to know"
    session.refresh(paper)
    assert paper.fields == []


@pytest.mark.db
def test_a_doi_openalex_does_not_index_is_counted_not_lost(session):
    from academious.ingest.enrich import enrich_missing_fields

    _europepmc_paper(session, doi="10.9999/unknown")

    report = enrich_missing_fields(session, apply=True, client=StubLookupClient({}))

    assert report.requested == 1
    assert report.returned == 0
    assert report.unmatched == 1
    assert report.still_without_fields == 1
    assert report.gained_fields == 0


@pytest.mark.db
def test_a_paper_already_asked_about_is_not_asked_again(session):
    """The exclusion that makes a repeated run incremental rather than a re-scan.

    A work OpenAlex holds without topics would otherwise cost a request on
    every future pass, for an answer already known not to help.
    """
    from academious.ingest.enrich import count_candidates, enrich_missing_fields

    _europepmc_paper(session, doi=INTEGRON_DOI)
    client = StubLookupClient({INTEGRON_DOI: _work(topics=[])})

    first = enrich_missing_fields(session, apply=True, client=client)
    assert first.requested == 1
    assert first.still_without_fields == 1

    assert count_candidates(session) == 0
    second = enrich_missing_fields(session, apply=True, client=StubLookupClient({}))
    assert second.candidates == 0

    # ... unless told to ignore the exclusion, which is what --recheck is for.
    assert count_candidates(session, recheck=True) == 1


@pytest.mark.db
def test_enriching_a_paper_does_not_found_a_second_one(session):
    """The pass classifies the corpus; it must not quietly grow it.

    Not prevented, only counted - `EnrichmentReport.founded` says why - so this
    is the test that would notice if it started happening.
    """
    from sqlalchemy import func, select

    from academious.db.models.paper import Paper
    from academious.ingest.enrich import enrich_missing_fields

    _europepmc_paper(session, doi=INTEGRON_DOI)
    before = session.scalar(select(func.count()).select_from(Paper))

    report = enrich_missing_fields(
        session, apply=True, client=StubLookupClient({INTEGRON_DOI: _work()})
    )

    assert report.founded == 0
    assert session.scalar(select(func.count()).select_from(Paper)) == before


@pytest.mark.db
def test_a_paper_that_already_has_a_field_is_never_a_candidate(session):
    from academious.ingest.enrich import count_candidates

    _europepmc_paper(
        session,
        doi="10.1234/classified",
        topics=[{"scheme": "arxiv", "id": "cs.LG", "label": "cs.LG"}],
    )

    assert count_candidates(session) == 0


@pytest.mark.db
def test_a_paper_with_no_doi_is_never_a_candidate(session):
    """There is nothing to look it up by."""
    from academious.ingest.enrich import count_candidates

    _europepmc_paper(session, doi=None)

    assert count_candidates(session) == 0


def _work(**overrides) -> dict:
    return load_json("openalex", "work_published_integron.json") | overrides


def _europepmc_paper(session, *, doi: str | None, topics=()):
    """A paper as Europe PMC leaves it: no field, and a DOI to find it again by.

    Committed rather than flushed, because a dry-run pass rolls back and would
    otherwise take the test's own fixture with it.
    """
    from academious.db.models.paper import PaperIdentifier
    from tests.factories import make_paper

    paper = make_paper(
        session,
        "Integron activity accelerates the evolution of antibiotic resistance",
        abstract="Integrons are genetic elements.",
        topics=topics,
        doi=doi,
    )
    if doi is not None:
        session.add(
            PaperIdentifier(
                id_type=IdType.DOI.value, value=doi, paper_id=paper.id, source_key="europepmc"
            )
        )
    session.commit()
    return paper
