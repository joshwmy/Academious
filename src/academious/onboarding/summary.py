"""What Academious believes this reader cares about, in their own words.

**Derived from the built profile, never from the draft.** The point of a summary
is to let someone check the system's representation against their intention, and
a summary rendered from the draft would only ever confirm that the form
remembered what they typed. Reading it back out of the `InterestProfile` means a
mapping bug, a dropped example paper or a silently merged pair of interests
shows up on the screen where it matters.

**No model, no template engine, no prose generation.** The labels are the
reader's own text and the canonical field names; the levels come from
`levels.py`'s inverse mappings. An LLM here would cost money per profile to
paraphrase strings that are already exactly right, and would occasionally
paraphrase them wrongly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from academious.onboarding.levels import (
    AVOIDANCE_LABEL,
    EXPLORATION_LABEL,
    FRESHNESS_LABEL,
    IMPORTANCE_LABEL,
    PUBLICATION_LABEL,
    Avoidance,
    Importance,
    avoidance_for_weight,
    exploration_for,
    freshness_for,
    importance_for_weight,
    publication_for,
)
from academious.personalise.profile import (
    Horizon,
    Interest,
    InterestKind,
    InterestProfile,
    Polarity,
)


@dataclass(frozen=True, slots=True)
class SummarySection:
    """One heading and the things under it."""

    heading: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    """A profile as a person would describe it."""

    core_interests: tuple[str, ...] = ()
    other_interests: tuple[str, ...] = ()
    exploring_now: tuple[str, ...] = ()
    broad_areas: tuple[str, ...] = ()
    example_papers: tuple[str, ...] = ()
    avoiding: tuple[str, ...] = ()
    blocked_topics: tuple[str, ...] = ()
    #: Label and value, e.g. ("New research", "Balanced").
    preferences: tuple[tuple[str, str], ...] = ()

    def sections(self) -> tuple[SummarySection, ...]:
        """Non-empty sections only. An empty heading tells a reader nothing."""
        candidates = (
            SummarySection("Core interests", self.core_interests),
            SummarySection("Other interests", self.other_interests),
            SummarySection("Exploring right now", self.exploring_now),
            SummarySection("Broad areas", self.broad_areas),
            SummarySection("Papers you chose", self.example_papers),
            SummarySection("Less interested in", self.avoiding),
            SummarySection("Blocked topics", self.blocked_topics),
        )
        return tuple(section for section in candidates if section.items)

    def lines(self) -> tuple[str, ...]:
        """The summary as plain text, for a terminal, a log or a test."""
        out: list[str] = []
        for section in self.sections():
            out.append(f"{section.heading}:")
            out.extend(f"  - {item}" for item in section.items)
        if self.preferences:
            out.append("Preferences:")
            out.extend(f"  - {label}: {value}" for label, value in self.preferences)
        return tuple(out)


def summarise(profile: InterestProfile) -> ProfileSummary:
    """Describe a built profile without inventing anything about it."""
    positives = [i for i in profile.interests if i.polarity is Polarity.POSITIVE]
    negatives = [i for i in profile.interests if i.polarity is Polarity.NEGATIVE]

    stated = [i for i in positives if i.kind is InterestKind.STATED]
    papers = [i for i in positives if i.kind is InterestKind.PAPER]
    fields = [i for i in positives if i.kind is InterestKind.FIELD]

    # Short-horizon interests are listed separately rather than sorted in among
    # the rest. They behave differently - they are what a preview refinement
    # produces, and they decay - so describing them as standing interests would
    # be describing them wrongly.
    long_term = [i for i in stated if i.horizon is Horizon.LONG]
    short_term = [i for i in [*stated, *papers] if i.horizon is Horizon.SHORT]

    core = _labels(long_term, Importance.CORE)
    other = tuple(label for label in _labels(long_term) if label not in core)

    return ProfileSummary(
        core_interests=core,
        other_interests=other,
        exploring_now=tuple(interest.label for interest in short_term),
        broad_areas=tuple(interest.label for interest in fields),
        example_papers=tuple(
            interest.label for interest in papers if interest.horizon is Horizon.LONG
        ),
        avoiding=tuple(_avoiding(interest) for interest in negatives),
        blocked_topics=tuple(sorted(profile.blocked_topics)),
        preferences=_preferences(profile),
    )


def _labels(interests: Sequence[Interest], only: Importance | None = None) -> tuple[str, ...]:
    if only is None:
        return tuple(interest.label for interest in interests)
    return tuple(
        interest.label for interest in interests if importance_for_weight(interest.weight) is only
    )


def _avoiding(interest: Interest) -> str:
    """A dislike, qualified when it is the milder of the two levels.

    The strong level is left unqualified: under a heading that already says
    *less interested in*, "pure image generation" needs no adverb, and adding
    one to both levels would erase the difference between them.
    """
    level = avoidance_for_weight(interest.weight)
    if level is Avoidance.LESS:
        return f"{interest.label} ({AVOIDANCE_LABEL[level].lower()})"
    return interest.label


def _preferences(profile: InterestProfile) -> tuple[tuple[str, str], ...]:
    preferences = profile.preferences
    return (
        ("New research", FRESHNESS_LABEL[freshness_for(preferences.freshness_appetite)]),
        ("Exploration", EXPLORATION_LABEL[exploration_for(preferences.exploration)]),
        (
            "Publication stage",
            PUBLICATION_LABEL[
                publication_for(
                    preferences.preprint_appetite,
                    peer_reviewed_only=profile.require_peer_reviewed,
                )
            ],
        ),
    )


def describe_importance(interest: Interest) -> str:
    """The level one interest sits at, for a per-interest control in a UI."""
    return IMPORTANCE_LABEL[importance_for_weight(interest.weight)]
