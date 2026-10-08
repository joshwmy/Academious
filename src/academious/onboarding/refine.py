"""Correcting a profile by reacting to the feed it produced.

**Refinement edits the draft, not the profile.** The profile is derived, and
deriving it again from a corrected draft is cheap; editing the profile directly
would put the reader's stated choices and the system's representation of them
permanently out of step, so the summary screen would stop describing what the
reader actually chose. Everything here returns a new `ProfileDraft`, and the
caller rebuilds.

**Deterministic and reversible, not learned.** Each action is a stated rule with
one effect, and every effect is visible in the returned draft: an added example
paper, an added dislike, an importance level moved by exactly one step. Nothing
is inferred, nothing accumulates invisibly, and a reader can undo any of it by
removing something they can see. `feedback.py` is where behavioural learning
will live, and it needs impressions and accounts that do not exist.

**Horizons follow one conservative rule.** Onboarding produces long-term
interests; *more like this* in a preview produces a short-term one. The
justification is that a reaction to a single item is evidence about this week
rather than about the year - someone spending a fortnight on retrieval-augmented
generation should not have their standing interest in distributed systems
overwritten by it. Anything cleverer than that rule would be guessing at intent.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from academious.onboarding.builder import (
    example_paper_key,
    field_key,
    interest_key,
    negative_interest_key,
)
from academious.onboarding.draft import (
    DraftIssue,
    ExamplePaper,
    NegativeInterest,
    NegativePaper,
    ProfileDraft,
    Severity,
    TextInterest,
)
from academious.onboarding.levels import Avoidance, Importance, step_importance
from academious.personalise.profile import Horizon


class RefinementAction(StrEnum):
    """What a reader can say about a previewed recommendation or an interest.

    Deliberately the same vocabulary as `feedback.EventType`'s explicit
    positives and negatives, minus everything inferred. When accounts arrive
    these become logged events against a stored profile rather than a second set
    of verbs over a draft.
    """

    #: An acknowledgement. Changes nothing, and exists so a client can offer
    #: "this fits" without it being a different kind of thing from the buttons
    #: beside it - and so a future impression log already has a name for it.
    FITS = "fits"
    MORE_LIKE_THIS = "more_like_this"
    LESS_LIKE_THIS = "less_like_this"
    NOT_INTERESTED = "not_interested"
    #: About an interest rather than a paper.
    LESS_FROM_INTEREST = "less_from_interest"
    MORE_FROM_INTEREST = "more_from_interest"
    REMOVE_INTEREST = "remove_interest"
    BLOCK_TOPIC = "block_topic"


@dataclass(frozen=True, slots=True)
class Refinement:
    """One correction, with whatever the preview knew about its target."""

    action: RefinementAction
    #: The previewed paper the reader reacted to, for the paper actions.
    paper_id: uuid.UUID | None = None
    #: The interest the feed attributed that paper to, taken from the preview
    #: rather than recomputed. Recomputing could pick a different interest from
    #: the one the reader was shown, which would land the correction somewhere
    #: they did not aim it.
    interest_key: str | None = None
    #: A canonical topic id, for BLOCK_TOPIC.
    topic_id: str | None = None
    #: The paper's title, so the draft can carry a readable label.
    label: str | None = None


@dataclass(frozen=True, slots=True)
class RefineResult:
    draft: ProfileDraft
    #: What changed, in the reader's terms. Empty when the action was a no-op,
    #: which is information rather than a failure.
    changes: tuple[str, ...] = ()
    issues: tuple[DraftIssue, ...] = ()


def apply_refinement(draft: ProfileDraft, refinement: Refinement) -> RefineResult:
    """Apply one correction. Never mutates the draft it was given."""
    match refinement.action:
        case RefinementAction.FITS:
            return RefineResult(draft=draft)
        case RefinementAction.MORE_LIKE_THIS:
            return _more_like_this(draft, refinement)
        case RefinementAction.LESS_LIKE_THIS:
            return _less_like_this(draft, refinement, strength=Avoidance.LESS, step=0)
        case RefinementAction.NOT_INTERESTED:
            # Stronger than "less like this" in two ways at once, which is what
            # makes it a different button rather than a louder one: the dislike
            # is recorded at full strength, and the interest that produced the
            # item loses a level of importance.
            return _less_like_this(draft, refinement, strength=Avoidance.AVOID, step=-1)
        case RefinementAction.LESS_FROM_INTEREST:
            return _step_interest(draft, refinement.interest_key, delta=-1)
        case RefinementAction.MORE_FROM_INTEREST:
            return _step_interest(draft, refinement.interest_key, delta=1)
        case RefinementAction.REMOVE_INTEREST:
            return _remove_interest(draft, refinement)
        case RefinementAction.BLOCK_TOPIC:
            return _block_topic(draft, refinement)


def apply_all(draft: ProfileDraft, refinements: Sequence[Refinement]) -> RefineResult:
    """Fold several corrections in order. Order matters and belongs to the caller."""
    changes: list[str] = []
    issues: list[DraftIssue] = []
    current = draft
    for refinement in refinements:
        result = apply_refinement(current, refinement)
        current = result.draft
        changes.extend(result.changes)
        issues.extend(result.issues)
    return RefineResult(draft=current, changes=tuple(changes), issues=tuple(issues))


# --- paper reactions ----------------------------------------------------------


def _more_like_this(draft: ProfileDraft, refinement: Refinement) -> RefineResult:
    paper_id = refinement.paper_id
    if paper_id is None:
        return _missing(draft, "more_like_this needs a paper.")

    if paper_id in {paper.paper_id for paper in draft.example_papers}:
        # Already chosen. Raise its importance rather than adding it twice: the
        # reader said the same thing again, which is emphasis, not a duplicate.
        papers = tuple(
            replace(paper, importance=step_importance(paper.importance, 1))
            if paper.paper_id == paper_id
            else paper
            for paper in draft.example_papers
        )
        return RefineResult(
            draft=replace(draft, example_papers=papers),
            changes=("Raised the importance of a paper you had already chosen.",),
        )

    added = ExamplePaper(
        paper_id=paper_id,
        importance=Importance.INTERESTED,
        # Short-term; see the module docstring. A reaction to one item in one
        # preview is evidence about now.
        horizon=Horizon.SHORT,
        label=refinement.label,
    )
    return RefineResult(
        draft=replace(draft, example_papers=(*draft.example_papers, added)),
        changes=("Added it as an example of what you want more of, for now.",),
    )


def _less_like_this(
    draft: ProfileDraft, refinement: Refinement, *, strength: Avoidance, step: int
) -> RefineResult:
    paper_id = refinement.paper_id
    if paper_id is None:
        return _missing(draft, "That action needs a paper.")

    changes: list[str] = []
    negatives = draft.negative_papers
    if paper_id in {paper.paper_id for paper in negatives}:
        negatives = tuple(
            replace(paper, strength=strength) if paper.paper_id == paper_id else paper
            for paper in negatives
        )
        changes.append("Strengthened a dislike you had already recorded.")
    else:
        negatives = (
            *negatives,
            NegativePaper(paper_id=paper_id, strength=strength, label=refinement.label),
        )
        changes.append("Recorded it as a paper to steer away from.")

    # Drop it as a positive example if it was one, so the draft never says both
    # things at once - `draft.validate` refuses that, and refusing the reader's
    # own correction would be absurd.
    papers = tuple(paper for paper in draft.example_papers if paper.paper_id != paper_id)
    if len(papers) != len(draft.example_papers):
        changes.append("Removed it from your example papers.")

    updated = replace(draft, negative_papers=negatives, example_papers=papers)
    if step and refinement.interest_key:
        stepped = _step_interest(updated, refinement.interest_key, delta=step)
        return RefineResult(
            draft=stepped.draft, changes=(*changes, *stepped.changes), issues=stepped.issues
        )
    return RefineResult(draft=updated, changes=tuple(changes))


# --- interest reactions -------------------------------------------------------


def _step_interest(draft: ProfileDraft, key: str | None, *, delta: int) -> RefineResult:
    if not key:
        return _missing(draft, "That action needs an interest.")

    changed = False
    interests = []
    for interest in draft.interests:
        if interest_key(interest.text) == key:
            moved = step_importance(interest.importance, delta)
            changed = changed or moved is not interest.importance
            interests.append(replace(interest, importance=moved))
        else:
            interests.append(interest)

    papers = []
    for paper in draft.example_papers:
        if example_paper_key(paper.paper_id) == key:
            moved = step_importance(paper.importance, delta)
            changed = changed or moved is not paper.importance
            papers.append(replace(paper, importance=moved))
        else:
            papers.append(paper)

    if not changed:
        # Either the key names nothing in this draft, or the level was already
        # at the end of the scale, or it is a broad area, which carries no
        # importance. All three are reported as no change rather than as an
        # error: pressing "more of this" on a core interest is not a mistake.
        return RefineResult(
            draft=draft,
            issues=(
                DraftIssue(
                    code="refinement_had_no_effect",
                    message=(
                        "That interest is already as strong or as weak as it goes, or it "
                        "is a broad area, which carries no importance level."
                    ),
                    severity=Severity.WARNING,
                    subject=key,
                ),
            ),
        )

    direction = "More" if delta > 0 else "Less"
    return RefineResult(
        draft=replace(draft, interests=tuple(interests), example_papers=tuple(papers)),
        changes=(f"{direction} weight on that interest.",),
    )


def _remove_interest(draft: ProfileDraft, refinement: Refinement) -> RefineResult:
    key = refinement.interest_key
    if not key:
        return _missing(draft, "Removing an interest needs an interest.")

    interests = tuple(i for i in draft.interests if interest_key(i.text) != key)
    negatives = tuple(n for n in draft.negatives if negative_interest_key(n.text) != key)
    papers = tuple(p for p in draft.example_papers if example_paper_key(p.paper_id) != key)
    fields = tuple(slug for slug in draft.fields if field_key(slug) != key)

    removed = (
        len(interests) != len(draft.interests)
        or len(negatives) != len(draft.negatives)
        or len(papers) != len(draft.example_papers)
        or len(fields) != len(draft.fields)
    )
    if not removed:
        return RefineResult(
            draft=draft,
            issues=(
                DraftIssue(
                    code="unknown_interest",
                    message="There is no such interest in this profile.",
                    severity=Severity.WARNING,
                    subject=key,
                ),
            ),
        )
    return RefineResult(
        draft=replace(
            draft,
            interests=interests,
            negatives=negatives,
            example_papers=papers,
            fields=fields,
        ),
        changes=("Removed that interest.",),
    )


def _block_topic(draft: ProfileDraft, refinement: Refinement) -> RefineResult:
    topic = (refinement.topic_id or "").strip()
    if not topic:
        return _missing(draft, "Blocking needs a topic.")
    if topic in draft.blocked_topics:
        return RefineResult(draft=draft)
    return RefineResult(
        draft=replace(draft, blocked_topics=(*draft.blocked_topics, topic)),
        changes=("Blocked that topic; papers carrying it will not appear.",),
    )


def add_interest(draft: ProfileDraft, text: str, importance: Importance) -> ProfileDraft:
    """Add an interest in words, at a stated importance. Validation is `validate`'s."""
    return replace(
        draft, interests=(*draft.interests, TextInterest(text=text, importance=importance))
    )


def add_negative_interest(draft: ProfileDraft, text: str) -> ProfileDraft:
    """Add a dislike in words."""
    return replace(draft, negatives=(*draft.negatives, NegativeInterest(text=text)))


def _missing(draft: ProfileDraft, message: str) -> RefineResult:
    return RefineResult(
        draft=draft, issues=(DraftIssue(code="incomplete_refinement", message=message),)
    )
