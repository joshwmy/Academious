"""OpenAlex normalisation, checked against payloads captured from the live API."""

from __future__ import annotations

from datetime import UTC, datetime

from academious.core.ids import IdType
from academious.sources.base import RawRecord
from academious.sources.openalex.normalise import normalise, reconstruct_abstract
from tests.conftest import load_json


def as_record(name: str) -> RawRecord:
    work = load_json("openalex", f"{name}.json")
    return RawRecord("openalex", work["id"], work, datetime(2026, 8, 28, tzinfo=UTC))


def test_reconstruct_abstract_restores_word_order():
    inverted = {"Integrons": [0], "are": [1], "genetic": [2], "elements": [3]}
    assert reconstruct_abstract(inverted) == "Integrons are genetic elements"


def test_reconstruct_abstract_of_missing_index_is_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_preprint_record_is_flagged_and_keeps_its_own_doi():
    candidate = normalise(as_record("work_preprint_integron"))
    assert candidate is not None
    assert candidate.is_preprint is True
    assert candidate.primary_doi == "10.1101/2022.09.11.507474"
    assert candidate.abstract and "Integrons" in candidate.abstract


def test_published_record_has_pmid_and_is_peer_reviewed():
    candidate = normalise(as_record("work_published_integron"))
    assert candidate is not None
    assert candidate.is_preprint is False
    assert candidate.is_peer_reviewed is True
    assert candidate.identifier_values(IdType.PMID) == ["38172619"]
    assert candidate.venue and candidate.venue.name == "Nature Microbiology"


def test_published_record_has_no_abstract_so_abstract_cannot_be_required():
    """Verified against live data: OpenAlex often omits abstracts for journal articles."""
    candidate = normalise(as_record("work_published_integron"))
    assert candidate is not None
    assert candidate.abstract is None


def test_preprint_and_published_versions_do_not_share_a_title():
    """Why title matching can never link a preprint to its published version."""
    preprint = normalise(as_record("work_preprint_integron"))
    published = normalise(as_record("work_published_integron"))
    assert preprint is not None and published is not None
    assert preprint.title != published.title
    assert preprint.primary_doi != published.primary_doi


def test_retraction_flag_is_read_from_the_work():
    candidate = normalise(as_record("work_retracted_lancet"))
    assert candidate is not None
    assert candidate.is_retracted_hint is True


def test_open_access_locations_are_captured_with_versions():
    candidate = normalise(as_record("work_retracted_lancet"))
    assert candidate is not None
    assert candidate.locations
    assert any(location.is_best for location in candidate.locations)
    assert all(location.url for location in candidate.locations)


def test_record_without_identifiers_is_skipped():
    raw = RawRecord("openalex", "x", {"title": "No ids here"}, datetime(2026, 1, 1, tzinfo=UTC))
    assert normalise(raw) is None


def test_paratext_is_skipped():
    work = load_json("openalex", "work_published_integron.json") | {"is_paratext": True}
    raw = RawRecord("openalex", work["id"], work, datetime(2026, 1, 1, tzinfo=UTC))
    assert normalise(raw) is None


def test_incremental_window_uses_the_configured_date_field() -> None:
    """OpenAlex put `updated_date` behind a paid plan.

    A free-tier request for it comes back 429 with a "Plan upgrade required"
    body, which every layer above reads as a rate limit and retries five times.
    The field is configurable so the downgrade is a setting rather than a
    rewrite, and the sort has to follow the filter: a cursor walking one
    ordering while the window bounds another can skip records silently.
    """
    from datetime import date

    from academious.core.config import Settings
    from academious.sources.openalex.client import OpenAlexClient

    free = OpenAlexClient(settings=Settings(openalex_incremental_field="publication_date"))
    params = free._params("primary_topic.domain.id:1", date(2026, 8, 25), "*")
    assert "from_publication_date:2026-08-25" in params["filter"]
    assert params["sort"] == "publication_date:asc"

    paid = OpenAlexClient(settings=Settings(openalex_incremental_field="updated_date"))
    params = paid._params("primary_topic.domain.id:1", date(2026, 8, 25), "*")
    assert "from_updated_date:2026-08-25" in params["filter"]
    assert params["sort"] == "updated_date:asc"
