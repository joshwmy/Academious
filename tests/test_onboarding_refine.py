"""Correcting a profile from its preview.

Refinement is the part of onboarding a reader uses when the system got them
wrong, so the properties worth testing are not that something changed but
*what* changed and whether they can see it. Every test below asserts on the
returned draft, because the draft is what the reader is shown and what they can
undo.
"""

from __future__ import annotations

import uuid

import pytest

from academious.onboarding.builder import example_paper_key, field_key, interest_key
from academious.onboarding.draft import (
    ProfileDraft,
    Severity,
    TextInterest,
    validate,
)
from academious.onboarding.levels import Avoidance, Importance
from academious.onboarding.refine import (
    Refinement,
    RefinementAction,
    add_interest,
    add_negative_interest,
    apply_all,
    apply_refinement,
)
from academious.personalise.profile import Horizon

CORE = "recommendation systems and ranking"
SECOND = "distributed systems and consensus"


@pytest.fixture
def draft() -> ProfileDraft:
    return ProfileDraft(
        fields=("computer-science",),
        interests=(
            TextInterest(CORE, Importance.CORE),
            TextInterest(SECOND, Importance.INTERESTED),
        ),
    )


@pytest.fixture
def paper_id() -> uuid.UUID:
    return uuid.uuid4()


# --- the no-op that is still a verb -------------------------------------------


def test_saying_a_recommendation_fits_changes_nothing(draft, paper_id):
    result = apply_refinement(draft, Refinement(action=RefinementAction.FITS, paper_id=paper_id))

    assert result.draft == draft
    assert result.changes == ()


# --- more like this -----------------------------------------------------------


def test_more_like_this_adds_the_paper_as_an_example(draft, paper_id):
    result = apply_refinement(
        draft,
        Refinement(
            action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id, label="A Good Paper"
        ),
    )

    assert [p.paper_id for p in result.draft.example_papers] == [paper_id]
    assert result.draft.example_papers[0].label == "A Good Paper"
    assert result.changes


def test_more_like_this_creates_a_short_term_interest(draft, paper_id):
    """A reaction to one item is evidence about this week, not about the year."""
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    )

    assert result.draft.example_papers[0].horizon is Horizon.SHORT


def test_a_short_term_refinement_leaves_the_long_term_interests_alone(draft, paper_id):
    """The whole point of two horizons: this fortnight must not overwrite the year."""
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    )

    assert result.draft.interests == draft.interests
    assert all(i.horizon is Horizon.LONG for i in result.draft.interests)


def test_more_like_this_twice_emphasises_rather_than_duplicates(draft, paper_id):
    once = apply_refinement(
        draft, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    ).draft
    twice = apply_refinement(
        once, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    ).draft

    assert len(twice.example_papers) == 1
    assert twice.example_papers[0].importance is Importance.CORE


# --- less like this, and the stronger version ---------------------------------


def test_less_like_this_records_a_mild_dislike(draft, paper_id):
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.LESS_LIKE_THIS, paper_id=paper_id)
    )

    assert [p.strength for p in result.draft.negative_papers] == [Avoidance.LESS]
    assert result.draft.interests == draft.interests, "no interest was touched"


def test_not_interested_is_stronger_than_less_like_this(draft, paper_id):
    """Two things at once, which is what makes it a different button."""
    key = interest_key(CORE)
    milder = apply_refinement(
        draft,
        Refinement(action=RefinementAction.LESS_LIKE_THIS, paper_id=paper_id, interest_key=key),
    ).draft
    stronger = apply_refinement(
        draft,
        Refinement(action=RefinementAction.NOT_INTERESTED, paper_id=paper_id, interest_key=key),
    ).draft

    assert milder.negative_papers[0].strength is Avoidance.LESS
    assert stronger.negative_papers[0].strength is Avoidance.AVOID

    assert {i.text: i.importance for i in stronger.interests}[CORE] is Importance.INTERESTED
    assert {i.text: i.importance for i in milder.interests}[CORE] is Importance.CORE


def test_not_interested_without_an_interest_key_still_records_the_dislike(draft, paper_id):
    """A preview item attributed to nothing is still a paper the reader rejected."""
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.NOT_INTERESTED, paper_id=paper_id)
    )

    assert result.draft.negative_papers[0].strength is Avoidance.AVOID
    assert result.draft.interests == draft.interests


def test_pushing_away_a_paper_you_had_chosen_removes_it_from_your_examples(draft, paper_id):
    """The draft must never say both things at once - validation refuses that."""
    chosen = apply_refinement(
        draft, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    ).draft
    pushed = apply_refinement(
        chosen, Refinement(action=RefinementAction.LESS_LIKE_THIS, paper_id=paper_id)
    ).draft

    assert pushed.example_papers == ()
    assert [p.paper_id for p in pushed.negative_papers] == [paper_id]
    assert not [i for i in validate(pushed)[1] if i.code == "contradictory_example_paper"]


# --- interest-level corrections -----------------------------------------------


def test_too_dominant_lowers_the_interest_by_exactly_one_level(draft):
    result = apply_refinement(
        draft,
        Refinement(action=RefinementAction.LESS_FROM_INTEREST, interest_key=interest_key(CORE)),
    )
    by_text = {i.text: i.importance for i in result.draft.interests}

    assert by_text[CORE] is Importance.INTERESTED
    assert by_text[SECOND] is Importance.INTERESTED, "the other interest is untouched"


def test_more_from_an_interest_raises_it_by_exactly_one_level(draft):
    result = apply_refinement(
        draft,
        Refinement(action=RefinementAction.MORE_FROM_INTEREST, interest_key=interest_key(SECOND)),
    )

    assert {i.text: i.importance for i in result.draft.interests}[SECOND] is Importance.CORE


def test_pressing_more_on_a_core_interest_is_not_an_error(draft):
    """Saturating, and reported as no change rather than as a mistake."""
    result = apply_refinement(
        draft,
        Refinement(action=RefinementAction.MORE_FROM_INTEREST, interest_key=interest_key(CORE)),
    )

    assert result.draft == draft
    assert [i.code for i in result.issues] == ["refinement_had_no_effect"]
    assert all(i.severity is Severity.WARNING for i in result.issues)


def test_an_unknown_interest_key_is_a_warning_not_a_silent_no_op(draft):
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.REMOVE_INTEREST, interest_key="i-nonsense")
    )

    assert result.draft == draft
    assert [i.code for i in result.issues] == ["unknown_interest"]


def test_removing_an_interest_removes_exactly_that_one(draft):
    result = apply_refinement(
        draft, Refinement(action=RefinementAction.REMOVE_INTEREST, interest_key=interest_key(CORE))
    )

    assert [i.text for i in result.draft.interests] == [SECOND]
    assert result.draft.fields == draft.fields


def test_a_broad_area_can_be_removed_by_its_key(draft):
    result = apply_refinement(
        draft,
        Refinement(
            action=RefinementAction.REMOVE_INTEREST, interest_key=field_key("computer-science")
        ),
    )

    assert result.draft.fields == ()


def test_an_example_paper_can_be_re_weighted_by_its_key(draft, paper_id):
    chosen = apply_refinement(
        draft, Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id)
    ).draft
    result = apply_refinement(
        chosen,
        Refinement(
            action=RefinementAction.MORE_FROM_INTEREST,
            interest_key=example_paper_key(paper_id),
        ),
    )

    assert result.draft.example_papers[0].importance is Importance.CORE


# --- blocking -----------------------------------------------------------------


def test_blocking_a_topic_adds_it_once(draft):
    blocked = apply_refinement(
        draft, Refinement(action=RefinementAction.BLOCK_TOPIC, topic_id="T11689")
    ).draft
    again = apply_refinement(
        blocked, Refinement(action=RefinementAction.BLOCK_TOPIC, topic_id="T11689")
    ).draft

    assert again.blocked_topics == ("T11689",)


def test_blocking_without_a_topic_is_refused_with_a_message(draft):
    result = apply_refinement(draft, Refinement(action=RefinementAction.BLOCK_TOPIC))

    assert [i.code for i in result.issues] == ["incomplete_refinement"]


# --- composition and immutability ---------------------------------------------


def test_refinements_apply_in_order_and_accumulate(draft, paper_id):
    other = uuid.uuid4()
    result = apply_all(
        draft,
        [
            Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id),
            Refinement(action=RefinementAction.LESS_LIKE_THIS, paper_id=other),
            Refinement(
                action=RefinementAction.LESS_FROM_INTEREST, interest_key=interest_key(CORE)
            ),
        ],
    )

    assert len(result.draft.example_papers) == 1
    assert len(result.draft.negative_papers) == 1
    assert {i.text: i.importance for i in result.draft.interests}[CORE] is Importance.INTERESTED
    assert len(result.changes) == 3


def test_refinement_never_mutates_the_draft_it_was_given(draft, paper_id):
    """The client still holds this object; the server has no business editing it."""
    apply_all(
        draft,
        [
            Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id),
            Refinement(action=RefinementAction.BLOCK_TOPIC, topic_id="T1"),
        ],
    )

    assert draft.example_papers == ()
    assert draft.blocked_topics == ()


def test_the_draft_stays_valid_after_refinement(draft, paper_id):
    result = apply_all(
        draft,
        [
            Refinement(action=RefinementAction.MORE_LIKE_THIS, paper_id=paper_id),
            Refinement(
                action=RefinementAction.NOT_INTERESTED,
                paper_id=uuid.uuid4(),
                interest_key=interest_key(SECOND),
            ),
        ],
    )
    _, issues = validate(result.draft)

    assert not [i for i in issues if i.severity is Severity.ERROR]


def test_interests_can_be_added_and_removed_by_hand(draft):
    grown = add_interest(draft, "retrieval augmented generation", Importance.CORE)
    disliked = add_negative_interest(grown, "generative image synthesis")

    assert len(disliked.interests) == 3
    assert [n.text for n in disliked.negatives] == ["generative image synthesis"]
    assert [n.strength for n in disliked.negatives] == [Avoidance.AVOID]


def test_a_hand_added_negative_is_still_validated(draft):
    """Nothing about refinement bypasses the rules the form obeys."""
    contradiction = add_negative_interest(draft, CORE)
    _, issues = validate(contradiction)

    assert "contradictory_interest" in {i.code for i in issues}


def test_negative_interests_added_by_hand_survive_normalisation(draft):
    doubled = add_negative_interest(
        add_negative_interest(draft, "generative image synthesis"),
        "Generative-Image  Synthesis",
    )
    cleaned, issues = validate(doubled)

    assert len(cleaned.negatives) == 1
    assert "duplicate_negative" in {i.code for i in issues}
