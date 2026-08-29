"""The retrieval entry point: search the corpus by research interest.

One object owns the model_key and the backend so that callers cannot
accidentally search vectors from one model with a query encoded by another - a
mistake that produces plausible-looking nonsense rather than an error.

Hybrid retrieval pulls a deeper candidate pool from each component than it
returns. Fusion can only reorder what it is given, so a paper that lexical
search ranks 40th and semantic search ranks 3rd is only reachable if lexical
actually handed over 40 results.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from academious.core.logging import get_logger
from academious.embeddings.backend import EmbeddingBackend
from academious.retrieval import hybrid, lexical, semantic
from academious.retrieval.filters import SearchFilters
from academious.retrieval.hybrid import FusionMethod
from academious.retrieval.types import RetrievalResult

log = get_logger(__name__)

#: Candidates each component contributes to fusion, as a multiple of the page
#: size, with a floor for small pages.
POOL_MULTIPLIER = 5
MIN_POOL = 50


class Method:
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


ALL_METHODS = (Method.LEXICAL, Method.SEMANTIC, Method.HYBRID)


def pool_size(limit: int) -> int:
    return max(limit * POOL_MULTIPLIER, MIN_POOL)


@dataclass(slots=True)
class RetrievalService:
    backend: EmbeddingBackend
    model_key: str

    def search_by_interest(
        self,
        session: Session,
        query: str,
        *,
        limit: int = 20,
        search_filters: SearchFilters | None = None,
        method: str = Method.HYBRID,
        fusion: FusionMethod = FusionMethod.RRF,
    ) -> RetrievalResult:
        """Return papers relevant to a description of a research interest."""
        active_filters = search_filters or SearchFilters()

        if method == Method.LEXICAL:
            return lexical.search(
                session, query, limit=limit, search_filters=active_filters
            )

        if method == Method.SEMANTIC:
            return semantic.search_text(
                session,
                query,
                backend=self.backend,
                model_key=self.model_key,
                limit=limit,
                search_filters=active_filters,
            )

        if method != Method.HYBRID:
            raise ValueError(f"unknown retrieval method {method!r}; expected one of {ALL_METHODS}")

        pool = pool_size(limit)
        components = {
            Method.LEXICAL: lexical.search(
                session, query, limit=pool, search_filters=active_filters
            ),
            Method.SEMANTIC: semantic.search_text(
                session,
                query,
                backend=self.backend,
                model_key=self.model_key,
                limit=pool,
                search_filters=active_filters,
            ),
        }
        return hybrid.fuse(session, components, limit=limit, method=fusion, query=query)

    def search_all_methods(
        self,
        session: Session,
        query: str,
        *,
        limit: int = 20,
        search_filters: SearchFilters | None = None,
        fusion: FusionMethod = FusionMethod.RRF,
    ) -> dict[str, RetrievalResult]:
        """Run every method over one query. The evaluation harness needs all three."""
        active_filters = search_filters or SearchFilters()
        pool = pool_size(limit)

        lexical_result = lexical.search(
            session, query, limit=pool, search_filters=active_filters
        )
        semantic_result = semantic.search_text(
            session,
            query,
            backend=self.backend,
            model_key=self.model_key,
            limit=pool,
            search_filters=active_filters,
        )
        fused = hybrid.fuse(
            session,
            {Method.LEXICAL: lexical_result, Method.SEMANTIC: semantic_result},
            limit=limit,
            method=fusion,
            query=query,
        )
        return {
            Method.LEXICAL: _truncate(lexical_result, limit),
            Method.SEMANTIC: _truncate(semantic_result, limit),
            Method.HYBRID: fused,
        }


def _truncate(result: RetrievalResult, limit: int) -> RetrievalResult:
    """Cut a deep pool back to the page size without re-querying."""
    if len(result.hits) <= limit:
        return result
    return RetrievalResult(
        query=result.query,
        method=result.method,
        hits=result.hits[:limit],
        elapsed_ms=result.elapsed_ms,
        candidates_considered=result.candidates_considered,
        detail=result.detail,
    )
