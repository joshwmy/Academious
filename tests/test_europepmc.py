"""Europe PMC normalisation, checked against payloads captured from the live API."""

from __future__ import annotations

from datetime import UTC, date, datetime

from academious.core.ids import IdType
from academious.sources.base import RawRecord
from academious.sources.europepmc.client import build_query, format_cursor, parse_cursor
from academious.sources.europepmc.normalise import map_language, map_licence, normalise
from tests.conftest import load_json

FETCHED_AT = datetime(2026, 8, 28, tzinfo=UTC)


def as_record(name: str) -> RawRecord:
    result = load_json("europepmc", f"{name}.json")
    return RawRecord("europepmc", f"{result['source']}:{result['id']}", result, FETCHED_AT)


def test_open_access_article_carries_every_identifier_it_has():
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    assert candidate.primary_doi == "10.1038/s41586-021-03819-2"
    assert candidate.identifier_values(IdType.PMID) == ["34265844"]
    assert candidate.identifier_values(IdType.PMCID) == ["PMC8371605"]


def test_author_names_prefer_the_full_form_over_the_medline_abbreviation():
    """`fullName` is 'Jumper J'; dedup compares surnames against full names."""
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    first = candidate.authors[0]
    assert first.name == "John Jumper"
    assert first.orcid == "0000-0001-6169-6580"
    assert first.affiliations == ["DeepMind, London, UK. jumper@deepmind.com."]


def test_abstract_markup_is_stripped():
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    assert candidate.abstract is not None
    assert "<sup>" not in candidate.abstract
    assert candidate.abstract.startswith("Proteins are essential to life")


def test_mesh_headings_become_topics_and_major_ones_score():
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    by_label = {topic["label"]: topic for topic in candidate.topics}
    assert by_label["Protein Folding"]["score"] == 1.0
    assert by_label["Proteins"]["score"] is None
    assert {topic["scheme"] for topic in candidate.topics} == {"mesh"}


def test_journal_article_is_peer_reviewed_and_dated_from_first_publication():
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    assert candidate.is_peer_reviewed is True
    assert candidate.is_preprint is False
    assert candidate.work_type == "article"
    assert candidate.published_date == date(2021, 7, 15)
    assert candidate.venue is not None and candidate.venue.name == "Nature"
    assert candidate.language == "en"


def test_html_and_pdf_of_one_copy_become_one_location():
    """Europe PMC lists them as two URLs; the corpus stores one location."""
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    europe_pmc = [loc for loc in candidate.locations if loc.source_name == "Europe PMC"]
    assert len(europe_pmc) == 1
    assert europe_pmc[0].url == "https://europepmc.org/articles/PMC8371605"
    assert europe_pmc[0].pdf_url == "https://europepmc.org/articles/PMC8371605?pdf=render"
    assert europe_pmc[0].is_best is True
    assert europe_pmc[0].licence == "cc-by"


def test_subscription_only_urls_are_never_recorded_as_locations():
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    assert all("doi.org" not in location.url for location in candidate.locations)


def test_open_access_records_claim_green_and_never_gold():
    """Europe PMC knows a free copy exists, not whether the journal is OA."""
    candidate = normalise(as_record("article_alphafold"))
    assert candidate is not None
    assert candidate.oa_status == "green"


def test_a_licence_on_a_closed_record_does_not_make_it_open():
    """Verified against live data: `cc by` with `isOpenAccess` N and no free URL."""
    candidate = normalise(as_record("article_subscription"))
    assert candidate is not None
    assert candidate.oa_status == "closed"
    assert candidate.locations == []


def test_preprint_record_is_flagged_and_names_its_server():
    candidate = normalise(as_record("preprint_biorxiv"))
    assert candidate is not None
    assert candidate.is_preprint is True
    assert candidate.is_peer_reviewed is False
    assert candidate.work_type == "preprint"
    assert candidate.venue is not None and candidate.venue.name == "bioRxiv"
    assert candidate.locations and candidate.locations[0].version == "submittedVersion"


def test_heuristic_preprint_of_link_is_not_turned_into_a_relation():
    """The payload's own note says the link is a title-first-author match."""
    record = as_record("preprint_biorxiv")
    corrections = record.payload["commentCorrectionList"]["commentCorrection"]
    assert corrections[0]["type"] == "Preprint of"
    candidate = normalise(record)
    assert candidate is not None
    assert candidate.preprint_of_doi is None


def test_retracted_article_is_kept_and_flagged():
    candidate = normalise(as_record("article_retracted"))
    assert candidate is not None
    assert candidate.is_retracted_hint is True
    assert candidate.title.startswith("RETRACTED:")


def test_retraction_notice_is_out_of_scope():
    """The notice is a different document from the paper it retracts."""
    result = load_json("europepmc", "article_retracted.json") | {
        "pubTypeList": {"pubType": ["Retraction of Publication", "Retraction Notice"]}
    }
    raw = RawRecord("europepmc", "MED:1", result, FETCHED_AT)
    assert normalise(raw) is None


def test_correction_is_out_of_scope_even_beside_a_journal_article_type():
    result = load_json("europepmc", "article_alphafold.json") | {
        "pubTypeList": {"pubType": ["Published Erratum", "correction"]}
    }
    raw = RawRecord("europepmc", "MED:2", result, FETCHED_AT)
    assert normalise(raw) is None


def test_a_research_type_wins_over_an_excluded_one_in_the_same_record():
    """pubTypeList mixes MEDLINE and JATS vocabularies on one record."""
    result = load_json("europepmc", "article_alphafold.json") | {
        "pubTypeList": {"pubType": ["Editorial", "research-article"]}
    }
    raw = RawRecord("europepmc", "MED:3", result, FETCHED_AT)
    assert normalise(raw) is not None


def test_record_without_identifiers_is_skipped():
    raw = RawRecord("europepmc", "MED:4", {"title": "No ids here"}, FETCHED_AT)
    assert normalise(raw) is None


def test_licence_and_language_codes_are_mapped_to_stored_forms():
    assert map_licence("cc by-nc-nd") == "cc-by-nc-nd"
    assert map_licence(None) is None
    assert map_language("eng") == "en"
    assert map_language("qqq") == "qqq"


def test_query_is_scoped_to_the_update_window():
    query = build_query("OPEN_ACCESS:Y", date(2026, 8, 1), date(2026, 8, 8))
    assert query == "(OPEN_ACCESS:Y) AND UPDATE_DATE:[2026-08-01 TO 2026-08-08]"


def test_cursor_round_trips_with_the_window_it_belongs_to():
    cursor = format_cursor(date(2026, 8, 1), date(2026, 8, 8), "AoIIP2b")
    assert parse_cursor(cursor) == (date(2026, 8, 1), date(2026, 8, 8), "AoIIP2b")


def test_a_finished_window_is_not_resumable():
    """A mark-less cursor means the window was harvested to the end."""
    assert parse_cursor(format_cursor(date(2026, 8, 1), date(2026, 8, 8), "")) is None
    assert parse_cursor(None) is None
    assert parse_cursor("nonsense") is None
