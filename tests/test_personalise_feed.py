"""The pipeline end to end, against the scenario this phase is judged by.

One synthetic corpus, one many-sided reader, and the properties a personalised
feed has to demonstrate before any of it is worth trusting. Each is a separate
test so a regression names itself rather than failing one opaque assertion about
a whole feed.

The corpus sits on orthogonal axes so "about RAG" is exact rather than
approximate. That is deliberate: these tests are about the *pipeline's*
decisions - what it retrieves, penalises, balances and explains - and a real
embedding would turn every assertion into a judgement about SPECTER2 instead.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
import pytest

from academious.personalise.candidates import CandidateBudget
from academious.personalise.features import PaperFacts
from academious.personalise.feed import FeedConfig, build_feed
from academious.personalise.profile import (
    EncodedProfile,
    Interest,
    InterestKind,
    InterestProfile,
    Polarity,
    Preferences,
)
from academious.personalise.ranking import DeterministicRanker, Weights
from academious.personalise.rerank import DiversityPolicy
from academious.personalise.sources import AdjacentSource, ExactMatchSource, InMemorySemanticSource

TODAY = date(2026, 9, 5)
DIMENSIONS = 10

# Topical axes of the synthetic corpus...
RAG, SYSTEMS, COMPBIO, IMAGEGEN, ADJACENT, UNRELATED = range(6)
#: ...and four axes of per-paper variation. Papers about one subject must be
#: *similar*, not identical: bit-identical siblings are near-duplicates, and the
#: duplicate rule would correctly collapse each subject to a single item,
#: leaving a feed too short to say anything about ranking. Two siblings here
#: differ on their variation axis and sit at cosine 0.90 - close, distinct.
VARIATION_AXES = range(6, DIMENSIONS)


def test_the_feed_ranks_the_readers_strong_interests_first(scenario):
    """RAG and systems papers lead, because that is what the reader asked for."""
    feed = _run(scenario)
    leaders = {item.matched_interest for item in feed.items[:4]}

    assert leaders & {"RAG", "AI systems"}, leaders
    assert feed.items[0].score > feed.items[-1].score


def test_a_moderate_interest_still_gets_representation(scenario):
    """Five thousand relevant papers is not an answer; neither is one topic."""
    feed = _run(scenario)
    represented = {item.matched_interest for item in feed.items}

    assert "Computational biology" in represented, represented
    assert len(represented) >= 3, "a multi-interest reader sees multiple interests"


def test_image_generation_papers_are_penalised_not_merely_absent(scenario):
    """An explicit negative must be visible in the arithmetic, not only the order."""
    feed = _run(scenario)
    disliked = [item for item in feed.items if item.scored.features["negative_affinity"] > 0.5]

    for item in disliked:
        assert item.scored.contributions["negative_affinity"] < 0.0

    ranks = [item.rank for item in disliked]
    assert not ranks or min(ranks) > 3, f"a disliked paper reached rank {min(ranks)}"


def test_fresh_work_is_favoured_without_the_feed_becoming_a_date_sort(scenario):
    """product.md: what deserves attention now, not what was published today."""
    feed = _run(scenario)
    dates = [scenario.facts[item.paper_id].feed_date for item in feed.items]

    assert dates[0] is not None
    assert dates != sorted(dates, reverse=True), "this is a ranking, not a date sort"
    recent = sum(1 for value in dates if value and (TODAY - value).days <= 30)
    assert recent >= len(dates) // 2, "but recency clearly matters"


def test_near_identical_papers_do_not_consume_the_list(scenario):
    """The corpus holds five copies of one RAG paper on a single axis."""
    feed = _run(scenario)
    duplicates = [item for item in feed.items if item.paper_id in scenario.duplicate_ids]

    assert len(duplicates) <= 2, f"{len(duplicates)} near-duplicates in a feed of ten"


def test_every_recommendation_can_say_why_it_is_there(scenario):
    """Without an LLM, and traceable to the argmax that produced the score."""
    feed = _run(scenario)

    for item in feed.items:
        assert item.reasons, f"rank {item.rank} has no reason"
        if item.matched_interest:
            assert any(item.matched_interest in reason for reason in item.reasons)


def test_the_feed_is_deterministic(scenario):
    """Same profile, same corpus, same order - or nothing downstream is measurable."""
    assert _run(scenario).paper_ids() == _run(scenario).paper_ids()


def test_changing_the_profile_changes_the_ranking_materially(scenario):
    """The test that says this is personalisation rather than decoration."""
    original = _run(scenario)
    flipped = _run(scenario, profile=_biology_first(scenario))

    assert original.paper_ids() != flipped.paper_ids()
    assert flipped.items[0].matched_interest == "Computational biology"


def test_exploration_is_capped_and_floored(scenario):
    """Adjacent work appears; noise does not, and it never takes over."""
    feed = _run(scenario, limit=10)
    exploration = [item for item in feed.items if item.is_exploration]

    assert len(exploration) <= 2, "at most the exploration share of ten"
    for item in exploration:
        assert item.score >= feed.items[0].score * 0.5, "cleared the relevance floor"
        assert "adjacent to your interests" in item.reasons


def test_no_account_or_persistent_identity_is_required(scenario):
    """The profile is a value. Nothing reaches a user table, because none exists."""
    assert not hasattr(scenario.profile.profile, "user_id")
    assert _run(scenario).items, "and a feed is produced anyway"


def test_a_blocked_topic_is_removed_rather_than_ranked_low(scenario):
    """Exclusion is a different outcome from a low score, and must stay so."""
    blocked = InterestProfile(
        interests=scenario.profile.profile.interests,
        preferences=scenario.profile.preferences,
        blocked_topics=frozenset({"T-imagegen"}),
    )
    feed = _run(scenario, profile=EncodedProfile(profile=blocked, model_key="specter2@v1"))

    assert all("T-imagegen" not in scenario.facts[item.paper_id].topic_ids for item in feed.items)
    assert feed.diagnostics.filtered_by_block > 0


def test_diagnostics_report_what_each_source_contributed(scenario):
    """A source earning no budget should be visible as such."""
    feed = _run(scenario)

    assert feed.diagnostics.candidates_considered > 0
    assert set(feed.diagnostics.source_contributions) <= {"semantic", "exact", "adjacent"}
    assert 0.0 <= feed.diagnostics.intra_list_diversity <= 1.0


def test_weights_are_data_so_the_trade_can_be_measured(scenario):
    """Turning freshness off must change the feed, or the weight means nothing."""
    default = _run(scenario)
    timeless = _run(scenario, ranker=DeterministicRanker(weights=Weights().replace(freshness=0.0)))

    assert default.paper_ids() != timeless.paper_ids()


# --- the scenario -------------------------------------------------------------


class _Scenario:
    """The reader and the corpus from the phase's success criteria."""

    def __init__(self) -> None:
        self.facts: dict[uuid.UUID, PaperFacts] = {}
        self.duplicate_ids: set[uuid.UUID] = set()

        # Five *bit-identical* RAG papers - a preprint and its mirrors. The
        # case diversity exists to survive, and the only exactly-duplicated
        # group in the corpus.
        for index in range(5):
            self.duplicate_ids.add(
                self._add(
                    None,
                    vector=_basis(RAG),
                    days_ago=index,
                    topics={"T-rag"},
                    peer_reviewed=True,
                )
            )

        for index in range(6):
            self._add(RAG, days_ago=index * 2 + 1, topics={"T-rag"}, peer_reviewed=True)
        for index in range(6):
            self._add(SYSTEMS, days_ago=index * 3, topics={"T-systems"}, peer_reviewed=True)
        for index in range(5):
            self._add(COMPBIO, days_ago=index * 5, topics={"T-compbio"}, peer_reviewed=True)

        # Image generation that *looks* like systems work. The only papers a
        # negative interest can meaningfully act on are ones something else
        # retrieved: a paper orthogonal to every interest is never a candidate,
        # so a negative interest against it would be untested decoration.
        for index in range(5):
            self._add(
                None,
                vector=_blend(IMAGEGEN, SYSTEMS, 0.7, variation=index),
                days_ago=index * 2,
                topics={"T-imagegen"},
            )

        # Adjacent: inside the exploration band, on no followed topic.
        for index in range(4):
            self._add(
                None,
                vector=_blend(RAG, ADJACENT, 0.7, variation=index),
                days_ago=index * 4,
                topics={"T-adjacent"},
            )
        for index in range(6):
            self._add(UNRELATED, days_ago=index * 30, topics={"T-other"})

        self.profile = _encode(
            (
                _stated("rag", "RAG", RAG, weight=2.0),
                _stated("sys", "AI systems", SYSTEMS, weight=2.0),
                _stated("bio", "Computational biology", COMPBIO, weight=1.0),
                _stated("img", "Image generation", IMAGEGEN, polarity=Polarity.NEGATIVE),
                Interest(key="t-rag", kind=InterestKind.TOPIC, label="Retrieval", value="T-rag"),
            ),
            Preferences(exploration=0.2),
        )

    def _add(
        self,
        axis: int | None,
        *,
        days_ago: int,
        topics: set[str],
        vector: np.ndarray | None = None,
        peer_reviewed: bool = False,
    ) -> uuid.UUID:
        paper_id = uuid.uuid4()
        if vector is None:
            # Siblings vary, so a subject is a cluster rather than one point.
            vector = _variant(axis or 0, len(self.facts))
        self.facts[paper_id] = PaperFacts(
            paper_id=paper_id,
            vector=vector,
            feed_date=TODAY - timedelta(days=days_ago),
            topic_ids=frozenset(topics),
            is_peer_reviewed=peer_reviewed,
            has_abstract=True,
        )
        return paper_id


@pytest.fixture
def scenario() -> _Scenario:
    return _Scenario()


def _run(scenario: _Scenario, *, profile=None, limit: int = 10, ranker=None):
    sources = [
        InMemorySemanticSource(scenario.facts),
        ExactMatchSource(scenario.facts),
        AdjacentSource(scenario.facts),
    ]
    return build_feed(
        profile or scenario.profile,
        sources,
        lambda ids: {pid: scenario.facts[pid] for pid in ids if pid in scenario.facts},
        today=TODAY,
        config=FeedConfig(
            limit=limit,
            budget=CandidateBudget(total=200, exploration_share=0.2),
            diversity=DiversityPolicy(max_per_interest=4, exploration_share=0.2),
        ),
        ranker=ranker,
    )


def _biology_first(scenario: _Scenario) -> EncodedProfile:
    """The same reader, re-weighted. The ranking must follow."""
    reweighted = tuple(
        interest
        if interest.key != "bio"
        else Interest(
            key="bio",
            kind=InterestKind.STATED,
            label="Computational biology",
            text=interest.text,
            vector=interest.vector,
            weight=8.0,
        )
        for interest in scenario.profile.profile.interests
        if interest.key != "t-rag"
    )
    return EncodedProfile(
        profile=InterestProfile(interests=reweighted, preferences=scenario.profile.preferences),
        model_key="specter2@v1",
    )


def _basis(index: int) -> np.ndarray:
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    vector[index] = 1.0
    return vector


def _unit(vector: np.ndarray) -> np.ndarray:
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _variant(axis: int, index: int) -> np.ndarray:
    """A paper about `axis`, distinguishable from its siblings.

    0.95 on the subject and 0.31 on one of four variation axes, so two siblings
    on different variation axes sit at cosine 0.90: close enough to be the same
    subject, far enough not to trip the near-duplicate rule.
    """
    noise = 6 + index % len(VARIATION_AXES)
    return _unit(0.95 * _basis(axis) + 0.31 * _basis(noise))


def _blend(first: int, second: int, weight: float, *, variation: int = 0) -> np.ndarray:
    combined = weight * _basis(first) + (1.0 - weight) * _basis(second)
    combined = combined + 0.12 * _basis(6 + variation % len(VARIATION_AXES))
    return _unit(combined)


def _stated(key: str, label: str, axis: int, **overrides) -> Interest:
    return Interest(
        key=key,
        kind=InterestKind.STATED,
        label=label,
        text=f"a described research interest concerning {label}",
        vector=_basis(axis),
        **overrides,
    )


def _encode(interests, preferences: Preferences) -> EncodedProfile:
    return EncodedProfile(
        profile=InterestProfile(interests=tuple(interests), preferences=preferences),
        model_key="specter2@v1",
    )
