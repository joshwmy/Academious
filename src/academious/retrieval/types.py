"""Result shapes shared by every retrieval method.

Scores are reported in each method's own units and labelled with `score_kind`.
They are deliberately not rescaled into a common 0-100 "relevance" number:
cosine similarity, ts_rank_cd and reciprocal rank fusion are not measurements of
the same thing, and mapping them onto a percentage would invent a precision the
system does not have. Ranking is the product; the score is a diagnostic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any


class ScoreKind:
    COSINE_SIMILARITY = "cosine_similarity"
    TS_RANK_CD = "ts_rank_cd"
    RRF = "reciprocal_rank_fusion"
    WEIGHTED = "normalised_weighted_sum"


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    paper_id: uuid.UUID
    rank: int
    score: float
    score_kind: str

    title: str = ""
    canonical_doi: str | None = None
    published_date: date | None = None
    is_preprint: bool = False
    is_peer_reviewed: bool = False
    oa_status: str = "unknown"
    retraction_status: str = "none"
    venue_name: str | None = None
    topics: list[dict[str, Any]] = field(default_factory=list)

    #: Per-method contributions, populated by hybrid ranking so a position can be
    #: explained without re-running the components.
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query: str
    method: str
    hits: list[RetrievalHit]
    elapsed_ms: float
    #: How many distinct papers this method put into the ranking. For a
    #: component method the SQL LIMIT is applied in the database, so this
    #: equals len(hits) and is not a count of everything scanned. For hybrid
    #: it is the size of the fused pool before truncation, which is the one
    #: case where it says something len(hits) does not.
    candidates_considered: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def paper_ids(self) -> list[uuid.UUID]:
        return [hit.paper_id for hit in self.hits]

    def __len__(self) -> int:
        return len(self.hits)
