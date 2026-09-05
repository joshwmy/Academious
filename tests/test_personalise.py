"""The recommendation rules, tested at the level they are argued at.

Every test here is pure: no database, no model, no clock, no network. That is
the point of keeping the pipeline's stages free of I/O - the decisions worth
arguing about (does the max beat the mean, does an explicit block really block,
does a non-click count against a paper) are decidable in milliseconds against
numbers rather than against a feed someone has to read.

Vectors are hand-built and orthogonal so cosine is exact and legible: a paper
"about" interest 0 is literally that basis vector. Nothing depends on SPECTER2
behaving any particular way, which is what makes these tests about the *rules*
rather than about the model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from academious.personalise.candidates import (
    Candidate,
    CandidateBudget,
    CandidateOrigin,
    CandidateReason,
    gather,
)
from academious.personalise.features import (
    COSINE_CEILING,
    COSINE_FLOOR,
    FEATURE_NAMES,
    FEATURE_SPECS,
    PaperFacts,
    extract,
)
from academious.personalise.feedback import (
    BEHAVIOURAL_WEIGHT_CEILING,
    EventType,
    FeedbackEvent,
    apply_feedback,
    impression_rate,
    is_negative_evidence,
)
from academious.personalise.profile import (
    MAX_INTERESTS,
    EncodedProfile,
    Horizon,
    Interest,
    InterestKind,
    InterestProfile,
    Polarity,
    Preferences,
    ProfileError,
)
from academious.personalise.ranking import DeterministicRanker, Weights
from academious.personalise.rerank import (
    DiversityPolicy,
    diversify,
    interest_coverage,
    intra_list_diversity,
    topic_redundancy,
    vector_redundancy,
)
from academious.personalise.sources import StaticSource

TODAY = date(2026, 9, 5)
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
DIMENSIONS = 6


# --- the profile refuses to be a bad one -------------------------------------


def test_a_stated_interest_needs_a_description_not_a_keyword():
    """SPECTER2 reads sentences; 'cancer' encodes to far less than a phrase."""
    with pytest.raises(ProfileError, match="at least"):
        Interest(key="onc", kind=InterestKind.STATED, label="Cancer", text="cancer")


def test_an_exact_match_interest_needs_a_value_not_a_description():
    with pytest.raises(ProfileError, match="needs a value"):
        Interest(key="t1", kind=InterestKind.TOPIC, label="RAG")


def test_two_interests_cannot_share_a_key():
    """The key is identity: Stage B strengthens by key, so a clash corrupts it."""
    with pytest.raises(ProfileError, match="share the key"):
        InterestProfile(interests=(_stated("dup", "A", 0), _stated("dup", "B", 1)))


def test_a_profile_needs_a_positive_interest():
    """A profile of pure dislikes has nothing to rank towards."""
    negative = _stated("no", "Image generation", 0, polarity=Polarity.NEGATIVE)
    with pytest.raises(ProfileError, match="positive interest"):
        InterestProfile(interests=(negative,))


def test_a_profile_is_capped_because_each_interest_costs_a_distance_expression():
    interests = tuple(
        _stated(f"i{n}", f"Interest {n}", n % DIMENSIONS) for n in range(MAX_INTERESTS + 1)
    )
    with pytest.raises(ProfileError, match="at most"):
        InterestProfile(interests=interests)


def test_encoding_refuses_a_profile_with_interests_still_unvectored():
    profile = InterestProfile(
        interests=(Interest(key="a", kind=InterestKind.STATED, label="A", text="a real interest"),)
    )
    with pytest.raises(ProfileError, match="still need vectors"):
        EncodedProfile(profile=profile, model_key="specter2@v1")


def test_confidence_discounts_weight_without_being_weight():
    """A confident read of a mild preference is not a guess about a strong one."""
    interest = _stated("a", "A", 0, weight=2.0, confidence=0.5)
    assert interest.effective_weight == 1.0


# --- multi-interest: the reason this is not one averaged vector ---------------


def test_a_paper_matches_its_own_interest_not_the_average_of_all_of_them():
    """The whole argument for multi-centroid, as a number.

    Three unrelated interests, a paper squarely on the third. An averaged
    profile vector sits between them and would score this paper mediocre; the
    max picks it up at full strength and names the interest that earned it.
    """
    profile = _encoded(_three_interests())
    features = _extract(_facts(vector=_basis(2)), profile)

    assert features["semantic_affinity"] == pytest.approx(1.0)
    assert features.matched_interest_label == "Genomics"

    # And the averaged alternative, computed here to make the contrast explicit.
    averaged = _unit(profile.positive_vectors.mean(axis=0))
    assert float(averaged @ _basis(2)) == pytest.approx(0.577, abs=1e-3)


def test_the_argmax_is_the_explanation():
    """No LLM and no second computation: the reason falls out of the score."""
    profile = _encoded(_three_interests())
    for index, label in enumerate(("RAG", "AI systems", "Genomics")):
        assert _extract(_facts(vector=_basis(index)), profile).matched_interest_label == label


def test_weight_decides_which_interest_wins_not_how_close_the_paper_looks():
    """Weighting is 'more of this', not 'these papers match better'."""
    profile = _encoded(
        (
            _stated("rag", "RAG", 0, weight=1.0),
            _stated("sys", "AI systems", 1, weight=4.0),
        )
    )
    between = _unit(_basis(0) + _basis(1))
    features = _extract(_facts(vector=between), profile)

    assert features.matched_interest_label == "AI systems"
    expected = (0.7071 - COSINE_FLOOR) / (COSINE_CEILING - COSINE_FLOOR)
    assert features["semantic_affinity"] == pytest.approx(expected, abs=1e-3)


def test_an_unrelated_paper_scores_zero_rather_than_negative():
    """Below the floor the exact cosine carries no information, so it clamps."""
    profile = _encoded(_three_interests())
    assert _extract(_facts(vector=_basis(5)), profile)["semantic_affinity"] == 0.0


# --- negatives are represented, not subtracted -------------------------------


def test_a_negative_interest_is_its_own_feature():
    """A paper near both a liked and a disliked region must be visibly that.

    Subtracting the negative from the positive would produce one middling
    number that cannot be distinguished from a mediocre match.
    """
    profile = _encoded(
        (
            _stated("rag", "RAG", 0),
            _stated("img", "Image generation", 3, polarity=Polarity.NEGATIVE),
        )
    )
    disliked = _extract(_facts(vector=_basis(3)), profile)

    assert disliked["negative_affinity"] == pytest.approx(1.0)
    assert disliked["semantic_affinity"] == 0.0


def test_a_negative_interest_pushes_a_paper_down_the_ranking():
    profile = _encoded(
        (
            _stated("rag", "RAG", 0),
            _stated("img", "Image generation", 3, polarity=Polarity.NEGATIVE),
        )
    )
    wanted = _facts(vector=_basis(0), feed_date=TODAY)
    unwanted = _facts(vector=_unit(_basis(0) + _basis(3) * 3), feed_date=TODAY)

    ranked = DeterministicRanker().rank(
        [_extract(wanted, profile), _extract(unwanted, profile)]
    )

    assert ranked[0].paper_id == wanted.paper_id
    assert ranked[1].contributions["negative_affinity"] < 0.0


# --- long and short term ------------------------------------------------------


def test_a_short_term_interest_can_lift_this_week_without_erasing_the_year():
    """LSTUR's split, as a knob rather than an overwrite.

    Same profile, same papers, only `recency_of_interest` differs. The
    long-term paper stays present in both.
    """
    interests = (
        _stated("sys", "ML systems", 0),
        _stated("diff", "Diffusion models", 1, horizon=Horizon.SHORT),
    )
    long_paper = _facts(vector=_basis(0))
    short_paper = _facts(vector=_basis(1))

    steady = _encoded(interests, preferences=Preferences(recency_of_interest=0.1))
    focused = _encoded(interests, preferences=Preferences(recency_of_interest=0.9))

    assert _extract(short_paper, steady)["semantic_affinity"] == pytest.approx(0.1)
    assert _extract(short_paper, focused)["semantic_affinity"] == pytest.approx(0.9)
    assert _extract(long_paper, steady)["semantic_affinity"] == pytest.approx(0.9)
    # The long-term interest is never erased, only de-emphasised.
    assert _extract(long_paper, focused)["semantic_affinity"] == pytest.approx(0.1)


def test_a_profile_with_no_short_term_interests_is_not_halved_by_the_dial():
    """A default nobody touched must not quietly cost half the affinity."""
    profile = _encoded((_stated("sys", "ML systems", 0),), preferences=Preferences())
    assert _extract(_facts(vector=_basis(0)), profile)["semantic_affinity"] == pytest.approx(1.0)


# --- features are bounded, documented and honest about missing data -----------


def test_every_feature_is_declared_and_bounded():
    """The registry is the contract; a feature outside it cannot be weighted."""
    profile = _encoded(_three_interests())
    features = _extract(_facts(vector=_basis(0), feed_date=TODAY), profile)

    assert set(features.values) == set(FEATURE_NAMES)
    assert all(0.0 <= value <= 1.0 for value in features.values.values())
    assert len(features.as_array()) == len(FEATURE_NAMES)


def test_freshness_decays_from_the_feed_date():
    profile = _encoded(_three_interests())
    fresh = _extract(_facts(vector=_basis(0), feed_date=TODAY), profile)
    fortnight = _extract(
        _facts(vector=_basis(0), feed_date=TODAY - timedelta(days=14)), profile
    )

    assert fresh["freshness"] == pytest.approx(1.0)
    assert fortnight["freshness"] == pytest.approx(0.3679, abs=1e-3)


def test_an_undated_paper_is_not_treated_as_new():
    """DATA-009 and DATA-010: a date the corpus cannot vouch for wins the feed."""
    profile = _encoded(_three_interests())
    assert _extract(_facts(vector=_basis(0), feed_date=None), profile)["freshness"] == 0.0


def test_topic_affinity_is_normalised_by_the_follow_set_not_the_paper():
    """A broadly tagged paper is not punished for breadth."""
    profile = _encoded(
        (_stated("rag", "RAG", 0), _topic("t1", "T1"), _topic("t2", "T2")),
    )
    both = _facts(vector=_basis(0), topic_ids=frozenset({"T1", "T2", "T99", "T100"}))
    one = _facts(vector=_basis(0), topic_ids=frozenset({"T1"}))

    assert _extract(both, profile)["topic_affinity"] == pytest.approx(1.0)
    assert _extract(one, profile)["topic_affinity"] == pytest.approx(0.5)


def test_missing_data_uses_the_declared_default_rather_than_zero():
    """A paper with no venue is not a paper in a bad venue."""
    profile = _encoded((_stated("rag", "RAG", 0),))
    features = _extract(_facts(vector=_basis(0)), profile)

    assert features["novelty"] == FEATURE_SPECS["novelty"].missing
    assert features["preprint_fit"] == FEATURE_SPECS["preprint_fit"].missing
    assert features["seen_fatigue"] == 0.0


def test_quality_prior_reads_no_citation_count_and_saturates():
    """Citations accrue with age and would bury the new work this product exists for.

    `PaperFacts` carries no citation count at all, which is the enforcement:
    the feature cannot read what the ranker is never given. Venue citedness is
    capped so a famous journal cannot outrank three ordinary signals.
    """
    assert not any(field == "citation_count" for field in PaperFacts.__slots__)

    profile = _encoded((_stated("rag", "RAG", 0),))
    strong = _facts(
        vector=_basis(0), is_peer_reviewed=True, has_abstract=True, venue_mean_citedness=10.0
    )
    famous_only = _facts(vector=_basis(0), venue_mean_citedness=500.0)

    assert _extract(strong, profile)["quality_prior"] == pytest.approx(1.0)
    assert _extract(famous_only, profile)["quality_prior"] == pytest.approx(1 / 3)


# --- ranking ------------------------------------------------------------------


def test_weights_must_cover_the_registry_exactly():
    """A renamed feature must fail loudly, not drop silently out of every score."""
    with pytest.raises(ValueError, match="features with no weight"):
        Weights({"semantic_affinity": 0.5})
    with pytest.raises(ValueError, match="do not exist"):
        Weights({**dict.fromkeys(FEATURE_NAMES, 0.1), "invented": 0.5})


def test_a_negative_weight_is_refused_because_direction_lives_in_the_registry():
    with pytest.raises(ValueError, match="negative weights"):
        Weights({**dict.fromkeys(FEATURE_NAMES, 0.1), "retracted": -0.5})


def test_the_feed_is_stable_across_runs():
    """An unstable feed is indistinguishable from a changed one, so unmeasurable."""
    profile = _encoded(_three_interests())
    identical = [_facts(vector=_basis(0), feed_date=TODAY) for _ in range(5)]
    vectors = [_extract(paper, profile) for paper in identical]

    first = [hit.paper_id for hit in DeterministicRanker().rank(vectors)]
    second = [hit.paper_id for hit in DeterministicRanker().rank(list(reversed(vectors)))]

    assert first == second


def test_a_retracted_paper_is_lowered_and_never_removed():
    """The reader following the topic is exactly who needs to know."""
    profile = _encoded(_three_interests())
    clean = _facts(vector=_basis(0), feed_date=TODAY)
    retracted = _facts(vector=_basis(0), feed_date=TODAY, retraction_status="retracted")

    ranked = DeterministicRanker().rank(
        [_extract(clean, profile), _extract(retracted, profile)]
    )

    assert [hit.paper_id for hit in ranked] == [clean.paper_id, retracted.paper_id]
    assert len(ranked) == 2, "lowered, not hidden"


def test_scores_are_comparable_because_they_are_normalised_by_positive_mass():
    profile = _encoded(_three_interests())
    perfect = _extract(
        _facts(
            vector=_basis(0),
            feed_date=TODAY,
            is_peer_reviewed=True,
            has_abstract=True,
            venue_mean_citedness=10.0,
        ),
        profile,
    )
    assert 0.0 <= DeterministicRanker().score(perfect).score <= 1.0


# --- candidate pooling --------------------------------------------------------


def test_one_paper_found_by_two_sources_keeps_both_reasons():
    """Agreement is signal, not duplication."""
    paper = uuid.uuid4()
    by_interest = CandidateReason(CandidateOrigin.SEMANTIC_INTEREST, "rag", "RAG", 0.8)
    semantic = StaticSource([Candidate(paper, (by_interest,))], name="semantic")
    topical = StaticSource(
        [Candidate(paper, (CandidateReason(CandidateOrigin.TOPIC, None, "Retrieval", 1.0),))],
        name="topic",
    )

    pool = gather([semantic, topical], _encoded(_three_interests()))

    assert len(pool) == 1
    merged = pool.get(paper)
    assert merged is not None
    assert merged.origins == {CandidateOrigin.SEMANTIC_INTEREST, CandidateOrigin.TOPIC}
    assert pool.contributions == {"semantic": 1, "topic": 1}


def test_a_source_cannot_exceed_its_budget():
    many = [Candidate(uuid.uuid4()) for _ in range(50)]
    pool = gather([StaticSource(many, name="s")], _encoded(_three_interests()),
                  budget=CandidateBudget(total=10))
    assert len(pool) == 10


def test_exploration_only_counts_when_it_is_the_sole_reason():
    """Otherwise the exploration budget is spent on papers that needed none."""
    explore_only = Candidate(uuid.uuid4(), (CandidateReason(CandidateOrigin.EXPLORATION),))
    also_wanted = Candidate(
        uuid.uuid4(),
        (
            CandidateReason(CandidateOrigin.EXPLORATION),
            CandidateReason(CandidateOrigin.SEMANTIC_INTEREST, "rag", "RAG", 0.9),
        ),
    )
    assert explore_only.is_exploration() is True
    assert also_wanted.is_exploration() is False


# --- diversity ----------------------------------------------------------------


def test_one_interest_cannot_take_the_whole_feed():
    """Ten papers about one thing is a worse feed than seven plus three."""
    profile = _encoded(_three_interests())
    papers = [_facts(vector=_basis(0), feed_date=TODAY) for _ in range(8)]
    papers += [_facts(vector=_basis(1), feed_date=TODAY) for _ in range(3)]
    ranked = DeterministicRanker().rank([_extract(p, profile) for p in papers])

    feed = diversify(ranked, limit=6, policy=DiversityPolicy(max_per_interest=3))

    coverage = interest_coverage(feed)
    assert coverage.get("rag", 0) <= 3
    assert coverage.get("sys", 0) >= 1, "the second interest is represented"
    assert len(feed) == 6, "caps relax rather than starving the feed"


def test_near_duplicates_do_not_take_two_slots():
    """A preprint and its published version say one thing."""
    profile = _encoded(_three_interests())
    original = _facts(vector=_basis(0), feed_date=TODAY)
    duplicate = _facts(vector=_basis(0), feed_date=TODAY)
    different = _facts(vector=_basis(1), feed_date=TODAY)
    papers = [original, duplicate, different]
    ranked = DeterministicRanker().rank([_extract(p, profile) for p in papers])
    vectors = {p.paper_id: p.vector for p in papers}

    feed = diversify(ranked, limit=2, redundancy=vector_redundancy(vectors))

    chosen = {item.paper_id for item in feed}
    assert different.paper_id in chosen
    assert len({original.paper_id, duplicate.paper_id} & chosen) == 1


def test_diversity_can_be_switched_off_so_its_cost_is_measurable():
    profile = _encoded(_three_interests())
    papers = [_facts(vector=_basis(0), feed_date=TODAY) for _ in range(5)]
    ranked = DeterministicRanker().rank([_extract(p, profile) for p in papers])

    untouched = diversify(
        ranked, limit=5, policy=DiversityPolicy(relevance_lambda=1.0, max_per_interest=None,
                                                max_per_topic=None)
    )
    assert [item.paper_id for item in untouched] == [item.paper_id for item in ranked]


def test_intra_list_diversity_reports_what_the_feed_actually_looks_like():
    profile = _encoded(_three_interests())
    same = [_facts(vector=_basis(0), feed_date=TODAY) for _ in range(3)]
    ranked = DeterministicRanker().rank([_extract(p, profile) for p in same])
    vectors = {p.paper_id: p.vector for p in same}

    assert intra_list_diversity(ranked, vector_redundancy(vectors)) == pytest.approx(0.0)


def test_topic_redundancy_is_the_fallback_when_vectors_are_absent():
    a, b = uuid.uuid4(), uuid.uuid4()
    similar = topic_redundancy({a: frozenset({"T1", "T2"}), b: frozenset({"T1"})})
    assert similar(a, b) == pytest.approx(0.5)


# --- feedback -----------------------------------------------------------------


def test_a_non_click_is_never_negative_evidence():
    """Position and exposure bias make it uninterpretable. The core discipline."""
    impression = FeedbackEvent(EventType.IMPRESSION, uuid.uuid4(), NOW, position=10)
    assert is_negative_evidence(impression) is False
    assert impression.strength == 0.0


def test_explicit_negatives_are_the_only_negatives():
    for event_type in (EventType.DISMISS, EventType.NOT_RELEVANT, EventType.LESS_LIKE_THIS):
        assert is_negative_evidence(FeedbackEvent(event_type, uuid.uuid4(), NOW)) is True
    for event_type in (EventType.OPEN, EventType.SAVE, EventType.OUTBOUND_CLICK):
        assert is_negative_evidence(FeedbackEvent(event_type, uuid.uuid4(), NOW)) is False


def test_a_save_moves_an_interest_more_than_an_open():
    profile = _profile(_three_interests())
    opened, _ = apply_feedback(profile, [_event(EventType.OPEN, "rag")], now=NOW)
    saved, _ = apply_feedback(profile, [_event(EventType.SAVE, "rag")], now=NOW)

    assert _weight(saved, "rag") > _weight(opened, "rag") > _weight(profile, "rag")


def test_old_evidence_moves_less_than_recent_evidence():
    profile = _profile(_three_interests())
    recent, _ = apply_feedback(profile, [_event(EventType.SAVE, "rag", days_ago=1)], now=NOW)
    ancient, _ = apply_feedback(profile, [_event(EventType.SAVE, "rag", days_ago=365)], now=NOW)

    assert _weight(recent, "rag") > _weight(ancient, "rag")


def test_repetition_saturates_rather_than_growing_without_bound():
    profile = _profile(_three_interests())
    many = [_event(EventType.SAVE, "rag") for _ in range(200)]
    updated, _ = apply_feedback(profile, many, now=NOW)

    assert _weight(updated, "rag") <= BEHAVIOURAL_WEIGHT_CEILING


def test_an_interest_can_be_reduced_and_then_recover():
    """A reader is not classified permanently by an early week."""
    profile = _profile(_three_interests())
    after_negative, _ = apply_feedback(
        profile, [_event(EventType.NOT_RELEVANT, "rag") for _ in range(3)], now=NOW
    )
    assert _weight(after_negative, "rag") < _weight(profile, "rag")

    recovered, _ = apply_feedback(
        after_negative, [_event(EventType.SAVE, "rag") for _ in range(5)], now=NOW
    )
    assert _weight(recovered, "rag") > _weight(after_negative, "rag")


def test_an_unattributed_event_changes_nothing():
    """A guess about which interest earned a click is noise, and it accumulates."""
    profile = _profile(_three_interests())
    updated, summary = apply_feedback(
        profile, [FeedbackEvent(EventType.SAVE, uuid.uuid4(), NOW)], now=NOW
    )

    assert summary.unattributed == 1
    assert summary.weight_deltas == {}
    assert _weight(updated, "rag") == _weight(profile, "rag")


def test_a_negative_on_a_negative_interest_strengthens_it():
    """'Less like this' about something already unwanted is agreement."""
    interests = (
        _stated("rag", "RAG", 0),
        _stated("img", "Image generation", 3, polarity=Polarity.NEGATIVE),
    )
    profile = _profile(interests)
    updated, _ = apply_feedback(profile, [_event(EventType.NOT_RELEVANT, "img")], now=NOW)

    assert _weight(updated, "img") > _weight(profile, "img")


def test_rates_are_reported_per_impression():
    """Otherwise a feed is rewarded for showing less."""
    events = [FeedbackEvent(EventType.IMPRESSION, uuid.uuid4(), NOW) for _ in range(10)]
    events += [FeedbackEvent(EventType.SAVE, uuid.uuid4(), NOW) for _ in range(2)]

    assert impression_rate(events, EventType.SAVE) == pytest.approx(0.2)


# --- helpers ------------------------------------------------------------------


def _basis(index: int) -> np.ndarray:
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    vector[index] = 1.0
    return vector


def _unit(vector: np.ndarray) -> np.ndarray:
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _stated(key: str, label: str, axis: int, **overrides) -> Interest:
    return Interest(
        key=key,
        kind=InterestKind.STATED,
        label=label,
        text=f"a described research interest about {label}",
        vector=_basis(axis),
        **overrides,
    )


def _topic(key: str, value: str) -> Interest:
    return Interest(key=key, kind=InterestKind.TOPIC, label=value, value=value)


def _three_interests() -> tuple[Interest, ...]:
    return (
        _stated("rag", "RAG", 0),
        _stated("sys", "AI systems", 1),
        _stated("gen", "Genomics", 2),
    )


def _profile(interests, **overrides) -> InterestProfile:
    return InterestProfile(interests=tuple(interests), **overrides)


def _encoded(interests, *, preferences: Preferences | None = None) -> EncodedProfile:
    profile = InterestProfile(
        interests=tuple(interests), preferences=preferences or Preferences()
    )
    return EncodedProfile(profile=profile, model_key="specter2@v1")


def _facts(**overrides) -> PaperFacts:
    overrides.setdefault("paper_id", uuid.uuid4())
    return PaperFacts(**overrides)


def _extract(facts: PaperFacts, profile: EncodedProfile):
    return extract(
        Candidate(facts.paper_id, (CandidateReason(CandidateOrigin.SEMANTIC_INTEREST),)),
        facts,
        profile,
        today=TODAY,
    )


def _event(event_type: EventType, interest_key: str, *, days_ago: float = 0.0) -> FeedbackEvent:
    return FeedbackEvent(
        event_type=event_type,
        paper_id=uuid.uuid4(),
        occurred_at=NOW - timedelta(days=days_ago),
        interest_key=interest_key,
        position=1,
    )


def _weight(profile: InterestProfile, key: str) -> float:
    return next(i.weight for i in profile.interests if i.key == key)
