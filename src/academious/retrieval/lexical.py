"""Lexical retrieval over PostgreSQL full-text search.

This is the baseline the semantic system has to beat. Without it, "the
embeddings return plausible papers" is an observation about plausibility, not
evidence that SPECTER2 earns its CPU cost - so the baseline is built to be
genuinely good, not to lose.

Elasticsearch is deliberately absent. It would add a second datastore, a second
index to keep consistent with `paper`, and an operational surface no other part
of Phase 2 needs. Weighted `tsvector` with `ts_rank_cd` covers the baseline role
at this corpus size.

**Two-pass querying.** `websearch_to_tsquery` requires every term, which is
correct for a keyword search box and wrong for a research interest. "public
health diabetes risk prediction" as a conjunction matches almost nothing, and a
baseline that returns nothing is not a baseline, it is a strawman. So the strict
query runs first, and only if it finds nothing does the same parsed query run
again with its conjunctions relaxed to disjunctions. Ranking still favours
papers matching more of the terms, because that is what ts_rank_cd measures.

The relaxation is skipped when the query contains a negation: turning `a & !b`
into `a | !b` does not loosen the query, it inverts what the exclusion means.

The index itself - which fields, at which weights - is a stored generated column
defined in academious/db/ddl.py.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Float,
    Row,
    Text,
    cast,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from academious.db.models.paper import Paper
from academious.retrieval import common
from academious.retrieval import filters as filter_module
from academious.retrieval.types import RetrievalResult, ScoreKind

#: PostgreSQL weight array, ordered {D, C, B, A}. Assignment of fields to letters
#: is in db/ddl.py: A title, B keywords and topic labels, C abstract. A title
#: match is worth five abstract matches, because a paper that puts a term in its
#: title is about that term, whereas an abstract mentions everything it touches.
DEFAULT_WEIGHTS = (0.1, 0.2, 0.4, 1.0)

#: ts_rank_cd normalisation bitmask.
#:   1  divide by 1 + log(document length) - stops long abstracts winning on
#:      volume alone
#:   32 rank / (rank + 1)                  - bounds the score in [0, 1), which
#:      makes it comparable across queries and safe to feed weighted fusion
DEFAULT_NORMALISATION = 1 | 32

TEXT_SEARCH_CONFIG = "english"

STRICT = "strict"
RELAXED = "relaxed"


def strict_tsquery(query: str) -> ColumnElement[Any]:
    """All terms required. Handles quoted phrases and leading-minus exclusion."""
    return func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)


def relaxed_tsquery(query: str) -> ColumnElement[Any]:
    """The same parsed query with `&` rewritten to `|`.

    Rewriting the rendered tsquery rather than re-parsing the raw string keeps
    everything websearch_to_tsquery understood: a quoted phrase stays a phrase
    operator, and stemming has already been applied.
    """
    return cast(func.replace(cast(strict_tsquery(query), Text), " & ", " | "), TSQUERY)


def _rank(
    tsquery: ColumnElement[Any],
    weights: tuple[float, float, float, float],
    normalisation: int,
) -> ColumnElement[float]:
    return func.ts_rank_cd(
        literal_column(f"ARRAY{list(weights)}::float4[]"),
        Paper.search_tsv,
        tsquery,
        literal(normalisation),
    ).cast(Float)


def _fetch(
    session: Session,
    tsquery: ColumnElement[Any],
    *,
    limit: int,
    active_filters: filter_module.SearchFilters,
    weights: tuple[float, float, float, float],
    normalisation: int,
) -> Sequence[Row[Any]]:
    rank = _rank(tsquery, weights, normalisation)
    statement = common.ranking_select(rank.label("score")).where(
        Paper.search_tsv.op("@@")(tsquery)
    )
    condition = filter_module.combined(active_filters)
    if condition is not None:
        statement = statement.where(condition)
    statement = statement.order_by(
        rank.desc(), Paper.published_date.desc().nullslast(), Paper.id
    ).limit(limit)
    return session.execute(statement).all()


def search(
    session: Session,
    query: str,
    *,
    limit: int = 20,
    search_filters: filter_module.SearchFilters | None = None,
    weights: tuple[float, float, float, float] = DEFAULT_WEIGHTS,
    normalisation: int = DEFAULT_NORMALISATION,
    allow_relaxed: bool = True,
) -> RetrievalResult:
    """Rank papers by weighted full-text relevance to `query`."""
    started = time.perf_counter()
    active_filters = search_filters or filter_module.SearchFilters()

    rows = _fetch(
        session,
        strict_tsquery(query),
        limit=limit,
        active_filters=active_filters,
        weights=weights,
        normalisation=normalisation,
    )
    mode = STRICT

    if not rows and allow_relaxed:
        rendered = session.execute(
            select(func.coalesce(cast(strict_tsquery(query), Text), ""))
        ).scalar_one()
        # Only worth a second pass if there was a conjunction to relax, and only
        # safe if relaxing it cannot invert an exclusion.
        if " & " in rendered and "!" not in rendered:
            rows = _fetch(
                session,
                relaxed_tsquery(query),
                limit=limit,
                active_filters=active_filters,
                weights=weights,
                normalisation=normalisation,
            )
            mode = RELAXED

    hits = common.hits_from_ranked(session, rows, score_kind=ScoreKind.TS_RANK_CD)

    return RetrievalResult(
        query=query,
        method="lexical",
        hits=hits,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        candidates_considered=len(hits),
        detail={
            "query_mode": mode,
            "weights": list(weights),
            "normalisation": normalisation,
            "config": TEXT_SEARCH_CONFIG,
            "filters": active_filters.describe(),
        },
    )
