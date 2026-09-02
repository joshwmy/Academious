"""Read queries behind the public API.

Two properties this module exists to hold:

**Projection, not entities.** Queries select the columns the public schemas
name. Loading `Paper` ORM objects would pull `identifiers` and `oa_locations`
through their `selectin` relationships on every list request, and would put the
whole row - operational columns included - one `model_validate` away from a
response.

**A bounded number of queries per request.** A page of any size is one query for
the rows plus one for the total. The detail endpoint is one query for the paper,
one for its identifiers and one for its best open-access location. Nothing here
scales its query count with the size of the page.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, Select, func, select
from sqlalchemy.orm import Session

from academious.db.models.paper import Paper, PaperIdentifier
from academious.db.models.support import OaLocation, Venue
from academious.retrieval import filters as retrieval_filters
from academious.retrieval.filters import SearchFilters

#: The columns a `PaperSummary` is built from. Named explicitly so that adding a
#: column to `paper` cannot widen a public response by accident.
SUMMARY_COLUMNS = (
    Paper.id,
    Paper.title,
    Paper.abstract,
    Paper.authors,
    Paper.published_date,
    Paper.published_year,
    Paper.canonical_doi,
    Paper.is_preprint,
    Paper.is_peer_reviewed,
    Paper.oa_status,
    Paper.retraction_status,
    Paper.topics,
    Paper.fields,
    Paper.citation_count,
    Venue.name.label("venue_name"),
)

DETAIL_COLUMNS = (
    *SUMMARY_COLUMNS,
    Paper.language,
    Paper.work_type,
    Paper.retraction_notice_url,
    Paper.fulltext_licence,
)


def _summary_select(*columns: Any) -> Select[Any]:
    return select(*columns).outerjoin(Venue, Venue.id == Paper.venue_id)


def list_papers(
    session: Session,
    *,
    limit: int,
    offset: int,
    search_filters: SearchFilters | None = None,
) -> tuple[list[Row[Any]], int]:
    """One page of papers, newest first, with the total that matched.

    Ordering is `published_date DESC, id DESC`. The date alone is not a total
    order - the corpus holds many papers per day and PostgreSQL is free to
    return ties in any order it likes, which would make page 2 overlap page 1.
    The id breaks the tie deterministically.
    """
    conditions = retrieval_filters.build_conditions(search_filters or SearchFilters())

    rows = session.execute(
        _summary_select(*SUMMARY_COLUMNS)
        .where(*conditions)
        # `feed_date`, not `published_date`: a postdated issue is correct
        # metadata and the wrong sort key - it would rank work that is not out
        # yet above work that is. See migration 0005. The id breaks ties, which
        # is what keeps page two from repeating page one.
        .order_by(Paper.feed_date.desc().nullslast(), Paper.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    total = session.execute(
        select(func.count()).select_from(Paper).where(*conditions)
    ).scalar_one()
    return list(rows), int(total)


def field_counts(session: Session) -> tuple[dict[str, int], int]:
    """Papers per subject field, and how many carry no field at all.

    Counted under the same default filters the feed applies, so a facet never
    promises results that browsing to it would not show - retracted papers are
    outside both. The second number is the honest half: a paper classified only
    in a vocabulary Academious does not map (MeSH), or not classified at all, is
    unreachable by any field, and the size of that gap is published rather than
    left to be inferred from arithmetic.
    """
    conditions = retrieval_filters.build_conditions(SearchFilters())
    slug = func.unnest(Paper.fields).label("slug")

    rows = session.execute(
        select(slug, func.count().label("papers"))
        .select_from(Paper)
        .where(*conditions)
        .group_by(slug)
    ).all()

    without = session.execute(
        select(func.count())
        .select_from(Paper)
        .where(*conditions, func.cardinality(Paper.fields) == 0)
    ).scalar_one()

    return {str(row.slug): int(row.papers) for row in rows}, int(without)


def get_paper(session: Session, paper_id: uuid.UUID) -> Row[Any] | None:
    return session.execute(
        _summary_select(*DETAIL_COLUMNS).where(Paper.id == paper_id)
    ).first()


def summaries_for_ids(
    session: Session, paper_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Row[Any]]:
    """Summary rows for an already-ranked set of ids, in one query.

    Retrieval returns ids in rank order and hydrates only the columns ranking
    needs. The API needs a few more - authors, the abstract - so it fetches them
    once for the page rather than per hit, and the caller re-applies the order.
    """
    if not paper_ids:
        return {}
    rows = session.execute(
        _summary_select(*SUMMARY_COLUMNS).where(Paper.id.in_(paper_ids))
    ).all()
    return {row.id: row for row in rows}


def identifiers_for(session: Session, paper_id: uuid.UUID) -> dict[str, str]:
    rows = session.execute(
        select(PaperIdentifier.id_type, PaperIdentifier.value).where(
            PaperIdentifier.paper_id == paper_id
        )
    ).all()
    return {row.id_type: row.value for row in rows}


def best_open_access_location(session: Session, paper_id: uuid.UUID) -> Row[Any] | None:
    """The location flagged best for this paper, if one is recorded."""
    return session.execute(
        select(OaLocation.url, OaLocation.pdf_url, OaLocation.licence)
        .where(OaLocation.paper_id == paper_id, OaLocation.is_best.is_(True))
        .limit(1)
    ).first()
