"""Information-retrieval metrics.

Pure functions over ranked id lists and a mapping of graded relevance. No
database, no configuration, no I/O - so the arithmetic can be tested against
worked examples rather than against whatever the system happened to return.

Relevance is graded 0-3 rather than binary. NDCG needs the grades, and the
distinction between "on topic but peripheral" and "exactly what I meant" is the
distinction personalised discovery lives or dies on. Binary metrics threshold
the grades at RELEVANT.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence

#: Grades. A judge picks one per (query, paper).
NOT_RELEVANT = 0
MARGINAL = 1
RELEVANT = 2
HIGHLY_RELEVANT = 3

#: Grade at or above which a paper counts as relevant for the binary metrics.
BINARY_THRESHOLD = RELEVANT

Grades = Mapping[uuid.UUID, int]


def relevant_ids(grades: Grades, *, threshold: int = BINARY_THRESHOLD) -> set[uuid.UUID]:
    return {paper_id for paper_id, grade in grades.items() if grade >= threshold}


def precision_at_k(
    ranked: Sequence[uuid.UUID], grades: Grades, k: int, *, threshold: int = BINARY_THRESHOLD
) -> float:
    """Fraction of the top k that is relevant.

    The denominator is k, not len(ranked). A method that returned three results
    when ten were asked for has not achieved perfect precision by being quiet.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = relevant_ids(grades, threshold=threshold)
    hits = sum(1 for paper_id in ranked[:k] if paper_id in relevant)
    return hits / k


def recall_at_k(
    ranked: Sequence[uuid.UUID], grades: Grades, k: int, *, threshold: int = BINARY_THRESHOLD
) -> float:
    """Fraction of known-relevant papers found in the top k.

    This is recall *within the judged pool*, which is all any pooled evaluation
    can measure: a relevant paper that no method retrieved was never judged and
    is invisible here. It is comparable between methods evaluated over the same
    pool and is not an estimate of true corpus recall. See docs/evaluation.md.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = relevant_ids(grades, threshold=threshold)
    if not relevant:
        return 0.0
    found = sum(1 for paper_id in ranked[:k] if paper_id in relevant)
    return found / len(relevant)


def reciprocal_rank(
    ranked: Sequence[uuid.UUID], grades: Grades, *, threshold: int = BINARY_THRESHOLD
) -> float:
    """1/rank of the first relevant result, or 0.0 if there is none."""
    relevant = relevant_ids(grades, threshold=threshold)
    for position, paper_id in enumerate(ranked, start=1):
        if paper_id in relevant:
            return 1.0 / position
    return 0.0


def dcg(gains: Sequence[int]) -> float:
    """Discounted cumulative gain, exponential formulation."""
    return float(
        sum((2**gain - 1) / math.log2(position + 1) for position, gain in enumerate(gains, 1))
    )


def ndcg_at_k(ranked: Sequence[uuid.UUID], grades: Grades, k: int) -> float:
    """Normalised DCG at k against the best ordering the judgments allow.

    An unjudged id in the ranking scores 0. That is the standard pooled-
    evaluation assumption and it is conservative: it can only understate a
    method, never flatter one.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    actual = dcg([grades.get(paper_id, 0) for paper_id in ranked[:k]])
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0.0:
        return 0.0
    return actual / ideal


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
