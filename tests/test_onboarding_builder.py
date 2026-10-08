"""Draft to profile: does the recommender receive the reader we meant?

The builder is where a person's words become weights, vectors and polarities,
and it is the easiest place in the system for an intention to go quietly
missing. So these tests check the translation rather than the plumbing: that
three interests stay three, that *core* outranks *occasional* in the profile and
not only on the screen, that a chosen paper reuses its own embedding, and that
the summary a reader reads is derived from what was built rather than from what
they typed.

Deterministic fixture vectors and a dictionary of papers. No model, no database,
no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from academious.eval import drafts as benchmark_drafts
from academious.onboarding import PROFILE_SCHEMA_VERSION
from academious.onboarding.builder import (
    BuildError,
    PaperReference,
    ProfileBuilder,
    example_paper_key,
    field_key,
    interest_key,
)
from academious.onboarding.draft import (
    DiscoveryChoices,
    ExamplePaper,
    NegativeInterest,
    NegativePaper,
    ProfileDraft,
    TextInterest,
)
from academious.onboarding.levels import (
    AVOIDANCE_WEIGHT,
    EXPLORATION_SHARE,
    IMPORTANCE_WEIGHT,
    PREPRINT_APPETITE,
    Avoidance,
    ExplorationLevel,
    FreshnessLevel,
    Importance,
    Provenance,
    PublicationStage,
)
from academious.onboarding.summary import summarise
from academious.personalise.profile import Horizon, InterestKind, Polarity
from academious.personalise.ranking import DEFAULT_WEIGHTS, weights_for

DIMENSIONS = 32
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
MODEL = "stub@v1"


class _Encoder:
    """One orthogonal axis per distinct string, and a count of calls.

    The count is load-bearing: "encode each interest once, in one batch" is a
    performance claim the API depends on, and a test that only checked the
    vectors would not notice it being broken.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._axes: dict[str, int] = {}

    def __call__(self, texts):
        listed = list(texts)
        self.calls.append(listed)
        return [self._vector(text) for text in listed]

    def _vector(self, text: str) -> np.ndarray:
        axis = self._axes.setdefault(text, len(self._axes))
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        vector[axis % DIMENSIONS] = 1.0
        return vector

    @property
    def texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


class _Papers:
    """A corpus of chosen papers, some of which are not embedded yet."""

    def __init__(self, known: dict[uuid.UUID, PaperReference]) -> None:
        self.known = known
        self.requests: list[list[uuid.UUID]] = []

    def __call__(self, paper_ids):
        listed = list(paper_ids)
        self.requests.append(listed)
        return {pid: self.known[pid] for pid in listed if pid in self.known}


def _reference(title: str, axis: int, *, embedded: bool = True) -> PaperReference:
    vector = None
    if embedded:
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        vector[axis % DIMENSIONS] = 1.0
    return PaperReference(paper_id=uuid.uuid4(), title=title, vector=vector)


@pytest.fixture
def encoder() -> _Encoder:
    return _Encoder()


@pytest.fixture
def paper() -> PaperReference:
    return _reference("Dense Retrieval for Scientific Search", axis=20)


@pytest.fixture
def builder(encoder, paper) -> ProfileBuilder:
    return ProfileBuilder(
        encode=encoder, papers=_Papers({paper.paper_id: paper}), model_key=MODEL, now=NOW
    )


# --- distinct interests survive -----------------------------------------------


@pytest.mark.parametrize("benchmark", benchmark_drafts.DRAFTS, ids=lambda d: d.id)
def test_every_stated_interest_becomes_its_own_interest(builder, benchmark):
    """The claim the whole multi-interest architecture rests on."""
    built = builder.build(benchmark.draft)
    texts = {i.text for i in built.profile.interests if i.kind is InterestKind.STATED}

    for expected in benchmark.expect_distinct:
        assert expected in texts, f"{benchmark.id} lost {expected!r}"


def test_distinct_interests_get_distinct_vectors(builder):
    built = builder.build(
        ProfileDraft(
            interests=(
                TextInterest("recommendation systems and ranking"),
                TextInterest("computational genomics and variant calling"),
            )
        )
    )
    vectors = built.encoded.positive_vectors

    assert vectors.shape[0] == 2
    assert float(vectors[0] @ vectors[1]) == pytest.approx(0.0)


def test_text_is_encoded_once_per_distinct_string_in_one_call(encoder, builder):
    """Three interests are one batch, and no string is encoded twice."""
    builder.build(
        ProfileDraft(
            interests=(
                TextInterest("large language model evaluation"),
                TextInterest("distributed systems and consensus"),
            ),
            negatives=(NegativeInterest("generative image synthesis"),),
        )
    )

    assert len(encoder.calls) == 1
    assert len(encoder.texts) == len(set(encoder.texts)) == 3


# --- importance mapping -------------------------------------------------------


def test_core_outranks_interested_outranks_occasional(builder):
    built = builder.build(
        ProfileDraft(
            interests=(
                TextInterest("recommendation systems research", Importance.CORE),
                TextInterest("information retrieval evaluation", Importance.INTERESTED),
                TextInterest("distributed consensus protocols", Importance.OCCASIONAL),
            )
        )
    )
    by_text = {i.text: i.weight for i in built.profile.interests}

    assert by_text["recommendation systems research"] == IMPORTANCE_WEIGHT[Importance.CORE]
    assert (
        by_text["recommendation systems research"]
        > by_text["information retrieval evaluation"]
        > by_text["distributed consensus protocols"]
    )


def test_avoidance_levels_reach_the_profile(builder):
    built = builder.build(
        ProfileDraft(
            interests=(TextInterest("recommendation systems research"),),
            negatives=(
                NegativeInterest("generative image synthesis", strength=Avoidance.LESS),
                NegativeInterest("cryptocurrency and blockchain", strength=Avoidance.AVOID),
            ),
        )
    )
    weights = {i.text: i.weight for i in built.profile.negative}

    assert weights["generative image synthesis"] == AVOIDANCE_WEIGHT[Avoidance.LESS]
    assert weights["cryptocurrency and blockchain"] == AVOIDANCE_WEIGHT[Avoidance.AVOID]
    assert all(i.polarity is Polarity.NEGATIVE for i in built.profile.negative)


def test_a_negative_is_never_folded_into_a_positive_vector(builder):
    built = builder.build(
        ProfileDraft(
            interests=(TextInterest("recommendation systems research"),),
            negatives=(NegativeInterest("generative image synthesis"),),
        )
    )

    assert built.encoded.positive_vectors.shape[0] == 1
    assert built.encoded.negative_vectors.shape[0] == 1


# --- provenance ---------------------------------------------------------------


def test_free_text_carries_explicit_text_provenance(builder):
    built = builder.build(ProfileDraft(interests=(TextInterest("protein structure prediction"),)))

    assert built.profile.interests[0].provenance == Provenance.EXPLICIT_TEXT


def test_a_broad_area_carries_field_provenance_and_the_canonical_label(builder):
    built = builder.build(ProfileDraft(fields=("computer-science",)))
    interest = built.profile.interests[0]

    assert interest.kind is InterestKind.FIELD
    assert interest.value == "computer-science"
    assert interest.label == "Computer Science"
    assert interest.provenance == Provenance.SELECTED_FIELD


def test_an_example_paper_keeps_the_paper_as_provenance(builder, paper):
    """A title re-encoded as text would lose the source; the id must survive."""
    built = builder.build(ProfileDraft(example_papers=(ExamplePaper(paper.paper_id),)))
    interest = built.profile.interests[0]

    assert interest.kind is InterestKind.PAPER
    assert str(paper.paper_id) in interest.provenance
    assert interest.provenance.startswith(str(Provenance.EXAMPLE_PAPER))


def test_interests_are_stamped_with_when_they_were_stated(builder):
    built = builder.build(ProfileDraft(interests=(TextInterest("protein structure prediction"),)))

    assert built.profile.interests[0].created_at == NOW


# --- example papers -----------------------------------------------------------


def test_an_example_paper_reuses_the_stored_embedding(builder, paper):
    built = builder.build(ProfileDraft(example_papers=(ExamplePaper(paper.paper_id),)))

    assert np.allclose(built.profile.interests[0].vector, paper.vector)


def test_an_example_paper_is_not_re_encoded_as_text(encoder, builder, paper):
    builder.build(ProfileDraft(example_papers=(ExamplePaper(paper.paper_id),)))

    assert encoder.calls == [], "the paper's own vector already exists"


def test_chosen_papers_are_resolved_in_one_request(encoder, paper):
    second = _reference("Learned Sparse Retrieval", axis=21)
    papers = _Papers({paper.paper_id: paper, second.paper_id: second})
    ProfileBuilder(encode=encoder, papers=papers, model_key=MODEL).build(
        ProfileDraft(
            example_papers=(ExamplePaper(paper.paper_id), ExamplePaper(second.paper_id))
        )
    )

    assert len(papers.requests) == 1


def test_a_paper_with_no_embedding_is_dropped_with_a_warning(encoder):
    """Not silently replaced by its title, and not a failure the reader caused."""
    pending = _reference("Waiting On The Embedding Backlog", axis=0, embedded=False)
    builder = ProfileBuilder(
        encode=encoder, papers=_Papers({pending.paper_id: pending}), model_key=MODEL
    )

    built = builder.build(
        ProfileDraft(
            interests=(TextInterest("recommendation systems research"),),
            example_papers=(ExamplePaper(pending.paper_id),),
        )
    )

    assert [i.code for i in built.warnings] == ["example_paper_not_embedded"]
    assert all(i.kind is not InterestKind.PAPER for i in built.profile.interests)


def test_a_paper_not_in_the_corpus_is_reported_differently(encoder):
    """A reader can act on 'no such paper'; they cannot act on 'not embedded yet'."""
    builder = ProfileBuilder(encode=encoder, papers=_Papers({}), model_key=MODEL)

    built = builder.build(
        ProfileDraft(
            interests=(TextInterest("recommendation systems research"),),
            example_papers=(ExamplePaper(uuid.uuid4()),),
        )
    )

    assert [i.code for i in built.warnings] == ["unknown_example_paper"]


def test_a_profile_left_with_nothing_positive_is_refused_with_the_reason(encoder):
    builder = ProfileBuilder(encode=encoder, papers=_Papers({}), model_key=MODEL)

    with pytest.raises(BuildError) as raised:
        builder.build(ProfileDraft(example_papers=(ExamplePaper(uuid.uuid4()),)))

    assert "no_usable_positive_interest" in {i.code for i in raised.value.issues}


# --- horizons -----------------------------------------------------------------


def test_onboarding_produces_long_term_interests(builder, paper):
    """A signup is a statement about the year, not about this afternoon."""
    built = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            interests=(TextInterest("recommendation systems research"),),
            example_papers=(ExamplePaper(paper.paper_id),),
        )
    )

    assert {i.horizon for i in built.profile.interests} == {Horizon.LONG}


def test_a_short_term_interest_survives_the_build(builder):
    built = builder.build(
        ProfileDraft(
            interests=(
                TextInterest("recommendation systems research"),
                TextInterest("retrieval augmented generation", horizon=Horizon.SHORT),
            )
        )
    )
    short = [i for i in built.profile.interests if i.horizon is Horizon.SHORT]

    assert [i.text for i in short] == ["retrieval augmented generation"]


# --- preferences --------------------------------------------------------------


def test_exploration_choice_reaches_the_profile(builder):
    built = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(exploration=ExplorationLevel.ADVENTUROUS),
        )
    )

    expected = EXPLORATION_SHARE[ExplorationLevel.ADVENTUROUS]
    assert built.profile.preferences.exploration == expected


def test_publication_choice_reaches_the_profile_as_an_appetite_and_a_filter(builder):
    """*Prefer* is a weight; *only* is a promise, and needs the hard filter behind it."""
    prefer = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(publication=PublicationStage.PREFER_PEER_REVIEWED),
        )
    )
    only = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(publication=PublicationStage.PEER_REVIEWED_ONLY),
        )
    )

    expected = PREPRINT_APPETITE[PublicationStage.PREFER_PEER_REVIEWED]
    assert prefer.profile.preferences.preprint_appetite == expected
    assert not prefer.profile.require_peer_reviewed
    assert only.profile.require_peer_reviewed


def test_freshness_choice_moves_the_ranker_weight_in_the_right_direction(builder):
    newest = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(freshness=FreshnessLevel.NEWEST_FIRST),
        )
    )
    relevance = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(freshness=FreshnessLevel.RELEVANCE_FIRST),
        )
    )
    balanced = builder.build(ProfileDraft(fields=("computer-science",)))

    assert (
        weights_for(newest.profile.preferences)["freshness"]
        > weights_for(balanced.profile.preferences)["freshness"]
        > weights_for(relevance.profile.preferences)["freshness"]
    )


def test_expressing_no_freshness_preference_changes_no_weight(builder):
    """The default table is the one the benchmark measured; it must survive exactly."""
    built = builder.build(ProfileDraft(fields=("computer-science",)))

    assert weights_for(built.profile.preferences).values == dict(DEFAULT_WEIGHTS)


def test_blocked_topics_reach_the_profile_as_a_hard_filter(builder):
    built = builder.build(ProfileDraft(fields=("computer-science",), blocked_topics=("T11689",)))

    assert built.profile.blocked_topics == frozenset({"T11689"})


# --- keys are stable ----------------------------------------------------------


def test_building_the_same_draft_twice_produces_the_same_keys(builder, paper):
    draft = ProfileDraft(
        fields=("computer-science",),
        interests=(TextInterest("recommendation systems research"),),
        example_papers=(ExamplePaper(paper.paper_id),),
    )

    first = [i.key for i in builder.build(draft).profile.interests]
    second = [i.key for i in builder.build(draft).profile.interests]

    assert first == second


def test_keys_can_be_derived_without_building(paper):
    """Refinement finds a draft entry from a key the preview reported."""
    assert interest_key("recommendation systems research").startswith("i-")
    assert field_key("computer-science") == "f-computer-science"
    assert example_paper_key(paper.paper_id).startswith("p-")


# --- the summary a reader reads -----------------------------------------------


def test_the_summary_separates_core_from_other_interests(builder):
    built = builder.build(
        ProfileDraft(
            interests=(
                TextInterest("recommendation systems research", Importance.CORE),
                TextInterest("computational genomics methods", Importance.OCCASIONAL),
            ),
            negatives=(NegativeInterest("generative image synthesis"),),
        )
    )
    summary = summarise(built.profile)

    assert summary.core_interests == ("recommendation systems research",)
    assert summary.other_interests == ("computational genomics methods",)
    assert summary.avoiding == ("generative image synthesis",)


def test_the_summary_is_derived_from_the_profile_not_the_draft(builder):
    """A merged duplicate must show once, because the profile holds it once."""
    built = builder.build(
        ProfileDraft(
            interests=(
                TextInterest("machine learning systems", Importance.CORE),
                TextInterest("Machine-Learning Systems", Importance.CORE),
            )
        )
    )

    assert summarise(built.profile).core_interests == ("machine learning systems",)


def test_the_summary_names_every_preference_in_words(builder):
    built = builder.build(
        ProfileDraft(
            fields=("computer-science",),
            discovery=DiscoveryChoices(publication=PublicationStage.PEER_REVIEWED_ONLY),
        )
    )
    values = dict(summarise(built.profile).preferences)

    assert values["Publication stage"] == "Peer-reviewed only"
    assert all(isinstance(value, str) for value in values.values())


def test_the_summary_hides_headings_with_nothing_under_them(builder):
    built = builder.build(ProfileDraft(fields=("computer-science",)))
    headings = {section.heading for section in summarise(built.profile).sections()}

    assert headings == {"Broad areas"}


def test_the_summary_renders_as_plain_lines(builder):
    built = builder.build(
        ProfileDraft(interests=(TextInterest("recommendation systems research", Importance.CORE),))
    )
    lines = summarise(built.profile).lines()

    assert "Core interests:" in lines
    assert "  - recommendation systems research" in lines


# --- the profile as a portable artifact ---------------------------------------


def test_the_schema_version_is_an_integer_that_exists():
    assert isinstance(PROFILE_SCHEMA_VERSION, int)
    assert PROFILE_SCHEMA_VERSION >= 1


def test_the_model_key_travels_with_the_encoded_profile(builder):
    built = builder.build(ProfileDraft(interests=(TextInterest("protein structure prediction"),)))

    assert built.encoded.model_key == MODEL


def test_a_negative_paper_becomes_a_negative_interest(encoder, paper):
    disliked = _reference("Something Else Entirely", axis=25)
    builder = ProfileBuilder(
        encode=encoder,
        papers=_Papers({paper.paper_id: paper, disliked.paper_id: disliked}),
        model_key=MODEL,
    )

    built = builder.build(
        ProfileDraft(
            example_papers=(ExamplePaper(paper.paper_id),),
            negative_papers=(NegativePaper(disliked.paper_id),),
        )
    )
    negatives = built.profile.negative

    assert len(negatives) == 1
    assert negatives[0].kind is InterestKind.PAPER
    assert np.allclose(negatives[0].vector, disliked.vector)
