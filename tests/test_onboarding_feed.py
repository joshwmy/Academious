"""Does a profile built from onboarding actually behave like the reader said?

The question this file exists for is not *is the ranker good* - nobody has
judged a paper yet, and `eval/recommend.py` is explicit that any quality number
computed before that measures the system against itself. It is the narrower,
answerable question: **does the thing a reader chose survive all the way into
the feed?** Each test names one stated choice and checks that changing it
changes the recommendations in the direction the interface promised.

These are behavioural invariants, not accuracy. There are no percentages here
and there should not be until a person has judged pooled results.

The corpus sits on orthogonal axes, the technique `test_personalise_feed.py`
uses and for the same reason: these tests are about the *pipeline's* decisions,
and a real embedding would turn every assertion into a judgement about SPECTER2.
No model, no database, no network.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
import pytest

from academious.onboarding.builder import PaperReference, ProfileBuilder, interest_key
from academious.onboarding.draft import (
    DiscoveryChoices,
    ExamplePaper,
    NegativeInterest,
    ProfileDraft,
    TextInterest,
)
from academious.onboarding.levels import Importance, PublicationStage
from academious.onboarding.refine import Refinement, RefinementAction, apply_refinement
from academious.personalise.candidates import CandidateBudget
from academious.personalise.features import PaperFacts
from academious.personalise.feed import FeedConfig, build_feed
from academious.personalise.ranking import DeterministicRanker, weights_for
from academious.personalise.rerank import DiversityPolicy
from academious.personalise.sources import ExactMatchSource, InMemorySemanticSource

TODAY = date(2026, 9, 5)
DIMENSIONS = 10
MODEL = "stub@v1"

# Subject axes, then four axes of per-paper variation so siblings are similar
# rather than identical - identical siblings are near-duplicates, and the rerank
# rule would correctly collapse each subject to a single item.
RECSYS, BIOLOGY, SYSTEMS, IMAGEGEN, ADJACENT, UNRELATED = range(6)
VARIATION = range(6, DIMENSIONS)

RECSYS_TEXT = "recommendation systems and personalised ranking"
BIOLOGY_TEXT = "computational genomics and protein structure"
SYSTEMS_TEXT = "distributed systems, consensus and replication"
IMAGE_TEXT = "diffusion models and generative image synthesis"

#: Which axis each interest text encodes onto. The stand-in for a model, and
#: deliberately a lookup rather than a keyword heuristic: a heuristic would make
#: these tests depend on how the fixture happens to spell things.
AXES = {
    RECSYS_TEXT: RECSYS,
    BIOLOGY_TEXT: BIOLOGY,
    SYSTEMS_TEXT: SYSTEMS,
    IMAGE_TEXT: IMAGEGEN,
}


def _basis(index: int) -> np.ndarray:
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    vector[index] = 1.0
    return vector


def _unit(vector: np.ndarray) -> np.ndarray:
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _variant(axis: int, index: int) -> np.ndarray:
    """A paper about `axis`, distinguishable from its siblings at cosine 0.90."""
    return _unit(0.95 * _basis(axis) + 0.31 * _basis(6 + index % len(VARIATION)))


def _blend(first: int, second: int, weight: float, *, variation: int = 0) -> np.ndarray:
    combined = weight * _basis(first) + (1.0 - weight) * _basis(second)
    return _unit(combined + 0.12 * _basis(6 + variation % len(VARIATION)))


def _encode(texts):
    """The stand-in encoder. Unknown text lands on the unrelated axis."""
    return [_basis(AXES.get(text, UNRELATED)) for text in texts]


class _Corpus:
    """Papers on each axis, plus the awkward cases a profile has to handle."""

    def __init__(self) -> None:
        self.facts: dict[uuid.UUID, PaperFacts] = {}
        self.by_axis: dict[int, list[uuid.UUID]] = {}

        for axis, topic, field in (
            (RECSYS, "T-recsys", "computer-science"),
            (BIOLOGY, "T-bio", "biochemistry-genetics-and-molecular-biology"),
            (SYSTEMS, "T-systems", "computer-science"),
        ):
            for index in range(6):
                self._add(
                    _variant(axis, index), axis, days_ago=index * 3, topic=topic, field=field
                )

        # Image generation that *looks* like systems work. A negative interest
        # can only act on papers something else retrieved: one orthogonal to
        # every interest is never a candidate, so a dislike about it would be
        # untested decoration.
        for index in range(5):
            self._add(
                _blend(IMAGEGEN, SYSTEMS, 0.7, variation=index),
                IMAGEGEN,
                days_ago=index * 2,
                topic="T-imagegen",
                field="computer-science",
            )

        for index in range(4):
            self._add(
                _blend(RECSYS, ADJACENT, 0.7, variation=index),
                ADJACENT,
                days_ago=index * 4,
                topic="T-adjacent",
                field="computer-science",
            )
        for index in range(5):
            self._add(
                _variant(UNRELATED, index),
                UNRELATED,
                days_ago=index * 20,
                topic="T-other",
                field="chemistry",
                peer_reviewed=index % 2 == 0,
            )

    def _add(
        self,
        vector: np.ndarray,
        axis: int,
        *,
        days_ago: int,
        topic: str,
        field: str,
        peer_reviewed: bool = False,
    ) -> uuid.UUID:
        paper_id = uuid.uuid4()
        self.facts[paper_id] = PaperFacts(
            paper_id=paper_id,
            vector=vector,
            feed_date=TODAY - timedelta(days=days_ago),
            topic_ids=frozenset({topic}),
            field_slugs=frozenset({field}),
            is_peer_reviewed=peer_reviewed,
            has_abstract=True,
        )
        self.by_axis.setdefault(axis, []).append(paper_id)
        return paper_id

    def references(self, paper_ids):
        return {
            pid: PaperReference(
                paper_id=pid, title=f"Paper {pid.hex[:6]}", vector=self.facts[pid].vector
            )
            for pid in paper_ids
            if pid in self.facts
        }


@pytest.fixture
def corpus() -> _Corpus:
    return _Corpus()


@pytest.fixture
def builder(corpus) -> ProfileBuilder:
    return ProfileBuilder(encode=_encode, papers=corpus.references, model_key=MODEL)


def _feed(corpus: _Corpus, builder: ProfileBuilder, draft: ProfileDraft, *, limit: int = 10):
    built = builder.build(draft)
    return built, build_feed(
        built.encoded,
        [InMemorySemanticSource(corpus.facts), ExactMatchSource(corpus.facts)],
        lambda ids: {pid: corpus.facts[pid] for pid in ids if pid in corpus.facts},
        today=TODAY,
        config=FeedConfig(
            limit=limit,
            budget=CandidateBudget(total=200),
            diversity=DiversityPolicy(max_per_interest=5),
        ),
        ranker=DeterministicRanker(weights=weights_for(built.profile.preferences)),
    )


def _axis_of(corpus: _Corpus, paper_id: uuid.UUID) -> int:
    for axis, ids in corpus.by_axis.items():
        if paper_id in ids:
            return axis
    raise AssertionError("paper is not in the corpus")


# --- distinct interests reach the feed ----------------------------------------


def test_two_stated_interests_both_earn_representation(corpus, builder):
    """The averaged-vector failure mode would leave one of them with nothing."""
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(interests=(TextInterest(RECSYS_TEXT), TextInterest(BIOLOGY_TEXT))),
    )
    axes = {_axis_of(corpus, item.paper_id) for item in feed.items}

    assert RECSYS in axes
    assert BIOLOGY in axes


def test_each_interest_is_attributed_by_name(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(interests=(TextInterest(RECSYS_TEXT), TextInterest(BIOLOGY_TEXT))),
    )
    attributed = {item.matched_interest for item in feed.items}

    assert {RECSYS_TEXT, BIOLOGY_TEXT} <= attributed


# --- importance mapping changes the ranking -----------------------------------


def test_a_core_interest_leads_over_an_occasional_one(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(
                TextInterest(RECSYS_TEXT, Importance.CORE),
                TextInterest(BIOLOGY_TEXT, Importance.OCCASIONAL),
            )
        ),
    )

    assert _axis_of(corpus, feed.items[0].paper_id) == RECSYS


def test_swapping_which_interest_is_core_swaps_what_leads(corpus, builder):
    """The test that says this is personalisation rather than decoration."""
    _, first = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(
                TextInterest(RECSYS_TEXT, Importance.CORE),
                TextInterest(BIOLOGY_TEXT, Importance.OCCASIONAL),
            )
        ),
    )
    _, flipped = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(
                TextInterest(RECSYS_TEXT, Importance.OCCASIONAL),
                TextInterest(BIOLOGY_TEXT, Importance.CORE),
            )
        ),
    )

    assert _axis_of(corpus, flipped.items[0].paper_id) == BIOLOGY
    assert first.paper_ids() != flipped.paper_ids()


# --- example papers -----------------------------------------------------------


def test_choosing_an_example_paper_pulls_in_work_like_it(corpus, builder):
    """The signal a reader gives when they cannot put the subject into words."""
    example = corpus.by_axis[BIOLOGY][0]

    _, without = _feed(corpus, builder, ProfileDraft(interests=(TextInterest(RECSYS_TEXT),)))
    _, with_paper = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(RECSYS_TEXT),),
            example_papers=(ExamplePaper(example, Importance.CORE),),
        ),
    )

    before = sum(1 for i in without.items if _axis_of(corpus, i.paper_id) == BIOLOGY)
    after = sum(1 for i in with_paper.items if _axis_of(corpus, i.paper_id) == BIOLOGY)
    assert after > before


def test_an_example_paper_is_explained_as_a_paper_not_as_a_typed_interest(corpus, builder):
    """*Similar to a paper you chose* is a different claim from *you said this*."""
    example = corpus.by_axis[BIOLOGY][0]
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(RECSYS_TEXT),),
            example_papers=(ExamplePaper(example, Importance.CORE),),
        ),
    )
    from_paper = [
        item
        for item in feed.items
        if item.scored.matched_interest_key
        and item.scored.matched_interest_key.startswith("p-")
    ]

    assert from_paper, "the example paper earned nothing"
    assert any("similar to a paper you chose" in reason for reason in from_paper[0].reasons)


# --- negative interests -------------------------------------------------------


def test_an_explicit_dislike_lowers_the_papers_it_matches(corpus, builder):
    """Compared per paper, not per position.

    Rank alone is the wrong measurement here and it took a failing test to say
    so: in a small corpus a penalised paper can keep its position simply because
    nothing better exists to take it, which makes an assertion about rank a
    statement about how many papers the fixture holds. The claim that actually
    belongs to the dislike is that *this paper scores lower for this reader*.
    """
    _, without = _feed(corpus, builder, ProfileDraft(interests=(TextInterest(SYSTEMS_TEXT),)))
    _, with_dislike = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(SYSTEMS_TEXT),),
            negatives=(NegativeInterest(IMAGE_TEXT),),
        ),
    )

    before = {i.paper_id: i.score for i in without.items}
    after = {i.paper_id: i.score for i in with_dislike.items}
    disliked = [pid for pid in before if _axis_of(corpus, pid) == IMAGEGEN]

    assert disliked, "the fixture must retrieve disliked papers or this tests nothing"
    for paper_id in disliked:
        assert after.get(paper_id, 0.0) < before[paper_id]
    for paper_id in before:
        if _axis_of(corpus, paper_id) == SYSTEMS:
            assert after.get(paper_id) == pytest.approx(before[paper_id]), (
                "a dislike must not move what it does not match"
            )


def test_a_dislike_is_visible_in_the_arithmetic_not_only_the_order(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(SYSTEMS_TEXT),),
            negatives=(NegativeInterest(IMAGE_TEXT),),
        ),
    )
    penalised = [i for i in feed.items if i.scored.features["negative_affinity"] > 0.0]

    for item in penalised:
        assert item.scored.contributions["negative_affinity"] < 0.0


def test_a_dislike_does_not_empty_the_feed(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(SYSTEMS_TEXT),),
            negatives=(NegativeInterest(IMAGE_TEXT),),
        ),
    )

    assert len(feed.items) >= 5


def test_a_blocked_topic_removes_papers_rather_than_lowering_them(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(SYSTEMS_TEXT),), blocked_topics=("T-imagegen",)
        ),
    )

    assert all(_axis_of(corpus, item.paper_id) != IMAGEGEN for item in feed.items)
    assert feed.diagnostics.filtered_by_block > 0


# --- publication stage --------------------------------------------------------


def test_peer_reviewed_only_removes_everything_unreviewed(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            interests=(TextInterest(RECSYS_TEXT), TextInterest(BIOLOGY_TEXT)),
            discovery=DiscoveryChoices(publication=PublicationStage.PEER_REVIEWED_ONLY),
        ),
    )

    assert all(corpus.facts[item.paper_id].is_peer_reviewed for item in feed.items)


# --- horizons -----------------------------------------------------------------


def test_a_short_term_refinement_moves_the_feed_without_erasing_the_long_term(corpus, builder):
    """Two horizons earn their complexity here or nowhere."""
    draft = ProfileDraft(
        interests=(
            TextInterest(RECSYS_TEXT, Importance.CORE),
            TextInterest(SYSTEMS_TEXT, Importance.CORE),
        )
    )
    _, before = _feed(corpus, builder, draft)

    refined = apply_refinement(
        draft,
        Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=corpus.by_axis[BIOLOGY][0]),
    ).draft
    built, after = _feed(corpus, builder, refined)

    assert before.paper_ids() != after.paper_ids(), "the refinement did nothing"
    long_term = {i.text for i in built.profile.interests if i.text}
    assert {RECSYS_TEXT, SYSTEMS_TEXT} <= long_term, "the standing interests were erased"


def test_lowering_an_interest_from_the_preview_changes_the_ranking(corpus, builder):
    draft = ProfileDraft(
        interests=(
            TextInterest(RECSYS_TEXT, Importance.CORE),
            TextInterest(BIOLOGY_TEXT, Importance.CORE),
        )
    )
    _, before = _feed(corpus, builder, draft)

    quieter = apply_refinement(
        draft,
        Refinement(
            action=RefinementAction.LESS_FROM_INTEREST, interest_key=interest_key(RECSYS_TEXT)
        ),
    ).draft
    _, after = _feed(corpus, builder, quieter)

    assert before.paper_ids() != after.paper_ids()


# --- determinism and explanation ----------------------------------------------


def test_the_same_draft_produces_the_same_feed(corpus, builder):
    draft = ProfileDraft(interests=(TextInterest(RECSYS_TEXT), TextInterest(BIOLOGY_TEXT)))

    _, first = _feed(corpus, builder, draft)
    _, second = _feed(corpus, builder, draft)

    assert first.paper_ids() == second.paper_ids()


def test_every_previewed_paper_can_say_why_it_is_there(corpus, builder):
    _, feed = _feed(
        corpus,
        builder,
        ProfileDraft(
            fields=("computer-science",),
            interests=(TextInterest(RECSYS_TEXT), TextInterest(BIOLOGY_TEXT)),
        ),
    )

    for item in feed.items:
        assert item.reasons, f"rank {item.rank} has no reason"


def test_a_reason_names_the_interest_that_actually_won(corpus, builder):
    """The explanation comes from the argmax, so it cannot disagree with the score."""
    _, feed = _feed(corpus, builder, ProfileDraft(interests=(TextInterest(RECSYS_TEXT),)))

    for item in feed.items:
        if item.matched_interest:
            assert any(item.matched_interest in reason for reason in item.reasons)


def test_a_reader_who_only_ticked_boxes_still_gets_a_feed(corpus, builder):
    """The cold-start floor. Before this phase the profile could not even be encoded."""
    built, feed = _feed(corpus, builder, ProfileDraft(fields=("computer-science",)))

    assert len(built.encoded.positive) == 0, "nothing to encode"
    assert feed.items, "but the reader still sees something"
    assert all(
        "computer-science" in corpus.facts[item.paper_id].field_slugs for item in feed.items
    )
