"""Fusing lexical and semantic rankings.

Two methods are implemented and both are deterministic and inspectable, because
an unexplainable ranking cannot be debugged and cannot be defended:

**Reciprocal rank fusion** (default). Each method contributes `weight / (k +
rank)`. It uses only positions, so it needs no score calibration and cannot be
destabilised by one method's scores living on a different scale - which is
precisely the failure mode of naive score addition, given that ts_rank_cd and
cosine similarity have no common unit.

**Normalised weighted sum**. Min-max normalises each method's scores within its
own result list, then adds them. It preserves the *margin* between a strong and
a marginal match, which rank fusion discards. That extra information is only
worth having when the score distributions are well behaved, so it is offered but
not the default.

No learning-to-rank model, by design: with no relevance labels yet, a learned
ranker would be fitted to nothing, and the point of Phase 2 is to produce the
labels that would justify one.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from academious.retrieval import common
from academious.retrieval.types import RetrievalHit, RetrievalResult, ScoreKind


class FusionMethod(StrEnum):
    RRF = "rrf"
    WEIGHTED = "weighted"


#: The standard RRF constant. It damps the difference between the top positions
#: so that rank 1 in one method does not automatically outrank a paper both
#: methods placed in their top five.
DEFAULT_RRF_K = 60

DEFAULT_WEIGHTS: dict[str, float] = {"lexical": 1.0, "semantic": 1.0}


@dataclass(slots=True)
class _Accumulator:
    total: float = 0.0
    components: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.components is None:
            self.components = {}


def _rrf_contributions(
    results: Mapping[str, RetrievalResult], weights: Mapping[str, float], k: int
) -> dict[uuid.UUID, _Accumulator]:
    scores: dict[uuid.UUID, _Accumulator] = {}
    for method, result in results.items():
        weight = weights.get(method, 1.0)
        for hit in result.hits:
            accumulator = scores.setdefault(hit.paper_id, _Accumulator())
            contribution = weight / (k + hit.rank)
            accumulator.total += contribution
            accumulator.components[method] = contribution
    return scores


def _normalised_contributions(
    results: Mapping[str, RetrievalResult], weights: Mapping[str, float]
) -> dict[uuid.UUID, _Accumulator]:
    scores: dict[uuid.UUID, _Accumulator] = {}
    for method, result in results.items():
        if not result.hits:
            continue
        weight = weights.get(method, 1.0)
        values = [hit.score for hit in result.hits]
        low, high = min(values), max(values)
        span = high - low
        for hit in result.hits:
            # A method that returned one result, or all-equal scores, gives every
            # hit 1.0 rather than 0.0: it did rank them, it just did not
            # discriminate, and zeroing them would silently delete the method.
            normalised = 1.0 if span == 0 else (hit.score - low) / span
            accumulator = scores.setdefault(hit.paper_id, _Accumulator())
            contribution = weight * normalised
            accumulator.total += contribution
            accumulator.components[method] = contribution
    return scores


def fuse(
    session: Session,
    results: Mapping[str, RetrievalResult],
    *,
    limit: int = 20,
    method: FusionMethod = FusionMethod.RRF,
    weights: Mapping[str, float] | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    query: str = "",
) -> RetrievalResult:
    """Combine component rankings into one. Component results are not re-queried."""
    started = time.perf_counter()
    active_weights = dict(weights or DEFAULT_WEIGHTS)

    if method is FusionMethod.RRF:
        scores = _rrf_contributions(results, active_weights, rrf_k)
        score_kind = ScoreKind.RRF
    else:
        scores = _normalised_contributions(results, active_weights)
        score_kind = ScoreKind.WEIGHTED

    # Ties broken by paper id so the same inputs always produce the same page.
    ordered = sorted(scores.items(), key=lambda item: (-item[1].total, str(item[0])))[:limit]
    metadata = common.hydrate(session, [paper_id for paper_id, _ in ordered])

    hits: list[RetrievalHit] = []
    for index, (paper_id, accumulator) in enumerate(ordered):
        row = metadata.get(paper_id)
        if row is None:
            # The paper was deleted between the component query and now.
            continue
        hit = common.row_to_hit(
            row, rank=index + 1, score=accumulator.total, score_kind=score_kind
        )
        hits.append(
            RetrievalHit(
                paper_id=hit.paper_id,
                rank=hit.rank,
                score=hit.score,
                score_kind=hit.score_kind,
                title=hit.title,
                canonical_doi=hit.canonical_doi,
                published_date=hit.published_date,
                is_preprint=hit.is_preprint,
                is_peer_reviewed=hit.is_peer_reviewed,
                oa_status=hit.oa_status,
                retraction_status=hit.retraction_status,
                venue_name=hit.venue_name,
                topics=hit.topics,
                components=dict(accumulator.components),
            )
        )

    return RetrievalResult(
        query=query,
        method="hybrid",
        hits=hits,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        candidates_considered=len(scores),
        detail={
            "fusion": method.value,
            "weights": active_weights,
            "rrf_k": rrf_k if method is FusionMethod.RRF else None,
            "components": {
                name: {"hits": len(result.hits), "elapsed_ms": result.elapsed_ms}
                for name, result in results.items()
            },
        },
    )
