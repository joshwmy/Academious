"""Field precedence when several sources describe the same paper."""

from __future__ import annotations

from datetime import date

from academious.db.models.paper import Paper
from academious.ingest.merge import apply_candidate, better_oa_status, earliest, merge_topics
from academious.sources.base import CandidateAuthor, PaperCandidate


def blank_paper() -> Paper:
    return Paper(
        title="",
        title_norm="",
        authors=[],
        topics=[],
        keywords=[],
        oa_status="unknown",
        fulltext_status="none",
        retraction_status="none",
        is_preprint=False,
        is_peer_reviewed=False,
    )


def candidate(source: str, **overrides) -> PaperCandidate:
    base = {
        "source_key": source,
        "source_id": "id",
        "title": "A title",
    }
    return PaperCandidate(**(base | overrides))


def test_higher_priority_source_replaces_the_abstract():
    paper = blank_paper()
    apply_candidate(paper, candidate("arxiv", abstract="arxiv version"))
    assert paper.abstract == "arxiv version"
    apply_candidate(paper, candidate("openalex", abstract="openalex version"))
    assert paper.abstract == "openalex version"
    assert paper.abstract_source == "openalex"


def test_lower_priority_source_does_not_overwrite_an_abstract():
    paper = blank_paper()
    apply_candidate(paper, candidate("openalex", abstract="openalex version"))
    apply_candidate(paper, candidate("arxiv", abstract="arxiv version"))
    assert paper.abstract == "openalex version"


def test_missing_abstract_is_filled_by_any_source():
    paper = blank_paper()
    apply_candidate(paper, candidate("openalex", abstract=None))
    apply_candidate(paper, candidate("biorxiv", abstract="from the preprint"))
    assert paper.abstract == "from the preprint"


def test_peer_review_is_sticky_once_any_source_reports_it():
    paper = blank_paper()
    apply_candidate(paper, candidate("biorxiv", is_preprint=True))
    assert paper.is_peer_reviewed is False
    apply_candidate(paper, candidate("openalex", is_peer_reviewed=True, is_preprint=False))
    assert paper.is_peer_reviewed is True
    assert paper.is_preprint is False
    apply_candidate(paper, candidate("arxiv", is_preprint=True))
    assert paper.is_peer_reviewed is True


def test_citation_counts_only_come_from_a_source_that_computes_them():
    paper = blank_paper()
    apply_candidate(paper, candidate("biorxiv", citation_count=999))
    assert paper.citation_count is None
    apply_candidate(paper, candidate("openalex", citation_count=27))
    assert paper.citation_count == 27


def test_topics_from_different_schemes_coexist():
    paper = blank_paper()
    apply_candidate(paper, candidate("arxiv", topics=[{"id": "cs.CL", "scheme": "arxiv"}]))
    apply_candidate(paper, candidate("openalex", topics=[{"id": "T10120", "scheme": "openalex"}]))
    schemes = {topic["scheme"] for topic in paper.topics}
    assert schemes == {"arxiv", "openalex"}


def test_merge_topics_is_idempotent():
    existing = [{"id": "T1", "scheme": "openalex"}]
    assert merge_topics(existing, existing) == existing


def test_oa_status_only_improves():
    assert better_oa_status("closed", "gold") == "gold"
    assert better_oa_status("gold", "closed") == "gold"
    assert better_oa_status("unknown", "green") == "green"


def test_earliest_online_date_wins():
    assert earliest(date(2024, 1, 3), date(2022, 9, 13)) == date(2022, 9, 13)
    assert earliest(None, date(2022, 9, 13)) == date(2022, 9, 13)
    assert earliest(date(2022, 9, 13), None) == date(2022, 9, 13)
    assert earliest(None, None) is None


def test_authors_populate_the_dedup_blocking_key():
    paper = blank_paper()
    apply_candidate(
        paper, candidate("openalex", authors=[CandidateAuthor(name="Céline Loot", position=0)])
    )
    assert paper.first_author_surname == "loot"


def test_apply_is_idempotent_and_reports_no_change_on_replay():
    paper = blank_paper()
    single = candidate("openalex", abstract="text", citation_count=5)
    assert apply_candidate(paper, single) is True
    assert apply_candidate(paper, single) is False
