"""Filters applied to every retrieval method, before ranking.

Filtering happens in SQL against `paper`, not in Python against a result page.
Filtering after ranking would silently shrink a page of ten results to three and
make recall depend on how aggressive the filter is - which is exactly the bug
that makes date-filtered search feel broken.

Retraction handling is the one filter with an opinionated default. A retracted
paper is not merely lower quality; the literature has withdrawn the claim. It is
excluded from ordinary discovery unless explicitly asked for. Corrections and
expressions of concern are a different matter: those papers stand, with a
caveat, so they are returned and their status travels with them on the hit for
the caller to surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, select

from academious.db.models.paper import Paper, RetractionStatus
from academious.db.models.support import SourceRecord


class RetractionPolicy(StrEnum):
    #: Default. Retracted papers are hidden; corrected and concern-flagged
    #: papers are returned with their status attached.
    EXCLUDE_RETRACTED = "exclude_retracted"
    #: Everything, retractions included. For retraction-aware tooling and for
    #: someone who is deliberately looking for the withdrawn record.
    INCLUDE_ALL = "include_all"
    #: Only papers carrying some notice. For auditing, not for discovery.
    ONLY_FLAGGED = "only_flagged"


class PreprintPolicy(StrEnum):
    ANY = "any"
    ONLY_PREPRINTS = "only_preprints"
    EXCLUDE_PREPRINTS = "exclude_preprints"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Metadata constraints. Every field defaults to "no constraint"."""

    published_from: date | None = None
    published_to: date | None = None
    #: Source keys as recorded on source_record: openalex, arxiv, biorxiv.
    sources: tuple[str, ...] = ()
    preprints: PreprintPolicy = PreprintPolicy.ANY
    peer_reviewed_only: bool = False
    open_access_only: bool = False
    #: Normalised subject field slugs from ingest.taxonomy, e.g.
    #: "computer-science". Matched against the derived `paper.fields` column,
    #: so one filter reaches papers classified by any source's vocabulary.
    fields: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    retraction: RetractionPolicy = RetractionPolicy.EXCLUDE_RETRACTED

    def describe(self) -> dict[str, Any]:
        """Flat, JSON-safe description, for recording alongside benchmark runs."""
        return {
            "published_from": self.published_from.isoformat() if self.published_from else None,
            "published_to": self.published_to.isoformat() if self.published_to else None,
            "sources": list(self.sources),
            "preprints": self.preprints.value,
            "peer_reviewed_only": self.peer_reviewed_only,
            "open_access_only": self.open_access_only,
            "fields": list(self.fields),
            "languages": list(self.languages),
            "retraction": self.retraction.value,
        }


#: OA statuses that mean a legally readable copy is known to exist. "closed" and
#: "unknown" do not; they are the reason this is an allowlist and not a !=.
OPEN_ACCESS_STATUSES = ("gold", "green", "hybrid", "bronze", "diamond")

FLAGGED_STATUSES = (
    RetractionStatus.RETRACTED.value,
    RetractionStatus.CORRECTED.value,
    RetractionStatus.CONCERN.value,
)


def build_conditions(filters: SearchFilters) -> list[ColumnElement[bool]]:
    """Translate filters into WHERE clauses over `paper`."""
    conditions: list[ColumnElement[bool]] = []

    if filters.published_from is not None:
        conditions.append(Paper.published_date >= filters.published_from)
    if filters.published_to is not None:
        conditions.append(Paper.published_date <= filters.published_to)

    if filters.preprints is PreprintPolicy.ONLY_PREPRINTS:
        conditions.append(Paper.is_preprint.is_(True))
    elif filters.preprints is PreprintPolicy.EXCLUDE_PREPRINTS:
        conditions.append(Paper.is_preprint.is_(False))

    if filters.peer_reviewed_only:
        conditions.append(Paper.is_peer_reviewed.is_(True))

    if filters.open_access_only:
        conditions.append(Paper.oa_status.in_(OPEN_ACCESS_STATUSES))

    if filters.languages:
        conditions.append(Paper.language.in_(filters.languages))

    if filters.sources:
        # Which sources a paper was seen in lives on source_record, because one
        # canonical paper is routinely assembled from several of them.
        conditions.append(
            exists(
                select(SourceRecord.id).where(
                    SourceRecord.paper_id == Paper.id,
                    SourceRecord.source_key.in_(filters.sources),
                )
            )
        )

    if filters.fields:
        # Array overlap against the derived column, not JSONB containment
        # against topics[].field. Only OpenAlex records carry a field on the
        # topic, so containment filtered 43% of the corpus and silently hid the
        # rest; `paper.fields` is normalised across all four source
        # vocabularies by ingest.taxonomy. GIN-indexed as ix_paper_fields.
        conditions.append(Paper.fields.op("&&")(_text_array(list(filters.fields))))

    match filters.retraction:
        case RetractionPolicy.EXCLUDE_RETRACTED:
            conditions.append(Paper.retraction_status != RetractionStatus.RETRACTED.value)
        case RetractionPolicy.ONLY_FLAGGED:
            conditions.append(Paper.retraction_status.in_(FLAGGED_STATUSES))
        case RetractionPolicy.INCLUDE_ALL:
            pass

    return conditions


def _text_array(value: list[str]) -> Any:
    from sqlalchemy import Text, cast, literal
    from sqlalchemy.dialects.postgresql import ARRAY

    return cast(literal(value, ARRAY(Text)), ARRAY(Text))


def combined(filters: SearchFilters) -> ColumnElement[bool] | None:
    conditions = build_conditions(filters)
    if not conditions:
        return None
    return and_(*conditions)
