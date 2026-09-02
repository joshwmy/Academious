"""Reconcile a PaperCandidate against the canonical corpus.

Order of attack, from cheapest and most certain to most speculative:

1. Identifier match. A shared normalised DOI/PMID/PMCID/arXiv id is proof of
   identity, and covers the large majority of records.
2. Fuzzy match on a normalised title, blocked by first-author surname and
   publication year, confirmed by author overlap.
3. Otherwise, a new paper.

The thresholds are deliberately conservative. A missed merge shows the user a
duplicate, which is untidy; a wrong merge destroys a distinct paper and is very
hard to notice afterwards. When in doubt this module does not merge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.core.config import Settings, get_settings
from academious.core.ids import IdType
from academious.core.logging import get_logger
from academious.core.text import (
    blocking_weight,
    jaccard,
    normalise_title,
    surname,
    surname_set,
)
from academious.db.models.paper import Paper, PaperIdentifier, PaperMerge
from academious.sources.base import PaperCandidate

log = get_logger(__name__)

# DOI prefixes that identify a preprint server. A record with one of these and a
# record with a publisher DOI are different versions, never the same row.
PREPRINT_DOI_PREFIXES = ("10.1101/", "10.48550/", "10.31234/", "10.21203/", "10.26434/")
# Strongest first: used to pick a survivor when identifiers disagree.
IDENTIFIER_STRENGTH = [IdType.DOI, IdType.PMCID, IdType.PMID, IdType.ARXIV, IdType.OPENALEX]


@dataclass(slots=True)
class MatchResult:
    paper: Paper
    created: bool
    rule: str
    confidence: float
    merged_paper_ids: list[uuid.UUID]


def is_preprint_doi(doi: str | None) -> bool:
    return bool(doi) and doi.lower().startswith(PREPRINT_DOI_PREFIXES)  # type: ignore[union-attr]


def conflicting(left: Paper, right: Paper) -> bool:
    """True when two papers cannot be the same row.

    Distinct DOIs mean distinct records. That is what keeps a preprint and its
    published version apart even when a source links them with a shared arXiv id.
    """
    if left.canonical_doi and right.canonical_doi:
        return left.canonical_doi != right.canonical_doi
    return False


def find_by_identifiers(session: Session, candidate: PaperCandidate) -> list[Paper]:
    """Every existing paper sharing at least one normalised identifier."""
    if not candidate.identifiers:
        return []
    pairs = [(i.id_type.value, i.value) for i in candidate.identifiers]
    rows = session.execute(
        select(PaperIdentifier).where(
            tuple_(PaperIdentifier.id_type, PaperIdentifier.value).in_(pairs)
        )
    ).scalars().all()

    papers: dict[uuid.UUID, Paper] = {}
    for row in rows:
        if row.paper_id not in papers:
            found = session.get(Paper, row.paper_id)
            if found is not None:
                papers[row.paper_id] = found
    return list(papers.values())


def _fuzzy_query(
    title_norm: str, surname_value: str | None, year: int | None, block: float
) -> Select[tuple[Paper]]:
    """Trigram-blocked candidate query.

    Built with expressions rather than raw SQL because the trigram operator is a
    literal `%`, which a raw text() clause would collide with psycopg's
    parameter syntax. `.op("%")` emits it correctly and still uses the GIN index.
    """
    score = func.similarity(Paper.title_norm, title_norm).label("score")
    conditions = [
        Paper.title_norm.op("%")(title_norm),
        score >= block,
    ]
    if surname_value is not None:
        conditions.append(Paper.first_author_surname == surname_value)
    if year is not None:
        conditions.append(
            or_(
                Paper.published_year.is_(None),
                and_(Paper.published_year >= year - 1, Paper.published_year <= year + 1),
            )
        )
    return (
        select(Paper.id, score).where(and_(*conditions)).order_by(score.desc()).limit(10)
    )


def find_fuzzy(
    session: Session, candidate: PaperCandidate, settings: Settings
) -> tuple[Paper, float] | None:
    """Trigram-blocked title match, confirmed by author overlap.

    Requires pg_trgm. The `%%` operator is escaped for SQLAlchemy's parameter
    binding; it reaches PostgreSQL as the trigram similarity operator `%`.
    """
    title_norm = normalise_title(candidate.title)
    if blocking_weight(title_norm) < 12:
        # Very short titles ("Errata", "Reply") produce false positives.
        # Weighted rather than counted: a bare `len()` is a Latin character
        # count, and it would reject a ten-ideograph Chinese title that names a
        # paper precisely. See core/text.blocking_weight.
        return None

    first_author = candidate.authors[0].name if candidate.authors else None
    rows = session.execute(
        _fuzzy_query(
            title_norm,
            surname(first_author),
            candidate.published_date.year if candidate.published_date else None,
            settings.dedup_trigram_block_threshold,
        )
    ).all()

    candidate_surnames = surname_set([author.name for author in candidate.authors])
    candidate_doi = candidate.primary_doi

    for row in rows:
        score = float(row.score)
        if score < settings.dedup_title_similarity_threshold:
            continue
        existing = session.get(Paper, row.id)
        if existing is None:
            continue

        # Distinct DOIs are decisive: never fuzzy-merge across them.
        if candidate_doi and existing.canonical_doi and candidate_doi != existing.canonical_doi:
            continue

        existing_surnames = surname_set(
            [author.get("name", "") for author in (existing.authors or [])]
        )
        overlap = jaccard(candidate_surnames, existing_surnames)
        if overlap < settings.dedup_author_jaccard_threshold:
            continue

        return existing, min(score, 1.0) * max(overlap, 0.5)

    return None


def merge_papers(
    session: Session,
    winner: Paper,
    loser: Paper,
    *,
    rule: str,
    confidence: float,
    details: dict[str, object] | None = None,
) -> None:
    """Move the loser's identifiers onto the winner and record a reversible audit."""
    if winner.id == loser.id:
        return

    existing_keys = {(i.id_type, i.value) for i in winner.identifiers}
    for identifier in list(loser.identifiers):
        if (identifier.id_type, identifier.value) in existing_keys:
            session.delete(identifier)
        else:
            identifier.paper_id = winner.id

    for location in list(loser.oa_locations):
        location.paper_id = winner.id

    if not winner.canonical_doi and loser.canonical_doi:
        winner.canonical_doi = loser.canonical_doi

    session.add(
        PaperMerge(
            winner_id=winner.id,
            loser_id=loser.id,
            rule=rule,
            confidence=confidence,
            details=details or {},
            created_at=utcnow(),
        )
    )
    session.flush()
    session.delete(loser)
    log.info("dedup.merged", winner=str(winner.id), loser=str(loser.id), rule=rule)


def _identifier_rank(paper: Paper, candidate: PaperCandidate) -> int:
    """How strongly `paper` is attached to `candidate`, for survivor selection."""
    values = {(i.id_type, i.value) for i in paper.identifiers}
    for strength, id_type in enumerate(IDENTIFIER_STRENGTH):
        if any(key == (id_type.value, value) for key in values
               for value in candidate.identifier_values(id_type)):
            return len(IDENTIFIER_STRENGTH) - strength
    return 0


def _new_paper(candidate: PaperCandidate) -> Paper:
    first_author = candidate.authors[0].name if candidate.authors else None
    return Paper(
        canonical_doi=candidate.primary_doi,
        title=candidate.title,
        title_norm=normalise_title(candidate.title),
        authors=[],
        first_author_surname=surname(first_author),
        published_year=candidate.published_date.year if candidate.published_date else None,
        is_preprint=candidate.is_preprint,
        is_peer_reviewed=candidate.is_peer_reviewed,
        topics=[],
        keywords=[],
    )


def resolve(
    session: Session,
    candidate: PaperCandidate,
    settings: Settings | None = None,
    *,
    create: bool = True,
) -> MatchResult | None:
    """Find, and unless `create` is False, create the canonical Paper.

    `create=False` asks a narrower question: *is this work already known?* A
    deposit in a general-purpose repository may enrich a paper the corpus holds
    but may not found one on its own, so the pipeline asks that way and gets
    None when nothing matches. See ingest/repositories.py.
    """
    settings = settings or get_settings()
    matches = find_by_identifiers(session, candidate)
    merged_ids: list[uuid.UUID] = []

    if matches:
        # Prefer the paper attached by the strongest identifier; where several
        # match and none conflict, fold them together.
        matches.sort(key=lambda p: _identifier_rank(p, candidate), reverse=True)
        winner = matches[0]
        for other in matches[1:]:
            if conflicting(winner, other):
                log.info(
                    "dedup.conflict_kept_separate",
                    winner=str(winner.id),
                    other=str(other.id),
                    winner_doi=winner.canonical_doi,
                    other_doi=other.canonical_doi,
                )
                continue
            merge_papers(
                session,
                winner,
                other,
                rule="identifier",
                confidence=1.0,
                details={"source": candidate.source_key},
            )
            merged_ids.append(other.id)
        return MatchResult(winner, False, "identifier", 1.0, merged_ids)

    fuzzy = find_fuzzy(session, candidate, settings)
    if fuzzy is not None:
        paper, confidence = fuzzy
        log.info(
            "dedup.fuzzy_match",
            paper=str(paper.id),
            confidence=round(confidence, 3),
            source=candidate.source_key,
        )
        return MatchResult(paper, False, "fuzzy_title_author", confidence, merged_ids)

    if not create:
        return None

    paper = _new_paper(candidate)
    session.add(paper)
    session.flush()
    return MatchResult(paper, True, "created", 1.0, merged_ids)
