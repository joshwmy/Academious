"""What a reader did, and what that is allowed to mean.

Nothing here is persisted yet - there are no accounts. It exists now because one
part of it is expensive to retrofit and nearly free to define early:
**impressions**. Without a record of what a reader was *shown*, a missing click
cannot be interpreted. Did they reject the paper, or never see it? Clicks
without impressions cannot train a ranker however many clicks there are, and a
feed that starts logging clicks first spends its first months producing data
that has to be thrown away. So the exposure event is defined before the system
that emits it.

**A non-click is not a negative.** The most common mistake in this part of a
recommender, and wrong for reasons that worsen with scale: position bias means
item ten was skipped for being tenth; exposure bias means the reader stopped at
item four; and a paper is expensive to evaluate, so *not opening* is usually
"not right now" rather than "not for me". `is_negative_evidence` says no to all
of it. Only explicit negatives are negatives.

**Interest updates are reversible, decayed and saturating.** A reader is not
classified by their first week: weight moves gradually, old evidence loses
influence on a schedule, and no amount of reading one topic lets it grow without
bound. Reversibility matters most - someone whose research direction changes
must be able to drag the feed with them, and a model that cannot forget will
eventually be wrong about a person forever.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from academious.personalise.profile import (
    MAX_WEIGHT,
    Horizon,
    Interest,
    InterestProfile,
    Polarity,
)

#: Half-life of one piece of evidence, per horizon. A short-term interest built
#: from this week's reading should fade within weeks; a long-term one should
#: survive a quiet month. These are what make interest drift possible rather
#: than a one-way accumulation.
SHORT_TERM_HALF_LIFE_DAYS = 10.0
LONG_TERM_HALF_LIFE_DAYS = 180.0

#: Ceiling on an interest's weight from accumulated behaviour. Saturating
#: rather than clipped: repeated evidence keeps helping with diminishing
#: returns, so a reader who reads a great deal about one thing does not lose
#: every other interest to it.
BEHAVIOURAL_WEIGHT_CEILING = 3.0


class EventType(StrEnum):
    """Every behaviour the feed can observe, grouped by what it implies.

    The grouping is the contract: a learned ranker treats these as different
    labels, and conflating a scroll-past with a dismissal poisons the training
    set in a way no amount of data recovers from.
    """

    #: Exposure. The paper was rendered in a feed the reader saw. Carries no
    #: opinion at all, and is the denominator for every rate.
    IMPRESSION = "impression"

    # Weak positive: attention spent, opinion not yet stated.
    OPEN = "open"
    ABSTRACT_EXPAND = "abstract_expand"
    OUTBOUND_CLICK = "outbound_click"

    # Strong positive: an act of intent.
    SAVE = "save"
    FOLLOW_FROM_ITEM = "follow_from_item"
    MORE_LIKE_THIS = "more_like_this"

    # Strong negative: explicitly stated. Nothing is ever inferred into this
    # group.
    DISMISS = "dismiss"
    NOT_RELEVANT = "not_relevant"
    LESS_LIKE_THIS = "less_like_this"
    BLOCK_TOPIC = "block_topic"


WEAK_POSITIVE = frozenset({EventType.OPEN, EventType.ABSTRACT_EXPAND, EventType.OUTBOUND_CLICK})
STRONG_POSITIVE = frozenset(
    {EventType.SAVE, EventType.FOLLOW_FROM_ITEM, EventType.MORE_LIKE_THIS}
)
STRONG_NEGATIVE = frozenset(
    {EventType.DISMISS, EventType.NOT_RELEVANT, EventType.LESS_LIKE_THIS, EventType.BLOCK_TOPIC}
)

#: How much one event moves an interest's weight, before decay and saturation.
#: A save is worth several opens because it is intent rather than curiosity; an
#: explicit negative outweighs any single positive because a reader who bothers
#: to say no has given the clearest signal available.
SIGNAL_STRENGTH: Mapping[EventType, float] = {
    EventType.IMPRESSION: 0.0,
    EventType.OPEN: 0.10,
    EventType.ABSTRACT_EXPAND: 0.05,
    EventType.OUTBOUND_CLICK: 0.20,
    EventType.SAVE: 0.50,
    EventType.FOLLOW_FROM_ITEM: 0.60,
    EventType.MORE_LIKE_THIS: 0.50,
    EventType.DISMISS: -0.30,
    EventType.NOT_RELEVANT: -0.70,
    EventType.LESS_LIKE_THIS: -0.50,
    EventType.BLOCK_TOPIC: -1.00,
}


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    """One observed behaviour, with the context needed to interpret it.

    `position` and `interest_key` are recorded at emission because neither can
    be recovered afterwards: the feed is regenerated on every request, so by the
    time an event is analysed the ranking that caused it no longer exists.
    Position is what makes debiasing possible at all.
    """

    event_type: EventType
    paper_id: uuid.UUID
    occurred_at: datetime
    #: Rank of the item in the feed that produced this event, 1-based.
    position: int | None = None
    #: Which interest the feed attributed the item to when it was shown - the
    #: link between an action and the part of the profile it should update.
    interest_key: str | None = None
    #: Opaque grouping for one sitting. Stage D needs it; it costs nothing now.
    session_id: str | None = None
    #: Milliseconds of attention, where it can be measured honestly. Absent is
    #: normal and must never be read as zero.
    dwell_ms: int | None = None

    @property
    def strength(self) -> float:
        return SIGNAL_STRENGTH[self.event_type]

    @property
    def is_explicit_negative(self) -> bool:
        return self.event_type in STRONG_NEGATIVE


@dataclass(frozen=True, slots=True)
class Impression:
    """What a feed showed: one row per rendered item.

    Distinct from `FeedbackEvent` so the exposure log stays complete even when
    the interaction log is lossy. The two join on `(paper_id, session_id)`, and
    a click with no matching impression is a bug worth seeing rather than a row
    to accept quietly.
    """

    paper_id: uuid.UUID
    position: int
    shown_at: datetime
    interest_key: str | None = None
    session_id: str | None = None
    #: The score that put it there, for offline debiasing and drift detection.
    score: float = 0.0


def is_negative_evidence(event: FeedbackEvent) -> bool:
    """Whether this event says the reader did not want the paper.

    Only explicit negatives qualify. An impression with no follow-up is never
    passed here as a negative anywhere in the codebase, and this is the place
    that says why: position and exposure bias make a non-click uninterpretable
    without a model of what the reader actually saw, and no such model exists or
    is planned for Stage B.
    """
    return event.is_explicit_negative


def decayed_weight(strength: float, age_days: float, *, horizon: Horizon) -> float:
    """Exponential decay of one piece of evidence by its horizon's half-life."""
    half_life = SHORT_TERM_HALF_LIFE_DAYS if horizon is Horizon.SHORT else LONG_TERM_HALF_LIFE_DAYS
    return strength * math.pow(0.5, max(0.0, age_days) / half_life)


def _saturate(total: float) -> float:
    """Diminishing returns towards the ceiling, linear near zero.

    `tanh` rather than a clip, so the hundredth save still moves the weight a
    little and the derivative never reaches exactly zero - an interest that
    cannot grow is one that cannot recover after decay either.
    """
    return BEHAVIOURAL_WEIGHT_CEILING * math.tanh(total / BEHAVIOURAL_WEIGHT_CEILING)


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    """What a batch of events did, so the change is inspectable before trusted."""

    events_considered: int = 0
    impressions: int = 0
    explicit_negatives: int = 0
    unattributed: int = 0
    weight_deltas: Mapping[str, float] = field(default_factory=dict)


def apply_feedback(
    profile: InterestProfile,
    events: Iterable[FeedbackEvent],
    *,
    now: datetime,
) -> tuple[InterestProfile, FeedbackSummary]:
    """Move interest weights according to what the reader did.

    Stage B's engine, implemented now against the structures it will use, so the
    intended behaviour is executable and testable rather than a paragraph of
    intent. It updates *weights only*: deriving new interests from behaviour
    needs clustering over embeddings of what was saved, which needs saves, which
    needs users.

    Properties guaranteed here, each covered by a test:

    * **Decayed** - an old event moves less than a recent one.
    * **Graded** - a save moves more than an open.
    * **Saturating** - repetition has diminishing returns.
    * **Reversible** - explicit negatives reduce weight, and an interest can
      recover from near zero when the reader returns to it.
    * **Attributed** - an event with no `interest_key` changes nothing, rather
      than being spread across the profile as a guess.
    """
    deltas: dict[str, float] = {}
    considered = impressions = negatives = unattributed = 0
    by_key = {interest.key: interest for interest in profile.interests}

    for event in events:
        considered += 1
        if event.event_type is EventType.IMPRESSION:
            impressions += 1
            continue
        if event.is_explicit_negative:
            negatives += 1
        if event.interest_key is None or event.interest_key not in by_key:
            # Never spread an unattributed action across the profile: a guess
            # about which interest earned a click is indistinguishable from
            # noise, and it accumulates.
            unattributed += 1
            continue

        interest = by_key[event.interest_key]
        age_days = max(0.0, (now - event.occurred_at) / timedelta(days=1))
        deltas[interest.key] = deltas.get(interest.key, 0.0) + decayed_weight(
            event.strength, age_days, horizon=interest.horizon
        )

    updated = tuple(
        _apply_delta(interest, deltas.get(interest.key, 0.0), now=now)
        for interest in profile.interests
    )
    summary = FeedbackSummary(
        events_considered=considered,
        impressions=impressions,
        explicit_negatives=negatives,
        unattributed=unattributed,
        weight_deltas=deltas,
    )
    return replace(profile, interests=updated), summary


def _apply_delta(interest: Interest, delta: float, *, now: datetime) -> Interest:
    if delta == 0.0:
        return interest
    # A negative on a negative interest strengthens it: "less like this" about
    # something already marked unwanted is agreement, not contradiction.
    signed = -delta if interest.polarity is Polarity.NEGATIVE else delta
    weight = _saturate(interest.weight + signed)
    return replace(interest, weight=min(MAX_WEIGHT, max(0.0, weight)), updated_at=now)


def impression_rate(events: Sequence[FeedbackEvent], of: EventType) -> float:
    """Rate of one event type per impression. The denominator is the point.

    A fraction of what was *shown*, never of what exists - the alternative
    silently rewards a feed for showing less.
    """
    impressions = sum(1 for event in events if event.event_type is EventType.IMPRESSION)
    if impressions == 0:
        return 0.0
    return sum(1 for event in events if event.event_type is of) / impressions
