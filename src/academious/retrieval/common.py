"""Shared projection: the columns every retrieval method returns, in one place.

Lexical, semantic and hybrid results have to be interchangeable - the evaluation
harness pools them, and hybrid fusion re-hydrates ids that came out of either
component. That only holds if all three build the same hit from the same
columns, which is what this module exists to guarantee.

**Retrieval is two-phase, and that is a measured decision.** Ranking selects
paper ids and a score, nothing else; the display columns are fetched afterwards
for the page that survived. Selecting them during ranking makes PostgreSQL
materialise a wide `paper` row for every candidate it scores, and on the Phase 2
corpus that join dominated query time - 17 ms of a 31 ms semantic query, against
2.5 ms for the vector scan itself (docs/performance.md). Filters still apply in
phase one, so the narrowing is a projection change only and cannot alter which
papers are returned or in what order.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, Select, select
from sqlalchemy.orm import Session

from academious.db.models.paper import Paper
from academious.db.models.support import Venue
from academious.retrieval.types import RetrievalHit

HIT_COLUMNS = (
    Paper.id,
    Paper.title,
    Paper.canonical_doi,
    Paper.published_date,
    Paper.is_preprint,
    Paper.is_peer_reviewed,
    Paper.oa_status,
    Paper.retraction_status,
    Paper.topics,
    Venue.name.label("venue_name"),
)


def base_select(*extra: Any) -> Select[Any]:
    """Paper metadata joined to its venue, plus whatever the method scores by."""
    return select(*HIT_COLUMNS, *extra).outerjoin(Venue, Venue.id == Paper.venue_id)


def ranking_select(score: Any) -> Select[Any]:
    """Phase one: ids and a score. No venue join, no wide columns."""
    return select(Paper.id, score)


def hits_from_ranked(
    session: Session, ranked: Sequence[Row[Any]], *, score_kind: str
) -> list[RetrievalHit]:
    """Phase two: turn (id, score) rows into hits, fetching metadata in one query."""
    metadata = hydrate(session, [row.id for row in ranked])
    hits: list[RetrievalHit] = []
    for index, row in enumerate(ranked):
        detail = metadata.get(row.id)
        if detail is None:
            # Deleted between the two phases. Dropping it is right; inventing a
            # placeholder would put a paper that no longer exists on a page.
            continue
        hits.append(
            row_to_hit(detail, rank=index + 1, score=row.score, score_kind=score_kind)
        )
    return hits


def row_to_hit(row: Row[Any], *, rank: int, score: float, score_kind: str) -> RetrievalHit:
    return RetrievalHit(
        paper_id=row.id,
        rank=rank,
        score=float(score),
        score_kind=score_kind,
        title=row.title,
        canonical_doi=row.canonical_doi,
        published_date=row.published_date,
        is_preprint=row.is_preprint,
        is_peer_reviewed=row.is_peer_reviewed,
        oa_status=row.oa_status,
        retraction_status=row.retraction_status,
        venue_name=row.venue_name,
        topics=list(row.topics or []),
    )


def hydrate(session: Session, paper_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Row[Any]]:
    """Fetch hit metadata for ids that were ranked without selecting it.

    Hybrid fusion works on ids and scores; it only needs the metadata for the
    page it is about to return, so this is one query for the survivors rather
    than carrying full rows through the fusion.
    """
    if not paper_ids:
        return {}
    rows = session.execute(base_select().where(Paper.id.in_(paper_ids))).all()
    return {row.id: row for row in rows}
