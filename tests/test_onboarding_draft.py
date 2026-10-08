"""What a reader is allowed to say, and what happens when they say it badly.

Every test here is pure: no database, no model, no network. Validation is the
part of profile creation a person actually collides with, so it gets the
sharpest tests - a message that names the wrong thing is worse than none.
"""

from __future__ import annotations

import uuid

from academious.onboarding.draft import (
    MAX_INTEREST_CHARS,
    DiscoveryChoices,
    ExamplePaper,
    NegativeInterest,
    NegativePaper,
    ProfileDraft,
    Severity,
    TextInterest,
    canonical,
    errors,
    validate,
)
from academious.onboarding.levels import (
    IMPORTANCE_WEIGHT,
    Avoidance,
    ExplorationLevel,
    FreshnessLevel,
    Importance,
    PublicationStage,
    step_importance,
)
from academious.personalise.profile import MAX_INTERESTS, MIN_DESCRIPTION_CHARS

INTEREST = "recommendation systems and ranking"


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


# --- the minimum a profile can be ---------------------------------------------


def test_one_broad_area_is_a_valid_profile():
    """The cold-start floor: someone who only ticked a box."""
    draft, issues = validate(ProfileDraft(fields=("computer-science",)))

    assert not errors(issues)
    assert draft.positive_count == 1


def test_one_typed_interest_is_a_valid_profile():
    draft, issues = validate(ProfileDraft(interests=(TextInterest(INTEREST),)))

    assert not errors(issues)
    assert draft.interests[0].importance is Importance.INTERESTED


def test_a_profile_of_only_dislikes_is_refused():
    """Nothing to rank, so this must fail loudly rather than quietly empty out."""
    _, issues = validate(ProfileDraft(negatives=(NegativeInterest("pure image generation"),)))

    assert "no_positive_interest" in _codes(errors(issues))


def test_an_empty_draft_is_refused():
    _, issues = validate(ProfileDraft())

    assert "no_positive_interest" in _codes(errors(issues))


# --- fields -------------------------------------------------------------------


def test_an_unknown_field_is_refused_rather_than_ignored():
    """Ignoring it answers a request about biology with a profile that never heard of it."""
    _, issues = validate(ProfileDraft(fields=("computer-science", "astrology")))

    problems = errors(issues)
    assert "unknown_field" in _codes(problems)
    assert any(issue.subject == "astrology" for issue in problems)


def test_a_repeated_field_is_collapsed_silently():
    draft, issues = validate(ProfileDraft(fields=("computer-science", "computer-science")))

    assert draft.fields == ("computer-science",)
    assert not issues


# --- free text ----------------------------------------------------------------


def test_an_interest_too_short_to_match_is_refused_with_advice():
    _, issues = validate(ProfileDraft(interests=(TextInterest("RAG"),)))

    problems = errors(issues)
    assert "interest_too_short" in _codes(problems)
    assert str(MIN_DESCRIPTION_CHARS) in problems[0].message


def test_an_oversized_interest_is_refused():
    _, issues = validate(ProfileDraft(interests=(TextInterest("a" * (MAX_INTEREST_CHARS + 1)),)))

    assert "interest_too_long" in _codes(errors(issues))


def test_whitespace_inside_an_interest_is_collapsed():
    draft, _ = validate(
        ProfileDraft(interests=(TextInterest("  recommendation   systems   research  "),))
    )

    assert draft.interests[0].text == "recommendation systems research"


# --- deduplication ------------------------------------------------------------


def test_case_and_punctuation_variants_are_one_interest():
    draft, issues = validate(
        ProfileDraft(
            interests=(
                TextInterest("machine learning systems"),
                TextInterest("Machine-Learning  Systems"),
            )
        )
    )

    assert len(draft.interests) == 1
    assert {issue.severity for issue in issues} == {Severity.WARNING}


def test_a_merged_duplicate_keeps_the_stronger_importance():
    """Someone who listed a subject twice, once as core, meant core."""
    draft, _ = validate(
        ProfileDraft(
            interests=(
                TextInterest(INTEREST, Importance.OCCASIONAL),
                TextInterest(INTEREST.upper(), Importance.CORE),
            )
        )
    )

    assert draft.interests[0].importance is Importance.CORE


def test_an_abbreviation_is_not_merged_with_its_expansion():
    """A false merge deletes a stated interest; two similar ones cost one distance."""
    assert canonical("ML") != canonical("machine learning")

    draft, _ = validate(
        ProfileDraft(
            interests=(
                TextInterest("machine learning for biology"),
                TextInterest("ML methods for biological data"),
            )
        )
    )

    assert len(draft.interests) == 2


def test_a_repeated_example_paper_is_merged():
    paper_id = uuid.uuid4()
    draft, issues = validate(
        ProfileDraft(
            example_papers=(
                ExamplePaper(paper_id, Importance.OCCASIONAL),
                ExamplePaper(paper_id, Importance.CORE),
            )
        )
    )

    assert len(draft.example_papers) == 1
    assert draft.example_papers[0].importance is Importance.CORE
    assert "duplicate_example_paper" in _codes(issues)


# --- contradictions -----------------------------------------------------------


def test_the_same_words_wanted_and_unwanted_is_refused_not_resolved():
    """Guessing would hand a reader the opposite of what they asked for."""
    _, issues = validate(
        ProfileDraft(
            interests=(TextInterest(INTEREST),),
            negatives=(NegativeInterest(INTEREST.title()),),
        )
    )

    assert "contradictory_interest" in _codes(errors(issues))


def test_the_same_paper_chosen_and_rejected_is_refused():
    paper_id = uuid.uuid4()
    _, issues = validate(
        ProfileDraft(
            interests=(TextInterest(INTEREST),),
            example_papers=(ExamplePaper(paper_id),),
            negative_papers=(NegativePaper(paper_id),),
        )
    )

    assert "contradictory_example_paper" in _codes(errors(issues))


# --- size limits, which are also the cost bound -------------------------------


def test_too_many_interests_is_refused_with_the_limit_named():
    _, issues = validate(
        ProfileDraft(interests=tuple(TextInterest(f"{INTEREST} number {n}") for n in range(30)))
    )

    assert "too_many_interests" in _codes(errors(issues))


def test_the_total_across_stages_is_bounded():
    """Each stage under its own limit can still exceed what a profile may hold."""
    draft = ProfileDraft(
        fields=("computer-science", "medicine", "physics-and-astronomy", "chemistry"),
        interests=tuple(TextInterest(f"{INTEREST} number {n}") for n in range(8)),
        example_papers=tuple(ExamplePaper(uuid.uuid4()) for _ in range(6)),
    )
    _, issues = validate(draft)

    assert "too_many_total_interests" in _codes(errors(issues))
    assert str(MAX_INTERESTS) in "".join(issue.message for issue in issues)


def test_blocked_topics_are_deduplicated():
    draft, _ = validate(
        ProfileDraft(fields=("computer-science",), blocked_topics=("T11689", "T11689", "  ", "T2"))
    )

    assert draft.blocked_topics == ("T11689", "T2")


# --- the level vocabulary -----------------------------------------------------


def test_importance_is_strictly_ordered():
    """Core has to outrank occasional, or the emphasis feature says nothing."""
    assert (
        IMPORTANCE_WEIGHT[Importance.CORE]
        > IMPORTANCE_WEIGHT[Importance.INTERESTED]
        > IMPORTANCE_WEIGHT[Importance.OCCASIONAL]
    )


def test_stepping_importance_saturates_at_both_ends():
    assert step_importance(Importance.CORE, 1) is Importance.CORE
    assert step_importance(Importance.OCCASIONAL, -1) is Importance.OCCASIONAL
    assert step_importance(Importance.INTERESTED, 1) is Importance.CORE
    assert step_importance(Importance.INTERESTED, -1) is Importance.OCCASIONAL


def test_the_discovery_defaults_are_the_measured_ones():
    """A reader who skips the preferences screen gets the benchmarked behaviour."""
    choices = DiscoveryChoices()

    assert choices.freshness is FreshnessLevel.BALANCED
    assert choices.exploration is ExplorationLevel.BALANCED
    assert choices.publication is PublicationStage.INCLUDE_PREPRINTS


def test_avoidance_has_two_meaningfully_different_levels():
    assert Avoidance.LESS is not Avoidance.AVOID


def test_validation_reports_everything_at_once_and_never_raises():
    """A reader with two problems should be told both, not the first."""
    _, issues = validate(ProfileDraft(fields=("astrology",), interests=(TextInterest("RAG"),)))

    assert {"unknown_field", "interest_too_short"} <= _codes(errors(issues))


def test_validation_does_not_mutate_the_draft_it_was_given():
    original = ProfileDraft(interests=(TextInterest("  spaced   out   interest  "),))
    validate(original)

    assert original.interests[0].text == "  spaced   out   interest  "
