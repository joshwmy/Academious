"""The source connector contract.

Every scholarly source implements two independently testable halves:

    harvest()   the only code that touches the network. Yields pages of raw,
                unmodified payloads plus a cursor for resumption.
    normalise() a pure function from one raw payload to a PaperCandidate.
                No I/O, no clock, no randomness - so it can be tested against
                recorded fixtures with no network access at all.

That split is what makes the "tests must not require internet" requirement
achievable rather than aspirational.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from academious.core.ids import IdType


@dataclass(frozen=True, slots=True)
class RawRecord:
    """A payload exactly as the source returned it, plus provenance."""

    source_key: str
    source_id: str
    payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class HarvestPage:
    """One page of results and the cursor needed to fetch the next."""

    records: list[RawRecord]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CandidateIdentifier:
    id_type: IdType
    value: str


@dataclass(slots=True)
class CandidateAuthor:
    name: str
    position: int
    orcid: str | None = None
    openalex_id: str | None = None
    affiliations: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "orcid": self.orcid,
            "openalex_id": self.openalex_id,
            "affiliations": self.affiliations,
        }


@dataclass(slots=True)
class CandidateLocation:
    url: str
    host_type: str = "unknown"
    version: str = "unknown"
    pdf_url: str | None = None
    licence: str | None = None
    source_name: str | None = None
    is_best: bool = False


@dataclass(slots=True)
class CandidateVenue:
    name: str
    openalex_id: str | None = None
    issn_l: str | None = None
    publisher: str | None = None
    venue_type: str | None = None
    is_oa: bool = False


@dataclass(slots=True)
class PaperCandidate:
    """A normalised paper, not yet reconciled against the canonical corpus."""

    source_key: str
    source_id: str
    title: str
    identifiers: list[CandidateIdentifier] = field(default_factory=list)
    abstract: str | None = None
    authors: list[CandidateAuthor] = field(default_factory=list)
    venue: CandidateVenue | None = None
    published_date: date | None = None
    first_seen_online: date | None = None
    is_preprint: bool = False
    is_peer_reviewed: bool = False
    work_type: str | None = None
    language: str | None = None
    topics: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    citation_count: int | None = None
    oa_status: str = "unknown"
    locations: list[CandidateLocation] = field(default_factory=list)
    is_retracted_hint: bool = False
    # Published DOI this record is a preprint of, when the source states it.
    preprint_of_doi: str | None = None

    def identifier_values(self, id_type: IdType) -> list[str]:
        return [i.value for i in self.identifiers if i.id_type == id_type]

    @property
    def primary_doi(self) -> str | None:
        values = self.identifier_values(IdType.DOI)
        return values[0] if values else None


@runtime_checkable
class SourceConnector(Protocol):
    """Implemented by every source module."""

    key: str

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        """Yield pages of raw records changed since `since`, resuming at `cursor`."""
        ...

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        """Pure. Returns None when the record is out of scope (see docs/ingestion.md)."""
        ...
