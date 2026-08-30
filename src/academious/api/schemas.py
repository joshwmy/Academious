"""Public response schemas.

Every field the public API returns is named here. Nothing serialises an ORM
object, and nothing serialises `**row`: the corpus row carries operational
columns - embedding input hashes, ingestion timestamps, dedup blocking keys -
that a reader has no use for and that describe how the system works rather than
what the literature says. An allowlist is the only version of that boundary that
stays correct when a column is added later.

Scores are absent by design. Lexical `ts_rank_cd`, cosine similarity and
reciprocal-rank fusion are not measurements of the same quantity, and the API's
default method is configuration rather than contract, so a `score` field would
change meaning without the response shape changing. The ordering is the product;
`rank` carries it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Abstracts are long. A list response carries enough to judge relevance, and
#: the detail endpoint carries the whole thing.
ABSTRACT_PREVIEW_CHARS = 320


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    position: int | None = None
    orcid: str | None = None
    affiliations: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    label: str | None = None
    scheme: str | None = None


class OpenAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="OpenAlex OA status: gold, green, hybrid, bronze, closed…")
    is_open: bool = Field(description="Whether a legally readable copy is known to exist")
    url: str | None = Field(default=None, description="Best known open-access landing page")
    pdf_url: str | None = None
    licence: str | None = None


class PaperSummary(BaseModel):
    """One paper as it appears in a list or a search result."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    title: str
    abstract_preview: str | None = Field(
        default=None, description=f"First {ABSTRACT_PREVIEW_CHARS} characters of the abstract"
    )
    authors: list[Author] = Field(default_factory=list)
    published_date: date | None = None
    published_year: int | None = None
    venue: str | None = Field(default=None, description="Journal or repository name")
    doi: str | None = None
    is_preprint: bool = False
    is_peer_reviewed: bool = False
    open_access_status: str = "unknown"
    retraction_status: str = Field(
        default="none", description="none, corrected, concern or retracted"
    )
    topics: list[Topic] = Field(default_factory=list)
    citation_count: int | None = None


class PaperDetail(PaperSummary):
    """One paper in full, for a detail page."""

    abstract: str | None = None
    language: str | None = None
    work_type: str | None = None
    identifiers: dict[str, str] = Field(
        default_factory=dict, description="External identifiers keyed by type, e.g. doi, arxiv"
    )
    open_access: OpenAccess | None = None
    retraction_notice_url: str | None = None


class PageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int
    offset: int
    total: int = Field(description="Total papers matching the filters, ignoring pagination")
    returned: int
    has_more: bool


class PaperPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: PageInfo
    results: list[PaperSummary]


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(description="1-based position in the ranking")
    paper: PaperSummary


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="The query as searched, after whitespace normalisation")
    count: int
    limit: int
    results: list[SearchHit]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str


def abstract_preview(abstract: str | None) -> str | None:
    if not abstract:
        return None
    collapsed = " ".join(abstract.split())
    if len(collapsed) <= ABSTRACT_PREVIEW_CHARS:
        return collapsed
    return collapsed[:ABSTRACT_PREVIEW_CHARS].rstrip() + "…"


def authors_from_json(raw: list[dict[str, Any]] | None) -> list[Author]:
    """Project stored author objects onto the public shape.

    Stored authors carry upstream identifiers that are not part of this
    contract, so fields are read by name rather than splatted.
    """
    authors: list[Author] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        affiliations = [a for a in (entry.get("affiliations") or []) if isinstance(a, str)]
        position = entry.get("position")
        orcid = entry.get("orcid")
        authors.append(
            Author(
                name=name,
                position=position if isinstance(position, int) else None,
                orcid=orcid if isinstance(orcid, str) else None,
                affiliations=affiliations,
            )
        )
    return authors


def topics_from_json(raw: list[dict[str, Any]] | None) -> list[Topic]:
    topics: list[Topic] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        topics.append(
            Topic(
                id=entry.get("id") if isinstance(entry.get("id"), str) else None,
                label=entry.get("label") if isinstance(entry.get("label"), str) else None,
                scheme=entry.get("scheme") if isinstance(entry.get("scheme"), str) else None,
            )
        )
    return topics
