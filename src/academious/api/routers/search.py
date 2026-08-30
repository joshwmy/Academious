"""Public search over the Phase 2 retrieval service.

This router is a boundary, not a ranker. It validates input, bounds cost, calls
the retrieval service with server-controlled configuration, and projects the
result. It chooses no weights, fuses nothing and reorders nothing: the ranking a
caller receives is the ranking the service returned, in the order it returned
it, which is what makes the Phase 2 benchmark evidence about this endpoint and
not merely about a library underneath it.

Retrieval configuration is not addressable from the query string. The method,
the embedding profile, fusion constants and the candidate depth are all
settings. A caller who could pass `method=` or `model_key=` could select an
experimental profile, make the expensive method run on demand, or read internal
implementation state out of the response - none of which are product features.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from academious.api import repository, schemas
from academious.api.concurrency import search_gate
from academious.api.dependencies import get_retrieval_service, get_session
from academious.api.limits import limiter, search_limit
from academious.api.routers.papers import _summary
from academious.core.config import get_settings
from academious.core.logging import get_logger
from academious.retrieval.service import RetrievalService

router = APIRouter(tags=["search"])
log = get_logger(__name__)

#: Starlette renamed its 422 constant; the number is stable and unambiguous.
UNPROCESSABLE = 422

settings = get_settings()

#: Control characters have no meaning in a research query and every meaning in a
#: log file. They are replaced with a space rather than deleted: deleting them
#: welds the words on either side together, so "graph<newline>networks" would be
#: searched as "graphnetworks" and quietly return nothing.
_CONTROL_CHARACTERS = dict.fromkeys(range(32), " ")
_CONTROL_CHARACTERS[127] = " "


def normalise_query(raw: str) -> str:
    """Collapse whitespace and drop control characters.

    Whitespace collapsing makes `graph  neural networks` and `graph neural
    networks` the same query, which callers reasonably expect. Replacing control
    characters is a log-safety measure: a newline in a query string is how a
    caller forges a second log line.
    """
    return " ".join(raw.translate(_CONTROL_CHARACTERS).split())


@router.get(
    "/search",
    summary="Search papers by research interest",
    response_model=schemas.SearchResponse,
    responses={
        422: {"model": schemas.ErrorResponse, "description": "Missing, blank or oversized query"},
        429: {"model": schemas.ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": schemas.ErrorResponse, "description": "Search is at capacity"},
    },
    description=(
        "Ranked papers for a description of a research interest. Results are ordered by "
        "relevance; `rank` is the ordering and is the only relevance signal exposed, because "
        "the underlying methods score in incomparable units. The retrieval method is server "
        "configuration and is deliberately not selectable per request."
    ),
)
@limiter.limit(search_limit)
def search(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=settings.api_max_query_length,
            description="What you are looking for, in your own words",
        ),
    ],
    limit: Annotated[
        int, Query(ge=1, le=settings.api_max_search_results, description="Results to return")
    ] = settings.api_default_page_size,
) -> schemas.SearchResponse:
    query = normalise_query(q)
    if not query:
        # `min_length` rejects "", but "   " and "\n" survive it and would reach
        # the tokeniser as an empty string.
        from fastapi import HTTPException

        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail="q: query must contain at least one non-whitespace character",
        )

    active = get_settings()
    # Raises CapacityExceededError -> 503 rather than queueing without bound.
    with search_gate.acquire():
        result = service.search_by_interest(
            session, query, limit=limit, method=active.retrieval_default_method
        )

    ranked_ids = result.paper_ids()
    summaries = repository.summaries_for_ids(session, ranked_ids)

    hits: list[schemas.SearchHit] = []
    for hit in result.hits:
        row = summaries.get(hit.paper_id)
        if row is None:
            # Deleted between ranking and projection. Dropping it keeps the page
            # honest; a placeholder would show a paper that no longer exists.
            continue
        hits.append(schemas.SearchHit(rank=len(hits) + 1, paper=_summary(row)))

    log.info("api.search", query_length=len(query), results=len(hits))
    return schemas.SearchResponse(
        query=query, count=len(hits), limit=limit, results=hits
    )
