"""Semantic retrieval over pgvector.

The query is a description of a research interest, not a paper and not a
keyword list, so it is encoded with SPECTER2's ad-hoc query adapter while the
corpus is encoded with the proximity adapter. Encoding the two sides with the
same adapter is the most common way to get mediocre numbers out of a model that
is not mediocre.

Vectors are stored L2-normalised, so cosine distance and inner product agree and
`1 - (a <=> b)` is a true cosine similarity in [-1, 1]. That similarity is
reported as-is. It is a diagnostic, not a percentage of relevance, and nothing
downstream should present it as one.

Search is exact: no ANN index is consulted, because Phase 2's job is to
establish what exact search costs before trading accuracy for latency. The
measurements, and the point at which that trade becomes necessary, are in
docs/performance.md.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
from sqlalchemy.orm import Session

from academious.db.models.embedding import PaperEmbedding
from academious.db.models.paper import Paper
from academious.embeddings.backend import EmbeddingBackend
from academious.retrieval import common
from academious.retrieval import filters as filter_module
from academious.retrieval.types import RetrievalResult, ScoreKind


def encode_query(backend: EmbeddingBackend, query: str) -> np.ndarray:
    """Encode one research-interest string into a normalised query vector."""
    batch = backend.encode_queries([query])
    return cast("np.ndarray[Any, Any]", batch.vectors[0])


def search(
    session: Session,
    query_vector: Sequence[float] | np.ndarray,
    *,
    model_key: str,
    limit: int = 20,
    search_filters: filter_module.SearchFilters | None = None,
    query_text: str = "",
) -> RetrievalResult:
    """Rank papers by cosine similarity to `query_vector` under `model_key`."""
    started = time.perf_counter()
    active_filters = search_filters or filter_module.SearchFilters()

    vector = np.asarray(query_vector, dtype=np.float32)
    distance = PaperEmbedding.embedding.cosine_distance(vector)
    similarity = (1.0 - distance).label("score")

    statement = (
        common.ranking_select(similarity)
        .join(PaperEmbedding, PaperEmbedding.paper_id == Paper.id)
        .where(PaperEmbedding.model_key == model_key)
    )
    condition = filter_module.combined(active_filters)
    if condition is not None:
        statement = statement.where(condition)

    # Ordering by distance ascending rather than similarity descending keeps the
    # expression in the form an HNSW index can serve, should one be added later.
    statement = statement.order_by(distance.asc(), Paper.id).limit(limit)

    rows = session.execute(statement).all()
    hits = common.hits_from_ranked(session, rows, score_kind=ScoreKind.COSINE_SIMILARITY)

    return RetrievalResult(
        query=query_text,
        method="semantic",
        hits=hits,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        candidates_considered=len(hits),
        detail={
            "model_key": model_key,
            "exact": True,
            "filters": active_filters.describe(),
        },
    )


def search_text(
    session: Session,
    query: str,
    *,
    backend: EmbeddingBackend,
    model_key: str,
    limit: int = 20,
    search_filters: filter_module.SearchFilters | None = None,
) -> RetrievalResult:
    """Encode `query` and search. Convenience wrapper over encode_query + search."""
    vector = encode_query(backend, query)
    return search(
        session,
        vector,
        model_key=model_key,
        limit=limit,
        search_filters=search_filters,
        query_text=query,
    )
