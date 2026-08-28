"""Field precedence when several sources describe the same paper.

Precedence is declared as data, not as branches in code, so that adding a source
means editing a table rather than auditing conditionals. Every rule here is a
judgement about which source is most trustworthy for one field; see
docs/data-model.md for the reasoning behind each.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from academious.core.text import normalise_title, surname
from academious.db.models.paper import FullTextStatus, Paper
from academious.sources.base import PaperCandidate

# Higher number wins. Sources absent from a list never supply that field.
ABSTRACT_PRIORITY = {"pubmed": 50, "europepmc": 40, "openalex": 30, "biorxiv": 20, "arxiv": 10}
TITLE_PRIORITY = {"openalex": 30, "pubmed": 25, "biorxiv": 20, "arxiv": 10}
VENUE_PRIORITY = {"openalex": 30, "pubmed": 20, "biorxiv": 10, "arxiv": 5}
TOPIC_PRIORITY = {"openalex": 30, "pubmed": 20, "biorxiv": 10, "arxiv": 5}
# Citation counts are only meaningful from a source that computes them globally.
CITATION_SOURCES = frozenset({"openalex"})

# Most open first. A later source may only improve the recorded status.
OA_RANK = {
    "unknown": 0,
    "closed": 1,
    "bronze": 2,
    "green": 3,
    "hybrid": 4,
    "gold": 5,
    "diamond": 6,
}


def _priority(table: dict[str, int], source_key: str) -> int:
    return table.get(source_key, 0)


def merge_topics(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union of topics, keyed by (scheme, id). Different schemes coexist."""
    merged = {(t.get("scheme"), t.get("id")): t for t in existing}
    for topic in incoming:
        merged.setdefault((topic.get("scheme"), topic.get("id")), topic)
    return list(merged.values())


def merge_keywords(existing: list[str], incoming: list[str]) -> list[str]:
    seen = {k.casefold(): k for k in existing}
    for keyword in incoming:
        seen.setdefault(keyword.casefold(), keyword)
    return list(seen.values())


def better_oa_status(existing: str, incoming: str) -> str:
    return incoming if OA_RANK.get(incoming, 0) > OA_RANK.get(existing, 0) else existing


def earliest(left: date | None, right: date | None) -> date | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def apply_candidate(paper: Paper, candidate: PaperCandidate) -> bool:
    """Fold a candidate into a paper. Returns True if anything changed.

    `paper.field_sources` is not stored; precedence is re-evaluated from the
    incoming source key each time, which is safe because the priority tables are
    total orders and merges are idempotent.
    """
    changed = False
    source = candidate.source_key
    existing_source = paper.abstract_source or ""

    # Title: only a higher-priority source may overwrite one already present.
    title_outranks = _priority(TITLE_PRIORITY, source) > _priority(
        TITLE_PRIORITY, existing_source
    )
    if (
        candidate.title
        and (not paper.title or title_outranks)
        and paper.title != candidate.title
    ):
            paper.title = candidate.title
            paper.title_norm = normalise_title(candidate.title)
            changed = True

    # Abstract: priority first, then prefer the longer text within a tie.
    if candidate.abstract:
        incoming_rank = _priority(ABSTRACT_PRIORITY, source)
        current_rank = _priority(ABSTRACT_PRIORITY, existing_source)
        longer = len(candidate.abstract) > len(paper.abstract or "")
        if paper.abstract is None or incoming_rank > current_rank or (
            incoming_rank == current_rank and longer
        ):
            paper.abstract = candidate.abstract
            paper.abstract_source = source
            changed = True

    author_rank_ok = _priority(TITLE_PRIORITY, source) >= _priority(
        TITLE_PRIORITY, existing_source
    )
    if candidate.authors and (not paper.authors or author_rank_ok):
        serialised = [author.to_json() for author in candidate.authors]
        if serialised != paper.authors:
            paper.authors = serialised
            first = candidate.authors[0].name if candidate.authors else None
            paper.first_author_surname = surname(first)
            changed = True

    published = candidate.published_date
    date_outranks = paper.published_date is None or _priority(TITLE_PRIORITY, source) >= _priority(
        TITLE_PRIORITY, existing_source
    )
    if published and paper.published_date != published and date_outranks:
        paper.published_date = published
        paper.published_year = published.year
        changed = True

    earliest_online = earliest(paper.first_seen_online, candidate.first_seen_online)
    if earliest_online != paper.first_seen_online:
        paper.first_seen_online = earliest_online
        changed = True

    # A paper is peer reviewed if ANY source says so; it is a preprint only while
    # no source has reported a peer-reviewed version.
    if candidate.is_peer_reviewed and not paper.is_peer_reviewed:
        paper.is_peer_reviewed = True
        changed = True
    if paper.is_peer_reviewed and paper.is_preprint and not candidate.is_preprint:
        paper.is_preprint = False
        changed = True
    elif candidate.is_preprint and paper.is_preprint is None:
        paper.is_preprint = True
        changed = True

    if candidate.work_type and not paper.work_type:
        paper.work_type = candidate.work_type
        changed = True
    if candidate.language and not paper.language:
        paper.language = candidate.language
        changed = True

    if candidate.topics and _priority(TOPIC_PRIORITY, source) > 0:
        merged_topics = merge_topics(paper.topics or [], candidate.topics)
        if merged_topics != paper.topics:
            paper.topics = merged_topics
            changed = True


    if candidate.keywords:
        merged_keywords = merge_keywords(paper.keywords or [], candidate.keywords)
        if merged_keywords != paper.keywords:
            paper.keywords = merged_keywords
            changed = True

    if (
        source in CITATION_SOURCES
        and candidate.citation_count is not None
        and paper.citation_count != candidate.citation_count
    ):
        paper.citation_count = candidate.citation_count
        changed = True

    improved_oa = better_oa_status(paper.oa_status or "unknown", candidate.oa_status)
    if improved_oa != paper.oa_status:
        paper.oa_status = improved_oa
        changed = True

    if candidate.locations and paper.fulltext_status == FullTextStatus.NONE.value:
        paper.fulltext_status = FullTextStatus.LINKED.value
        changed = True
    elif (
        not candidate.locations
        and paper.abstract
        and paper.fulltext_status == FullTextStatus.NONE.value
    ):
        paper.fulltext_status = FullTextStatus.ABSTRACT_ONLY.value
        changed = True

    return changed
