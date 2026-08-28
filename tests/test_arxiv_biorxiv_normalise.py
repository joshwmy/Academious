"""arXiv and bioRxiv normalisation, against records captured from the live APIs."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.conftest import load_json, load_text

from academious.core.ids import IdType
from academious.sources.arxiv.client import parse_list_records
from academious.sources.arxiv.normalise import is_open_licence
from academious.sources.arxiv.normalise import normalise as normalise_arxiv
from academious.sources.base import RawRecord
from academious.sources.biorxiv.normalise import (
    is_storable_licence,
    map_licence,
    split_authors,
)
from academious.sources.biorxiv.normalise import normalise as normalise_biorxiv

WHEN = datetime(2026, 8, 28, tzinfo=UTC)


def arxiv_candidate():
    records, _ = parse_list_records(load_text("arxiv", "getrecord_1706.03762.xml"))
    return normalise_arxiv(RawRecord("arxiv", records[0]["id"], records[0], WHEN))


def biorxiv_candidate():
    payload = load_json("biorxiv", "details_integron.json")["collection"][-1]
    return normalise_biorxiv(RawRecord("biorxiv", "x", {**payload, "server": "biorxiv"}, WHEN))


def test_arxiv_record_parses_title_authors_and_id():
    candidate = arxiv_candidate()
    assert candidate is not None
    assert candidate.title == "Attention Is All You Need"
    assert candidate.identifier_values(IdType.ARXIV) == ["1706.03762"]
    assert len(candidate.authors) == 8
    assert candidate.authors[0].name == "Ashish Vaswani"


def test_arxiv_licence_is_not_creative_commons():
    """Verified against a real record: arXiv's default licence forbids re-serving."""
    candidate = arxiv_candidate()
    assert candidate is not None
    licence = candidate.locations[0].licence
    assert licence is not None and "nonexclusive-distrib" in licence
    assert is_open_licence(licence) is False


def test_arxiv_open_licence_detection():
    assert is_open_licence("http://creativecommons.org/licenses/by/4.0/") is True
    assert is_open_licence("http://creativecommons.org/publicdomain/zero/1.0/") is True
    assert is_open_licence(None) is False


def test_arxiv_categories_become_topics():
    candidate = arxiv_candidate()
    assert candidate is not None
    assert {topic["id"] for topic in candidate.topics} == {"cs.CL", "cs.LG"}


def test_arxiv_record_without_id_is_skipped():
    assert normalise_arxiv(RawRecord("arxiv", "x", {"title": "No id"}, WHEN)) is None


def test_biorxiv_exposes_the_published_doi():
    """This link is the only authoritative preprint-to-published mapping we have."""
    candidate = biorxiv_candidate()
    assert candidate is not None
    assert candidate.primary_doi == "10.1101/2022.09.11.507474"
    assert candidate.preprint_of_doi == "10.1038/s41564-023-01548-y"


def test_biorxiv_splits_the_semicolon_author_string():
    candidate = biorxiv_candidate()
    assert candidate is not None
    assert len(candidate.authors) == 13
    assert candidate.authors[0].name == "Loot, C."


def test_split_authors_handles_empty_input():
    assert split_authors(None) == []
    assert split_authors("  ") == []


def test_biorxiv_licence_mapping_and_storability():
    assert map_licence("cc_by") == "cc-by"
    assert map_licence("cc_no") == "biorxiv-no-reuse"
    assert is_storable_licence("cc_by") is True
    assert is_storable_licence("cc_no") is False
    assert is_storable_licence(None) is False


def test_biorxiv_record_is_always_a_preprint():
    candidate = biorxiv_candidate()
    assert candidate is not None
    assert candidate.is_preprint is True
    assert candidate.is_peer_reviewed is False
    assert candidate.oa_status == "green"
