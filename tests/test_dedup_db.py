"""Fuzzy deduplication and its refusals. Requires pg_trgm, so PostgreSQL only."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from academious.core.config import get_settings
from academious.core.ids import IdType
from academious.db.models.paper import Paper, PaperMerge
from academious.ingest import canonicalise
from academious.sources.base import CandidateAuthor, CandidateIdentifier, PaperCandidate

pytestmark = pytest.mark.db

TITLE = "A new route for integron cassette dissemination among bacterial genomes"
AUTHORS = ["Céline Loot", "Guillaume Millot", "Didier Mazel"]


def candidate(source: str, title: str, *, doi: str | None = None, authors=None, year=2022):
    from datetime import date

    identifiers = [CandidateIdentifier(IdType.DOI, doi)] if doi else []
    return PaperCandidate(
        source_key=source,
        source_id=f"{source}-{title[:12]}",
        title=title,
        identifiers=identifiers,
        authors=[
            CandidateAuthor(name=name, position=index)
            for index, name in enumerate(authors or AUTHORS)
        ],
        published_date=date(year, 6, 1),
    )


def ingest(session, candidate_obj):
    from academious.ingest.merge import apply_candidate
    from academious.ingest.pipeline import _sync_identifiers

    match = canonicalise.resolve(session, candidate_obj, get_settings())
    _sync_identifiers(session, match.paper, candidate_obj)
    apply_candidate(match.paper, candidate_obj)
    session.flush()
    return match


def test_identical_title_and_authors_without_dois_are_merged(session):
    first = ingest(session, candidate("openalex", TITLE))
    second = ingest(session, candidate("biorxiv", TITLE))

    assert first.created is True
    assert second.created is False
    assert second.rule == "fuzzy_title_author"
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 1


def test_different_dois_are_never_fuzzy_merged(session):
    """A preprint and its published version share a topic, not an identity."""
    ingest(session, candidate("openalex", TITLE, doi="10.1101/2022.09.11.507474"))
    ingest(session, candidate("openalex", TITLE, doi="10.1038/s41564-023-01548-y"))

    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2


def test_same_title_with_unrelated_authors_is_not_merged(session):
    ingest(session, candidate("openalex", TITLE))
    ingest(session, candidate("openalex", TITLE, authors=["Ada Lovelace", "Alan Turing"]))

    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2


def test_different_titles_by_the_same_authors_are_not_merged(session):
    ingest(session, candidate("openalex", TITLE))
    ingest(
        session,
        candidate(
            "openalex",
            "Integron cassettes integrate into bacterial genomes via attG sites",
        ),
    )
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2


def test_very_short_titles_never_fuzzy_match(session):
    ingest(session, candidate("openalex", "Reply"))
    ingest(session, candidate("openalex", "Reply"))
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2


def test_shared_identifier_merges_two_existing_papers_and_records_an_audit(session):
    """Two papers known separately, then a record arrives carrying both ids."""
    ingest(session, candidate("openalex", TITLE, doi="10.1234/aaa"))
    ingest(
        session,
        candidate("arxiv", "Completely different work about compilers", doi="10.1234/bbb"),
    )
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2

    bridging = PaperCandidate(
        source_key="openalex",
        source_id="bridge",
        title=TITLE,
        identifiers=[
            CandidateIdentifier(IdType.DOI, "10.1234/aaa"),
            CandidateIdentifier(IdType.PMID, "111"),
        ],
    )
    ingest(session, bridging)
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 2


def test_merge_moves_identifiers_and_is_auditable(session):
    left = ingest(session, candidate("openalex", TITLE, doi="10.1234/aaa")).paper
    right = ingest(
        session, candidate("arxiv", "Another unrelated paper entirely", doi=None)
    ).paper

    canonicalise.merge_papers(
        session, left, right, rule="manual", confidence=0.99, details={"why": "test"}
    )
    session.flush()

    audit = session.execute(select(PaperMerge)).scalars().one()
    assert audit.winner_id == left.id
    assert audit.loser_id == right.id
    assert audit.rule == "manual"
    assert session.execute(select(func.count()).select_from(Paper)).scalar_one() == 1


def test_conflicting_helper_matches_the_documented_rule():
    left = Paper(title="a", title_norm="a", canonical_doi="10.1/a")
    right = Paper(title="b", title_norm="b", canonical_doi="10.1/b")
    same = Paper(title="c", title_norm="c", canonical_doi="10.1/a")
    unknown = Paper(title="d", title_norm="d", canonical_doi=None)

    assert canonicalise.conflicting(left, right) is True
    assert canonicalise.conflicting(left, same) is False
    assert canonicalise.conflicting(left, unknown) is False


def test_preprint_doi_detection():
    assert canonicalise.is_preprint_doi("10.1101/2022.09.11.507474") is True
    assert canonicalise.is_preprint_doi("10.48550/arxiv.1706.03762") is True
    assert canonicalise.is_preprint_doi("10.1038/s41564-023-01548-y") is False
    assert canonicalise.is_preprint_doi(None) is False
