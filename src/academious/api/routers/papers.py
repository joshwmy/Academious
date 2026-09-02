"""Public paper browsing and paper detail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy.orm import Session

from academious.api import repository, schemas
from academious.api.dependencies import get_session
from academious.api.limits import limiter, read_limit
from academious.core.config import get_settings
from academious.ingest import taxonomy
from academious.retrieval.filters import (
    OPEN_ACCESS_STATUSES,
    PreprintPolicy,
    SearchFilters,
)

router = APIRouter(tags=["papers"])

settings = get_settings()

NOT_FOUND = "Paper not found"


def validated_fields(field: list[str] | None) -> tuple[str, ...]:
    """Reject a field slug that is not in the vocabulary.

    An unknown slug is refused rather than ignored. Ignoring it would answer a
    filtered request with an unfiltered page, and answering it with an empty
    page would make a typo indistinguishable from a field nothing is published
    in - a caller cannot tell those apart, so the server says which it is.
    """
    unknown = sorted({slug for slug in field or () if not taxonomy.is_field(slug)})
    if unknown:
        raise HTTPException(
            # The number, not `status.HTTP_422_*`: Starlette renamed that
            # constant and both spellings warn on one version or the other.
            status_code=422,
            detail=(
                f"field: unknown value(s) {', '.join(unknown)}. "
                "GET /fields lists the vocabulary"
            ),
        )
    return tuple(dict.fromkeys(field or ()))


def _summary(row: object) -> schemas.PaperSummary:
    return schemas.PaperSummary(
        id=row.id,  # type: ignore[attr-defined]
        title=row.title,  # type: ignore[attr-defined]
        abstract_preview=schemas.abstract_preview(row.abstract),  # type: ignore[attr-defined]
        authors=schemas.authors_from_json(row.authors),  # type: ignore[attr-defined]
        published_date=row.published_date,  # type: ignore[attr-defined]
        published_year=row.published_year,  # type: ignore[attr-defined]
        venue=row.venue_name,  # type: ignore[attr-defined]
        doi=row.canonical_doi,  # type: ignore[attr-defined]
        is_preprint=row.is_preprint,  # type: ignore[attr-defined]
        is_peer_reviewed=row.is_peer_reviewed,  # type: ignore[attr-defined]
        open_access_status=row.oa_status,  # type: ignore[attr-defined]
        retraction_status=row.retraction_status,  # type: ignore[attr-defined]
        topics=schemas.topics_from_json(row.topics),  # type: ignore[attr-defined]
        fields=list(row.fields or []),  # type: ignore[attr-defined]
        citation_count=row.citation_count,  # type: ignore[attr-defined]
    )


@router.get(
    "/fields",
    summary="List subject fields",
    response_model=schemas.FieldsResponse,
    responses={429: {"model": schemas.ErrorResponse, "description": "Rate limit exceeded"}},
    description=(
        "The subject-field vocabulary the `field` filter accepts, with the number of papers "
        "in each. Fields are normalised across every source: OpenAlex supplies them directly, "
        "arXiv archives and bioRxiv/medRxiv categories are mapped onto the same vocabulary, "
        "and papers classified only in MeSH carry no field. `papers_without_field` is how "
        "many papers no field filter can reach."
    ),
)
@limiter.limit(read_limit)
def list_fields(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> schemas.FieldsResponse:
    counts, without_field = repository.field_counts(session)
    return schemas.FieldsResponse(
        fields=[
            schemas.FieldSummary(
                slug=entry["slug"],
                label=entry["label"],
                paper_count=counts.get(entry["slug"], 0),
            )
            for entry in taxonomy.describe()
        ],
        papers_without_field=without_field,
    )


@router.get(
    "/papers",
    summary="Browse papers",
    response_model=schemas.PaperPage,
    responses={
        422: {"model": schemas.ErrorResponse, "description": "Invalid pagination or filter"},
        429: {"model": schemas.ErrorResponse, "description": "Rate limit exceeded"},
    },
    description=(
        "A page of papers, most recently published first with the paper id as a stable "
        "tie-breaker, so paging never repeats or skips a row. Filters are applied in SQL "
        "before pagination, so `total` counts what matched, not what was returned."
    ),
)
@limiter.limit(read_limit)
def list_papers(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=settings.api_max_page_size, description="Papers per page")
    ] = settings.api_default_page_size,
    offset: Annotated[
        int, Query(ge=0, le=settings.api_max_offset, description="Papers to skip")
    ] = 0,
    source: Annotated[
        list[str] | None,
        Query(description="Restrict to papers seen in these sources, e.g. arxiv, biorxiv"),
    ] = None,
    preprints: Annotated[
        PreprintPolicy, Query(description="Include, exclude or require preprints")
    ] = PreprintPolicy.ANY,
    peer_reviewed: Annotated[bool, Query(description="Only peer-reviewed papers")] = False,
    open_access: Annotated[
        bool, Query(description="Only papers with a known open-access copy")
    ] = False,
    field: Annotated[
        list[str] | None,
        Query(description="Restrict to these subject fields, e.g. computer-science"),
    ] = None,
) -> schemas.PaperPage:
    search_filters = SearchFilters(
        sources=tuple(source or ()),
        preprints=preprints,
        peer_reviewed_only=peer_reviewed,
        open_access_only=open_access,
        fields=validated_fields(field),
    )
    rows, total = repository.list_papers(
        session, limit=limit, offset=offset, search_filters=search_filters
    )
    results = [_summary(row) for row in rows]
    return schemas.PaperPage(
        page=schemas.PageInfo(
            limit=limit,
            offset=offset,
            total=total,
            returned=len(results),
            has_more=offset + len(results) < total,
        ),
        results=results,
    )


@router.get(
    "/papers/{paper_id}",
    summary="Get one paper",
    response_model=schemas.PaperDetail,
    responses={
        404: {"model": schemas.ErrorResponse, "description": "No such paper"},
        422: {"model": schemas.ErrorResponse, "description": "Malformed paper id"},
        429: {"model": schemas.ErrorResponse, "description": "Rate limit exceeded"},
    },
    description=(
        "One paper in full, addressed by its Academious UUID - the identifier `/papers` and "
        "`/search` return. DOIs and arXiv ids are reported in `identifiers` but are not "
        "accepted here: a DOI identifies a work, and several corpus papers can share one."
    ),
)
@limiter.limit(read_limit)
def get_paper(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    paper_id: Annotated[uuid.UUID, Path(description="Academious paper UUID")],
) -> schemas.PaperDetail:
    row = repository.get_paper(session, paper_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    summary = _summary(row)
    location = repository.best_open_access_location(session, paper_id)
    open_access = schemas.OpenAccess(
        status=row.oa_status,
        is_open=row.oa_status in OPEN_ACCESS_STATUSES,
        url=location.url if location else None,
        pdf_url=location.pdf_url if location else None,
        licence=(location.licence if location else None) or row.fulltext_licence,
    )
    return schemas.PaperDetail(
        **summary.model_dump(),
        abstract=row.abstract,
        language=row.language,
        work_type=row.work_type,
        identifiers=repository.identifiers_for(session, paper_id),
        open_access=open_access,
        retraction_notice_url=row.retraction_notice_url,
    )
