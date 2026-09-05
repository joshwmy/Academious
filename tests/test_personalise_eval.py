"""The recommendation benchmark, and the discipline it has to keep.

The interesting tests here are about what the harness *refuses* to report.
`evaluation.md` section 1 says nothing fabricates ground truth, and a feed
evaluator is where that is easiest to break by accident: every ranked list looks
scoreable, and every scoring formula treats an unjudged paper as irrelevant. A
number produced that way is not a small measurement, it is a confident wrong one.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
import pytest

from academious.eval import profiles as profile_set
from academious.eval.recommend import ProfileRun, describe_feed, render, score_feed
from academious.personalise.candidates import CandidateBudget
from academious.personalise.features import PaperFacts
from academious.personalise.feed import FeedConfig, build_feed
from academious.personalise.profile import EncodedProfile, InterestProfile
from academious.personalise.sources import ExactMatchSource, InMemorySemanticSource

TODAY = date(2026, 9, 5)
DIMENSIONS = 8


# --- the profile set ----------------------------------------------------------


def test_every_benchmark_profile_is_constructible_and_distinct():
    assert len(profile_set.PROFILES) == 6
    assert len({p.id for p in profile_set.PROFILES}) == 6
    assert len({p.shape for p in profile_set.PROFILES}) == 6
    for benchmark in profile_set.PROFILES:
        assert benchmark.intent, f"{benchmark.id} does not say what it probes"
        assert benchmark.profile.positive, f"{benchmark.id} has nothing to rank towards"


def test_the_generalist_profile_would_expose_an_averaged_vector():
    """The profile whose whole job is to fail if interests are ever merged."""
    generalist = profile_set.get("rec-02")
    assert len(generalist.profile.positive) == 3
    assert len(generalist.expect_represented) == 3


def test_a_profile_can_consist_only_of_ticked_boxes():
    """Cold start: someone who wrote no free text still has a usable profile."""
    boxes = profile_set.get("rec-06")
    assert not boxes.profile.semantic(), "nothing to encode"
    assert boxes.profile.positive, "but still rankable"


def test_no_benchmark_profile_carries_relevance_judgments():
    """Ground truth belongs in a judgment file a person wrote, not in code."""
    for benchmark in profile_set.PROFILES:
        assert not hasattr(benchmark, "relevant_papers")
        assert not hasattr(benchmark, "grades")


# --- what the harness refuses to report ---------------------------------------


def test_quality_metrics_are_withheld_when_nothing_has_been_judged(corpus):
    """Absence, not zero. A zero reads as 'the feed was bad'."""
    assert score_feed(_feed(corpus), {}) is None


def test_quality_metrics_are_withheld_when_no_feed_item_has_been_judged(corpus):
    assert score_feed(_feed(corpus), {uuid.uuid4(): 3}) is None


def test_a_partially_judged_feed_is_scored_but_marked_unreportable(corpus):
    """The number exists for a developer; the report refuses to headline it."""
    feed = _feed(corpus)
    scored = score_feed(feed, {feed.items[0].paper_id: 3})

    assert scored is not None
    assert scored.judged_in_feed == 1
    assert scored.coverage < 1.0
    assert scored.is_reportable is False


def test_a_fully_judged_feed_is_reportable(corpus):
    feed = _feed(corpus)
    scored = score_feed(feed, {item.paper_id: 3 for item in feed.items})

    assert scored is not None and scored.is_reportable
    assert scored.ndcg[10] > 0.0
    assert scored.mrr == pytest.approx(1.0)


def test_the_report_says_so_when_it_has_measured_nothing(corpus):
    """The failure mode is a report that looks rigorous and contains no evidence."""
    feed = _feed(corpus)
    run = ProfileRun(
        profile_id="rec-01",
        shape="specialist",
        feed=feed,
        described=describe_feed(feed, profile_set.get("rec-01"), corpus, today=TODAY),
        scored=score_feed(feed, {}),
    )

    text = render([run])

    assert "No profile has a fully judged feed" in text
    assert "NDCG@10" not in text.split("Ranking quality")[1]


# --- description works with no ground truth at all ----------------------------


def test_a_feed_is_describable_before_anyone_judges_it(corpus):
    """Coverage, diversity, freshness: real questions, answerable today."""
    feed = _feed(corpus)
    described = describe_feed(feed, profile_set.get("rec-01"), corpus, today=TODAY)

    assert described.size == len(feed.items)
    assert 0.0 <= described.intra_list_diversity <= 1.0
    assert described.distinct_topics >= 1
    assert described.median_age_days is not None
    assert 0.0 <= described.share_within_fortnight <= 1.0
    assert 0.0 < described.max_topic_share <= 1.0


def test_an_empty_feed_describes_as_empty_rather_than_failing():
    benchmark = profile_set.get("rec-01")
    empty = build_feed(
        _encode(benchmark.profile), [], lambda ids: {}, today=TODAY, config=FeedConfig(limit=10)
    )
    described = describe_feed(empty, benchmark, {}, today=TODAY)

    assert described.size == 0
    assert described.interests_expected == len(benchmark.expect_represented)


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def corpus() -> dict[uuid.UUID, PaperFacts]:
    facts: dict[uuid.UUID, PaperFacts] = {}
    for index in range(30):
        paper_id = uuid.uuid4()
        axis = index % 4
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        vector[axis] = 0.95
        # The variation axis must not track the subject axis, or every paper on
        # a subject is bit-identical and the near-duplicate rule correctly
        # collapses the subject to one item.
        vector[4 + (index // 4) % 4] = 0.31
        facts[paper_id] = PaperFacts(
            paper_id=paper_id,
            vector=(vector / np.linalg.norm(vector)).astype(np.float32),
            feed_date=TODAY - timedelta(days=index),
            topic_ids=frozenset({f"T-{axis}"}),
            field_slugs=frozenset({"computer-science"}),
            is_peer_reviewed=index % 2 == 0,
            has_abstract=True,
        )
    return facts


def _encode(profile: InterestProfile) -> EncodedProfile:
    """Give every semantic interest a vector, deterministically.

    A stand-in for SPECTER2, in the spirit of the project's existing torch-free
    hashing backend: the job here is to exercise the harness, and a real model
    would make these tests slow and non-deterministic without making them say
    anything more.
    """
    vectors = []
    for position, _ in enumerate(profile.pending_encoding()):
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        vector[position % 4] = 1.0
        vectors.append(vector)
    return EncodedProfile(profile=profile.with_vectors(vectors), model_key="stub@v1")


def _feed(corpus: dict[uuid.UUID, PaperFacts]):
    benchmark = profile_set.get("rec-01")
    return build_feed(
        _encode(benchmark.profile),
        [InMemorySemanticSource(corpus), ExactMatchSource(corpus)],
        lambda ids: {pid: corpus[pid] for pid in ids if pid in corpus},
        today=TODAY,
        config=FeedConfig(limit=10, budget=CandidateBudget(total=100)),
    )
