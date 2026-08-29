"""IR metrics, checked against worked examples rather than against the system."""

from __future__ import annotations

import math
import uuid

import pytest

from academious.eval import metrics

A, B, C, D, E = (uuid.UUID(int=n) for n in range(1, 6))

# A: highly relevant, B: relevant, C: marginal, D: not relevant. E is unjudged.
GRADES = {A: 3, B: 2, C: 1, D: 0}


def test_precision_at_k_divides_by_k_not_by_results_returned():
    """A short result list does not get perfect precision for being short."""
    assert metrics.precision_at_k([A], GRADES, 5) == pytest.approx(0.2)


def test_precision_at_k_counts_only_grades_at_or_above_the_threshold():
    # A and B qualify; C is marginal and D is not relevant.
    assert metrics.precision_at_k([A, B, C, D], GRADES, 4) == pytest.approx(0.5)


def test_marginal_counts_when_the_threshold_is_lowered():
    assert metrics.precision_at_k(
        [A, B, C, D], GRADES, 4, threshold=metrics.MARGINAL
    ) == pytest.approx(0.75)


def test_recall_at_k_is_measured_against_the_judged_relevant_set():
    assert metrics.recall_at_k([A, D], GRADES, 2) == pytest.approx(0.5)
    assert metrics.recall_at_k([A, B], GRADES, 2) == pytest.approx(1.0)


def test_recall_is_zero_when_nothing_relevant_was_judged():
    assert metrics.recall_at_k([A], {D: 0}, 5) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_position():
    assert metrics.reciprocal_rank([D, C, B, A], GRADES) == pytest.approx(1 / 3)
    assert metrics.reciprocal_rank([A], GRADES) == pytest.approx(1.0)


def test_reciprocal_rank_is_zero_when_nothing_relevant_is_retrieved():
    assert metrics.reciprocal_rank([D, C], GRADES) == 0.0


def test_dcg_matches_the_exponential_formula():
    # grades 3 then 2: (2^3-1)/log2(2) + (2^2-1)/log2(3)
    expected = 7 / math.log2(2) + 3 / math.log2(3)
    assert metrics.dcg([3, 2]) == pytest.approx(expected)


def test_ndcg_is_one_for_the_ideal_ordering():
    assert metrics.ndcg_at_k([A, B, C, D], GRADES, 4) == pytest.approx(1.0)


def test_ndcg_penalises_a_reversed_ordering():
    assert metrics.ndcg_at_k([D, C, B, A], GRADES, 4) < 0.7


def test_unjudged_results_score_zero_gain_rather_than_being_skipped():
    with_unjudged = metrics.ndcg_at_k([E, A, B], GRADES, 3)
    without = metrics.ndcg_at_k([A, B, C], GRADES, 3)
    assert with_unjudged < without


def test_ndcg_is_zero_when_no_judgment_carries_gain():
    assert metrics.ndcg_at_k([A, B], {D: 0}, 2) == 0.0


@pytest.mark.parametrize("k", [0, -1])
def test_k_must_be_positive(k):
    with pytest.raises(ValueError, match="k must be positive"):
        metrics.precision_at_k([A], GRADES, k)


def test_mean_of_nothing_is_zero_not_an_error():
    assert metrics.mean([]) == 0.0
