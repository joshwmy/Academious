"""Measuring a feed, which is not the same as measuring a search result.

Two kinds of number here, and keeping them apart is the point.

**Descriptive metrics need no ground truth.** Interest coverage, intra-list
diversity, topic concentration, the freshness distribution, exploration spent -
all are properties of the feed itself, computable the moment one exists, and
each answers a real question: did the second interest get a look in, is the list
ten versions of one paper, is this secretly a date sort. They are always
reported.

**Quality metrics need a human, and are withheld until one has judged.**
`evaluation.md`'s rule is that nothing fabricates ground truth, and here it has
a sharper edge than in retrieval: it is tempting to treat "the ranker put it
first" as evidence the paper was right, which measures the system against
itself. NDCG, precision, recall and MRR appear only where a judgment file
supplies grades, and coverage is reported so a number computed over four judged
papers is not mistaken for one computed over forty.

The metric implementations are `eval/metrics.py`, unchanged and shared with
retrieval - a feed and a search result are both a ranked list of paper ids, and
that much genuinely is one problem.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from academious.eval import metrics
from academious.eval.profiles import BenchmarkProfile
from academious.personalise.features import PaperFacts
from academious.personalise.feed import FeedResult

#: Cut-offs reported for every quality metric. Ten is the feed a reader sees;
#: twenty is what a second screen would show.
DEPTHS = (5, 10, 20)


@dataclass(frozen=True, slots=True)
class FeedMetrics:
    """What a feed looks like, before anyone judges whether it is good.

    Every field is computable without ground truth, and each corresponds to a
    failure this architecture exists to prevent.
    """

    size: int = 0
    #: Items per matched interest. A specialist should concentrate; a
    #: generalist should not.
    interest_coverage: Mapping[str, int] = field(default_factory=dict)
    #: How many of the profile's interests earned at least one item.
    interests_represented: int = 0
    interests_expected: int = 0
    #: Mean pairwise dissimilarity. Near zero means ten versions of one paper.
    intra_list_diversity: float = 1.0
    #: Distinct topics across the feed, and the largest share one topic holds.
    distinct_topics: int = 0
    max_topic_share: float = 0.0
    #: Median age in days and the share within a fortnight. Together they say
    #: whether freshness works without the feed collapsing into a date sort.
    median_age_days: float | None = None
    share_within_fortnight: float = 0.0
    exploration_items: int = 0
    retracted_items: int = 0

    def represented_ratio(self) -> float:
        if not self.interests_expected:
            return 1.0
        return self.interests_represented / self.interests_expected


@dataclass(frozen=True, slots=True)
class QualityScores:
    """Judged metrics. Absent rather than zero when nothing has been judged."""

    judged_in_feed: int = 0
    feed_size: int = 0
    ndcg: Mapping[int, float] = field(default_factory=dict)
    precision: Mapping[int, float] = field(default_factory=dict)
    recall: Mapping[int, float] = field(default_factory=dict)
    mrr: float | None = None

    @property
    def coverage(self) -> float:
        """Share of the feed a human has actually looked at."""
        return self.judged_in_feed / self.feed_size if self.feed_size else 0.0

    @property
    def is_reportable(self) -> bool:
        """Whether these numbers mean anything yet.

        A metric over a feed with two of ten items judged is not a small
        measurement, it is a misleading one: every formula here scores the eight
        unjudged items as irrelevant.
        """
        return self.judged_in_feed > 0 and self.coverage >= 1.0


@dataclass(slots=True)
class ProfileRun:
    """One profile's feed, described and - where possible - scored."""

    profile_id: str
    shape: str
    feed: FeedResult
    described: FeedMetrics
    scored: QualityScores | None = None


def describe_feed(
    result: FeedResult,
    benchmark: BenchmarkProfile,
    facts: Mapping[uuid.UUID, PaperFacts],
    *,
    today: date,
) -> FeedMetrics:
    """Everything measurable about a feed with no human in the loop."""
    items = result.items
    expected = benchmark.expect_represented or tuple(
        interest.key for interest in benchmark.profile.positive
    )
    if not items:
        return FeedMetrics(interests_expected=len(expected))

    coverage = dict(result.diagnostics.interest_coverage)
    represented = sum(1 for key in expected if coverage.get(key, 0) > 0)

    topic_counts: dict[str, int] = {}
    ages: list[int] = []
    for item in items:
        known = facts.get(item.paper_id)
        if known is None:
            continue
        for topic in known.topic_ids:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if known.feed_date is not None:
            ages.append((today - known.feed_date).days)

    return FeedMetrics(
        size=len(items),
        interest_coverage=coverage,
        interests_represented=represented,
        interests_expected=len(expected),
        intra_list_diversity=result.diagnostics.intra_list_diversity,
        distinct_topics=len(topic_counts),
        max_topic_share=(max(topic_counts.values()) / len(items)) if topic_counts else 0.0,
        median_age_days=_median(ages),
        share_within_fortnight=(sum(1 for age in ages if age <= 14) / len(ages) if ages else 0.0),
        exploration_items=result.diagnostics.exploration_items,
        retracted_items=sum(1 for item in items if item.is_retracted),
    )


def score_feed(result: FeedResult, grades: Mapping[uuid.UUID, int]) -> QualityScores | None:
    """Judged metrics, or `None` when nothing in this feed has been judged.

    Returning `None` rather than zeros is the discipline: a zero reads as "the
    feed was bad" and an absence reads as "nobody has looked", and a report must
    never confuse the two.
    """
    if not grades or not result.items:
        return None

    ranked = result.paper_ids()
    judged = sum(1 for paper_id in ranked if paper_id in grades)
    if judged == 0:
        return None

    return QualityScores(
        judged_in_feed=judged,
        feed_size=len(ranked),
        ndcg={k: metrics.ndcg_at_k(ranked, grades, k) for k in DEPTHS},
        precision={k: metrics.precision_at_k(ranked, grades, k) for k in DEPTHS},
        recall={k: metrics.recall_at_k(ranked, grades, k) for k in DEPTHS},
        mrr=metrics.reciprocal_rank(ranked, grades),
    )


def render(runs: Sequence[ProfileRun]) -> str:
    """A report that is explicit about which half of it is a measurement."""
    lines: list[str] = ["", "Feed description (no ground truth required)", ""]
    lines.append(
        f"{'profile':<10} {'shape':<18} {'n':>3} {'ints':>6} {'div':>6} "
        f"{'topics':>7} {'top%':>6} {'age':>6} {'<14d':>6} {'expl':>5}"
    )
    for run in runs:
        described = run.described
        age = "-" if described.median_age_days is None else f"{described.median_age_days:.0f}"
        ratio = f"{described.interests_represented}/{described.interests_expected}"
        lines.append(
            f"{run.profile_id:<10} {run.shape:<18} {described.size:>3} {ratio:>6} "
            f"{described.intra_list_diversity:>6.3f} {described.distinct_topics:>7} "
            f"{described.max_topic_share:>6.2f} {age:>6} "
            f"{described.share_within_fortnight:>6.2f} {described.exploration_items:>5}"
        )

    reportable = [run for run in runs if run.scored and run.scored.is_reportable]
    partial = [run for run in runs if run.scored and not run.scored.is_reportable]

    lines += ["", "Ranking quality (human judgments)", ""]
    if not reportable:
        lines.append(
            "  No profile has a fully judged feed. Nothing is reported, rather "
            "than a number computed as if unjudged papers were irrelevant - see "
            "docs/evaluation.md section 1."
        )
    else:
        lines.append(f"{'profile':<10} {'NDCG@10':>8} {'P@10':>7} {'R@10':>7} {'MRR':>7}")
        for run in reportable:
            scored = run.scored
            assert scored is not None
            lines.append(
                f"{run.profile_id:<10} {scored.ndcg[10]:>8.3f} {scored.precision[10]:>7.3f} "
                f"{scored.recall[10]:>7.3f} {(scored.mrr or 0.0):>7.3f}"
            )

    if partial:
        lines += ["", "Withheld - feed not judged to depth:"]
        for run in partial:
            scored = run.scored
            assert scored is not None
            lines.append(f"  {run.profile_id}: {scored.judged_in_feed}/{scored.feed_size} judged")

    return "\n".join(lines)


def _median(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2
