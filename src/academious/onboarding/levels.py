"""The one place a human choice becomes a recommender number.

A reader says *core interest*. The ranker needs `weight=1.0`. Somebody has to
perform that translation, and the only question is whether it happens once,
somewhere findable, or five times in five files that drift apart.

**Nothing outside this module may write a profile number.** Not the API layer,
not the draft, not the frontend. `draft.py` carries the reader's words;
`builder.py` asks here what they mean. The consequence is that changing what
*core* is worth is a one-line change with a test on it, rather than a search for
every place 1.0 was typed.

**The numbers are a prior, not a measurement.** Nobody has judged a feed built
from a core interest against one built from an occasional interest, so these are
chosen for the property that can be checked without judgment - that the ordering
is strict and the gaps are large enough to move a ranking. `interest_emphasis`
in `features.py` is what makes them matter at all: before that feature existed,
a weight only decided which interest won an argmax and a reader emphasising one
subject saw no change in their feed.

**A level a reader can choose must be one the pipeline can honour.** That rule
removed a control from this file rather than adding one: there is no
"peer-reviewed only" without a hard filter to enforce it, so `PEER_REVIEWED_ONLY`
maps to both an appetite *and* `InterestProfile.require_peer_reviewed`, and
`feed.py` refuses the papers. A level that only tilted a weight while promising
"only" would be a lie in the interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from academious.personalise.profile import Preferences

# --- how much a reader wants something ---------------------------------------


class Importance(StrEnum):
    """How much a positive interest matters, in the reader's own terms."""

    CORE = "core"
    INTERESTED = "interested"
    OCCASIONAL = "occasional"


#: Importance to `Interest.weight`. Strictly ordered, with gaps wide enough that
#: `interest_emphasis` (weight 0.12 in the ranker) can actually reorder a feed:
#: core against occasional is a 0.6 difference in a [0, 1] feature, which is
#: worth about 0.07 of score - larger than the freshness gap between a paper
#: published today and one published four days ago.
IMPORTANCE_WEIGHT: Mapping[Importance, float] = {
    Importance.CORE: 1.0,
    Importance.INTERESTED: 0.7,
    Importance.OCCASIONAL: 0.4,
}

#: Ordered weakest-first, so a refinement can step a level up or down without
#: arithmetic on the labels.
IMPORTANCE_ORDER: tuple[Importance, ...] = (
    Importance.OCCASIONAL,
    Importance.INTERESTED,
    Importance.CORE,
)


def step_importance(level: Importance, delta: int) -> Importance:
    """Move one level up or down, saturating at the ends.

    Saturating rather than wrapping: a reader who says *more of this* about an
    interest already marked core has not asked for it to become occasional.
    """
    index = IMPORTANCE_ORDER.index(level)
    return IMPORTANCE_ORDER[max(0, min(len(IMPORTANCE_ORDER) - 1, index + delta))]


class Avoidance(StrEnum):
    """How strongly a reader does not want something."""

    LESS = "less"
    AVOID = "avoid"


#: Avoidance to `Interest.weight` on a negative interest. Both are meaningful
#: because `negative_affinity` carries a heavy ranker weight (0.30): an explicit
#: "not this" is the strongest statement a reader with no history can make, and
#: halving it has to mean something.
AVOIDANCE_WEIGHT: Mapping[Avoidance, float] = {
    Avoidance.LESS: 0.6,
    Avoidance.AVOID: 1.0,
}

# --- how a reader wants discovery done ---------------------------------------


class FreshnessLevel(StrEnum):
    """How much the feed should prefer new work over well-matched work."""

    NEWEST_FIRST = "newest_first"
    BALANCED = "balanced"
    RELEVANCE_FIRST = "relevance_first"


#: Freshness to `Preferences.freshness_appetite`, which `ranking.weights_for`
#: turns into the `freshness` weight. Two hops rather than one because the
#: appetite has to survive serialisation into the canonical profile, and a
#: weight table does not: a stored weight would silently pin a reader to
#: whatever the ranker's constants were on the day they signed up.
FRESHNESS_APPETITE: Mapping[FreshnessLevel, float] = {
    FreshnessLevel.NEWEST_FIRST: 1.0,
    FreshnessLevel.BALANCED: 0.5,
    FreshnessLevel.RELEVANCE_FIRST: 0.0,
}


class ExplorationLevel(StrEnum):
    """How much of the feed may go to work outside established interests."""

    FOCUSED = "focused"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


#: Exploration to `Preferences.exploration`, which is also the share of the feed
#: `DiversityPolicy` lets exploration-only candidates occupy. BALANCED is the
#: `Preferences` default, so a reader who skips this screen gets exactly the
#: behaviour the benchmark was measured against.
EXPLORATION_SHARE: Mapping[ExplorationLevel, float] = {
    ExplorationLevel.FOCUSED: 0.05,
    ExplorationLevel.BALANCED: 0.15,
    ExplorationLevel.ADVENTUROUS: 0.30,
}


class PublicationStage(StrEnum):
    """Which publication stages a reader will accept."""

    INCLUDE_PREPRINTS = "include_preprints"
    PREFER_PEER_REVIEWED = "prefer_peer_reviewed"
    PEER_REVIEWED_ONLY = "peer_reviewed_only"


#: Publication stage to `Preferences.preprint_appetite`, where 1.0 is neutral,
#: 0.0 is "peer-reviewed please" and 2.0 would be "preprints please". Nothing
#: maps above 1.0: no reader has asked to be shown *fewer* peer-reviewed papers,
#: and offering the control would invent a preference to justify the range.
PREPRINT_APPETITE: Mapping[PublicationStage, float] = {
    PublicationStage.INCLUDE_PREPRINTS: 1.0,
    PublicationStage.PREFER_PEER_REVIEWED: 0.4,
    PublicationStage.PEER_REVIEWED_ONLY: 0.0,
}


def requires_peer_review(stage: PublicationStage) -> bool:
    """Whether this stage is a hard filter rather than a preference.

    Only `PEER_REVIEWED_ONLY`. The word *only* is a promise, and `feed.py`
    enforces it by removing preprints from the candidate set rather than
    scoring them lower - a penalty can always be out-competed by a large
    enough bonus somewhere else.
    """
    return stage is PublicationStage.PEER_REVIEWED_ONLY


# --- the whole set of discovery choices --------------------------------------


def preferences_for(
    *,
    freshness: FreshnessLevel,
    exploration: ExplorationLevel,
    publication: PublicationStage,
) -> Preferences:
    """The three human choices as one `Preferences`.

    `recency_of_interest` is deliberately left at its default. It weighs
    short-term interests against long-term ones, and onboarding produces no
    short-term interests at all (see `builder.py`), so exposing a control for it
    would be a dial connected to nothing until the reader refines their preview.
    """
    return Preferences(
        exploration=EXPLORATION_SHARE[exploration],
        preprint_appetite=PREPRINT_APPETITE[publication],
        freshness_appetite=FRESHNESS_APPETITE[freshness],
    )


# --- reading the numbers back ------------------------------------------------
#
# A summary has to describe a built profile rather than the draft behind it -
# otherwise it describes what the reader typed instead of what the recommender
# received, and the two could differ without anyone noticing. So every mapping
# above needs an inverse. Nearest-value rather than exact-match, because a
# profile that arrives from a client, or from a future stage that moved a weight
# by a fraction, still has to be describable in words.


def _nearest[T](value: float, table: Mapping[T, float]) -> T:
    return min(table, key=lambda level: abs(table[level] - value))


def importance_for_weight(weight: float) -> Importance:
    return _nearest(weight, IMPORTANCE_WEIGHT)


def avoidance_for_weight(weight: float) -> Avoidance:
    return _nearest(weight, AVOIDANCE_WEIGHT)


def freshness_for(appetite: float) -> FreshnessLevel:
    return _nearest(appetite, FRESHNESS_APPETITE)


def exploration_for(share: float) -> ExplorationLevel:
    return _nearest(share, EXPLORATION_SHARE)


def publication_for(appetite: float, *, peer_reviewed_only: bool) -> PublicationStage:
    """The stage a profile expresses. The hard filter wins where they disagree.

    A profile can carry an appetite of 0.0 without the filter - that is
    *prefer*, not *only* - so the flag is checked first rather than inferred
    from the number.
    """
    if peer_reviewed_only:
        return PublicationStage.PEER_REVIEWED_ONLY
    if appetite >= 0.7:
        return PublicationStage.INCLUDE_PREPRINTS
    return PublicationStage.PREFER_PEER_REVIEWED


#: What each level is called on a summary screen. Kept beside the numbers so a
#: renamed level cannot keep its old wording anywhere in the product.
IMPORTANCE_LABEL: Mapping[Importance, str] = {
    Importance.CORE: "Core interest",
    Importance.INTERESTED: "Interested",
    Importance.OCCASIONAL: "Occasionally interested",
}

AVOIDANCE_LABEL: Mapping[Avoidance, str] = {
    Avoidance.LESS: "Less of this",
    Avoidance.AVOID: "Not interested",
}

FRESHNESS_LABEL: Mapping[FreshnessLevel, str] = {
    FreshnessLevel.NEWEST_FIRST: "Mostly newest research",
    FreshnessLevel.BALANCED: "Balanced",
    FreshnessLevel.RELEVANCE_FIRST: "Best match first",
}

EXPLORATION_LABEL: Mapping[ExplorationLevel, str] = {
    ExplorationLevel.FOCUSED: "Stay close to my interests",
    ExplorationLevel.BALANCED: "Balanced discovery",
    ExplorationLevel.ADVENTUROUS: "Show me adjacent topics",
}

PUBLICATION_LABEL: Mapping[PublicationStage, str] = {
    PublicationStage.INCLUDE_PREPRINTS: "Preprints included",
    PublicationStage.PREFER_PEER_REVIEWED: "Peer-reviewed preferred",
    PublicationStage.PEER_REVIEWED_ONLY: "Peer-reviewed only",
}


class Provenance(StrEnum):
    """Where an interest came from, recorded on every one this package builds.

    Explanations differ by provenance - *because you said you follow X* is a
    different sentence from *because it resembles a paper you chose* - and the
    difference is only recoverable if it is written down when the interest is
    created. `BEHAVIOURAL_INFERENCE` is Stage B's and is never produced here; it
    is listed so the vocabulary is complete in one place rather than growing a
    second enum later.
    """

    EXPLICIT_TEXT = "explicit_text"
    SELECTED_TOPIC = "selected_topic"
    SELECTED_FIELD = "selected_field"
    EXAMPLE_PAPER = "example_paper"
    PROFILE_REFINEMENT = "profile_refinement"
    BEHAVIOURAL_INFERENCE = "behavioural_inference"
