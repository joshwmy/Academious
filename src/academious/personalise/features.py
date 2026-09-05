"""Named, bounded, documented features - the contract between corpus and ranker.

This module exists to survive its own replacement. Today a hand-weighted sum
consumes these features; when there are impressions to learn from, a trained
ranker consumes *the same* features and nothing about extraction changes. That
only works if a feature is a stable, named, self-describing thing rather than a
term in an expression, which is why `FEATURES` is a registry and not a docstring.

**Raw engine scores never reach a scorer.** `retrieval/types.py` refuses to
rescale cosine, `ts_rank_cd` and RRF onto one number because they do not measure
the same thing, and that refusal is right - for reporting a search result.
Ranking a feed means choosing an order, and an order *is* a committed trade
between "closer to an interest" and "published this morning". The way to keep
both truths is to put every transform in one visible place: each feature below
declares its range, direction, meaning and missing-data behaviour. A number that
has not passed through here is not allowed into a score.

**Missing data is a stated policy, never an accidental zero.** A paper with no
venue is not a paper in a bad venue; an undated record is not a new one. Each
spec carries the value used when its input is absent, and the reason for it.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

from academious.personalise.candidates import Candidate, CandidateOrigin
from academious.personalise.profile import EncodedProfile, Horizon, Interest, InterestKind

#: The cosine band worth spending a [0, 1] feature on. SPECTER2 similarities for
#: plausibly-related papers sit inside roughly this range, so mapping raw cosine
#: onto [0, 1] would spend most of the feature's resolution on distinctions that
#: never occur. A presentation choice about the model's output rather than a
#: claim about the model - and one constant, so it can be argued with.
COSINE_FLOOR = 0.55
COSINE_CEILING = 0.92

#: Freshness decay: `exp(-age / 14)`. A fortnight-old paper scores about a third
#: of one published today, and a quarter-old paper near zero without ever being
#: excluded. From phase-0-report.md section 6.3.
FRESHNESS_DECAY_DAYS = 14.0

#: Venue citedness is capped here before normalising. The job is separating "a
#: real venue" from "no venue at all", not ranking journals against each other.
VENUE_CITEDNESS_CAP = 10.0

#: How many distinct kinds of agreeing source count as full agreement. Three
#: independent reasons is already strong; more is not three times stronger.
AGREEMENT_SATURATION = 3.0

#: Window over which an impression stops suppressing a paper.
SEEN_DECAY_DAYS = 7.0


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One feature, and what a reader of the code needs in order to trust it."""

    name: str
    description: str
    #: +1 if more is better for the reader, -1 if more is worse. A learned
    #: ranker may disagree, which is its right; the deterministic one uses this
    #: to decide whether a weight adds or subtracts, so a sign mistake becomes
    #: a wrong table entry rather than silent nonsense.
    direction: int
    #: Value used when the underlying data is absent, and why that value.
    missing: float
    missing_rationale: str


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "semantic_affinity",
        "Best cosine match to any positive interest, long and short horizons "
        "blended by the reader's recency_of_interest, rescaled onto the band "
        "where SPECTER2 discriminates.",
        direction=1,
        missing=0.0,
        missing_rationale="A paper with no embedding cannot be matched. It scores "
        "as unrelated rather than being excluded, so a gap in the embedding "
        "backlog degrades the feed instead of emptying it.",
    ),
    FeatureSpec(
        "affinity_long",
        "Best match to a long-term interest, before horizon blending.",
        direction=1,
        missing=0.0,
        missing_rationale="As semantic_affinity.",
    ),
    FeatureSpec(
        "affinity_short",
        "Best match to a short-term interest, before horizon blending. Zero "
        "when the reader has declared no current intent, which is the normal "
        "case rather than an error.",
        direction=1,
        missing=0.0,
        missing_rationale="No short-term interests means no short-term signal.",
    ),
    FeatureSpec(
        "interest_emphasis",
        "How strongly the reader weighted the interest this paper matched, "
        "relative to the heaviest interest in their profile. Kept separate from "
        "semantic_affinity on purpose: a reader saying they care more about a "
        "subject is a fact about the reader, and folding it into the cosine "
        "would report a closer match than the model actually found.",
        direction=1,
        missing=1.0,
        missing_rationale="A profile whose interests are all weighted equally "
        "emphasises none of them, so every paper scores full and the feature "
        "cannot reorder anything.",
    ),
    FeatureSpec(
        "negative_affinity",
        "Best cosine match to an explicitly negative interest. Its own feature "
        "rather than a subtraction from semantic_affinity, so a paper close to "
        "both a liked and a disliked region is visibly that rather than an "
        "averaged middling score.",
        direction=-1,
        missing=0.0,
        missing_rationale="No negative interests means no penalty.",
    ),
    FeatureSpec(
        "topic_affinity",
        "Share of the reader's followed topics this paper carries, normalised "
        "by the follow set rather than the paper's topic count, so breadth is "
        "not punished.",
        direction=1,
        missing=0.0,
        missing_rationale="Following no topics means the feature says nothing.",
    ),
    FeatureSpec(
        "field_affinity",
        "Whether the paper sits in a field the reader follows.",
        direction=1,
        missing=0.0,
        missing_rationale="26% of the corpus carries no field at all (DATA-007), "
        "so absence is common and must not read as a mismatch.",
    ),
    FeatureSpec(
        "author_affinity",
        "Whether any author is one the reader follows.",
        direction=1,
        missing=0.0,
        missing_rationale="Unknown authorship is not evidence against a paper.",
    ),
    FeatureSpec(
        "venue_affinity",
        "Whether the venue is one the reader follows.",
        direction=1,
        missing=0.0,
        missing_rationale="A preprint has no venue and must not be penalised for "
        "it here; that judgement belongs to quality_prior.",
    ),
    FeatureSpec(
        "lexical_affinity",
        "Normalised lexical match, when a lexical source proposed this paper. "
        "Rank-derived rather than raw ts_rank_cd, whose magnitude has no fixed "
        "scale and is not comparable between queries.",
        direction=1,
        missing=0.0,
        missing_rationale="No lexical source proposed it, which is not a "
        "statement about the paper's text.",
    ),
    FeatureSpec(
        "freshness",
        "exp(-age/14) on feed_date, never published_date.",
        direction=1,
        missing=0.0,
        missing_rationale="An undated record is not evidence of newness. DATA-009 "
        "and DATA-010 are both what happens when a date the corpus cannot vouch "
        "for is trusted.",
    ),
    FeatureSpec(
        "novelty",
        "How far outside the reader's established territory a paper sits: an "
        "unfamiliar author, an unfollowed topic. Not automatically good - a "
        "dial the ranker weights, because the product asks for some novelty "
        "rather than as much as possible.",
        direction=1,
        missing=0.5,
        missing_rationale="Unknown novelty is neither novel nor familiar; 0.5 "
        "keeps it from swinging the score either way.",
    ),
    FeatureSpec(
        "source_agreement",
        "How many distinct kinds of source proposed this paper, saturating at "
        "three. Cheap ensemble evidence: a paper found by an interest, a topic "
        "and an author is better supported than one found once.",
        direction=1,
        missing=0.0,
        missing_rationale="Cannot occur - a candidate has at least one reason.",
    ),
    FeatureSpec(
        "quality_prior",
        "Deliberately weak and transparent: peer review, a complete abstract, "
        "and whether the venue is cited at all. NOT an impact-factor ranking, "
        "and never raw citation count - citations accrue with age and would "
        "systematically bury the new work this product exists to surface.",
        direction=1,
        missing=0.0,
        missing_rationale="Absent signals score zero individually; the feature "
        "averages three, so one gap costs a third rather than everything.",
    ),
    FeatureSpec(
        "preprint_fit",
        "How well the paper's publication type matches the reader's stated "
        "appetite for preprints. 0.5 when they are neutral.",
        direction=1,
        missing=0.5,
        missing_rationale="Neutral appetite is the default and should not move "
        "the score.",
    ),
    FeatureSpec(
        "seen_fatigue",
        "How recently this reader was already shown this paper, decaying to "
        "zero across a week. Stage B populates it; today it is always zero.",
        direction=-1,
        missing=0.0,
        missing_rationale="Never shown is the default while no impression log "
        "exists.",
    ),
    FeatureSpec(
        "retracted",
        "1.0 if the paper is retracted. Lowers, never hides: a reader following "
        "the topic is exactly who needs to learn it was withdrawn.",
        direction=-1,
        missing=0.0,
        missing_rationale="Unknown retraction status is treated as not retracted, "
        "matching the corpus default.",
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURES)
FEATURE_SPECS: Mapping[str, FeatureSpec] = {spec.name: spec for spec in FEATURES}


@dataclass(frozen=True, slots=True)
class PaperFacts:
    """What is known about one paper, before any of it becomes a feature.

    A plain structure rather than a `Paper`, so the rule is testable without a
    database - and so this list alone says what the ranker is allowed to see.
    """

    paper_id: uuid.UUID
    vector: np.ndarray | None = None
    feed_date: date | None = None
    topic_ids: frozenset[str] = frozenset()
    field_slugs: frozenset[str] = frozenset()
    author_ids: frozenset[str] = frozenset()
    venue_name: str | None = None
    venue_mean_citedness: float | None = None
    is_preprint: bool = False
    is_peer_reviewed: bool = False
    has_abstract: bool = False
    retraction_status: str = "none"
    #: Days since this reader was last shown it. Stage B.
    seen_days_ago: float | None = None


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """Extracted features for one candidate, every value in [0, 1].

    `matched_*` is the explanation, produced by the same `argmax` that produced
    the affinity rather than by a second computation that could disagree.
    """

    paper_id: uuid.UUID
    values: Mapping[str, float]
    matched_interest_key: str | None = None
    matched_interest_label: str | None = None

    def __getitem__(self, name: str) -> float:
        return self.values[name]

    def as_array(self) -> np.ndarray:
        """Features in `FEATURE_NAMES` order - a learned ranker's input."""
        return np.asarray([self.values[name] for name in FEATURE_NAMES], dtype=np.float32)


def extract(
    candidate: Candidate,
    facts: PaperFacts,
    profile: EncodedProfile,
    *,
    today: date,
) -> FeatureVector:
    """Turn one candidate, plus what we know about it, into named features."""
    long_affinity, short_affinity, matched = _affinities(facts.vector, profile)

    has_short_term = any(i.horizon is Horizon.SHORT for i in profile.positive)
    if has_short_term:
        emphasis = profile.preferences.recency_of_interest
        blended = (1.0 - emphasis) * long_affinity + emphasis * short_affinity
    else:
        # A reader with no short-term interests must not have their feed halved
        # by an emphasis dial they never touched.
        blended = long_affinity

    followed_topics = profile.profile.values_of(InterestKind.TOPIC)
    followed_fields = profile.profile.values_of(InterestKind.FIELD)
    followed_authors = profile.profile.values_of(InterestKind.AUTHOR)
    followed_venues = profile.profile.values_of(InterestKind.VENUE)

    values = {
        "semantic_affinity": blended,
        "affinity_long": long_affinity,
        "affinity_short": short_affinity,
        "interest_emphasis": _emphasis(matched, profile),
        "negative_affinity": _negative_affinity(facts.vector, profile),
        "topic_affinity": _share(facts.topic_ids, followed_topics),
        "field_affinity": _hit(facts.field_slugs, followed_fields),
        "author_affinity": _hit(facts.author_ids, followed_authors),
        "venue_affinity": (float(facts.venue_name in followed_venues) if facts.venue_name else 0.0),
        "lexical_affinity": _clamp(candidate.strength(CandidateOrigin.LEXICAL)),
        "freshness": _freshness(facts.feed_date, today),
        "novelty": _novelty(facts, followed_topics, followed_authors),
        "source_agreement": _clamp(len(candidate.origins) / AGREEMENT_SATURATION),
        "quality_prior": _quality_prior(facts),
        "preprint_fit": _preprint_fit(facts, profile),
        "seen_fatigue": _seen_fatigue(facts.seen_days_ago),
        "retracted": float(facts.retraction_status == "retracted"),
    }
    return FeatureVector(
        paper_id=facts.paper_id,
        values=values,
        matched_interest_key=matched.key if matched is not None else None,
        matched_interest_label=matched.label if matched is not None else None,
    )


def _affinities(
    vector: np.ndarray | None, profile: EncodedProfile
) -> tuple[float, float, Interest | None]:
    """Best long- and short-horizon match, and the interest that won overall.

    The weight decides *which* interest wins, not how close the paper looks: a
    reader weighting an interest heavily is asking for more of it, not claiming
    those papers match better than they do. So the argmax runs over weighted
    similarity while the reported affinity is unweighted.
    """
    if vector is None or len(profile.positive) == 0:
        return 0.0, 0.0, None

    similarities = profile.positive_vectors @ np.asarray(vector, dtype=np.float32)
    winner = int(np.argmax(similarities * profile.positive_weights))

    long_best = 0.0
    short_best = 0.0
    for index, interest in enumerate(profile.positive):
        scaled = _rescale(float(similarities[index]))
        if interest.horizon is Horizon.SHORT:
            short_best = max(short_best, scaled)
        else:
            long_best = max(long_best, scaled)
    return long_best, short_best, profile.positive[winner]


def _emphasis(matched: Interest | None, profile: EncodedProfile) -> float:
    """The matched interest's weight, relative to the heaviest in the profile.

    This is what makes a weight mean something. Without it the weight only
    decides which interest wins an argmax, and a reader who says one subject
    matters eight times more than another sees no change in their feed at all -
    which was true of this code until a test asked.
    """
    if matched is None:
        return FEATURE_SPECS["interest_emphasis"].missing
    heaviest = max((i.effective_weight for i in profile.positive), default=0.0)
    if heaviest <= 0.0:
        return FEATURE_SPECS["interest_emphasis"].missing
    return _clamp(matched.effective_weight / heaviest)


def _negative_affinity(vector: np.ndarray | None, profile: EncodedProfile) -> float:
    if vector is None or len(profile.negative) == 0:
        return 0.0
    similarities = profile.negative_vectors @ np.asarray(vector, dtype=np.float32)
    return _rescale(float(np.max(similarities)))


def _share(present: frozenset[str], followed: frozenset[str]) -> float:
    if not followed:
        return 0.0
    return len(present & followed) / len(followed)


def _hit(present: frozenset[str], followed: frozenset[str]) -> float:
    if not followed:
        return 0.0
    return float(bool(present & followed))


def _freshness(feed_date: date | None, today: date) -> float:
    if feed_date is None:
        return FEATURE_SPECS["freshness"].missing
    # feed_date is clamped upstream, so a future date should not arise; treat
    # one as today rather than letting it score above 1.0.
    age = max(0, (today - feed_date).days)
    return math.exp(-age / FRESHNESS_DECAY_DAYS)


def _novelty(
    facts: PaperFacts, followed_topics: frozenset[str], followed_authors: frozenset[str]
) -> float:
    """Unfamiliar author and unfollowed topic, averaged over what is knowable.

    Meaningful only when the reader follows something to be unfamiliar with. A
    profile of pure free-text interests gets the neutral default rather than a
    fabricated 1.0 that would make every paper look novel.
    """
    signals: list[float] = []
    if followed_topics:
        signals.append(0.0 if facts.topic_ids & followed_topics else 1.0)
    if followed_authors:
        signals.append(0.0 if facts.author_ids & followed_authors else 1.0)
    if not signals:
        return FEATURE_SPECS["novelty"].missing
    return sum(signals) / len(signals)


def _quality_prior(facts: PaperFacts) -> float:
    signals = (
        float(facts.is_peer_reviewed),
        float(facts.has_abstract),
        _clamp((facts.venue_mean_citedness or 0.0) / VENUE_CITEDNESS_CAP),
    )
    return sum(signals) / len(signals)


def _preprint_fit(facts: PaperFacts, profile: EncodedProfile) -> float:
    """Map a [0, 2] appetite onto agreement with this paper's publication type."""
    appetite = profile.preferences.preprint_appetite
    if appetite == 1.0:
        return FEATURE_SPECS["preprint_fit"].missing
    leaning = (appetite - 1.0) / 2.0  # -0.5 peer-reviewed .. +0.5 preprint
    return _clamp(0.5 + leaning if facts.is_preprint else 0.5 - leaning)


def _seen_fatigue(seen_days_ago: float | None) -> float:
    if seen_days_ago is None:
        return FEATURE_SPECS["seen_fatigue"].missing
    return _clamp(1.0 - seen_days_ago / SEEN_DECAY_DAYS)


def _rescale(cosine: float) -> float:
    return _clamp((cosine - COSINE_FLOOR) / (COSINE_CEILING - COSINE_FLOOR))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def describe() -> list[str]:
    """The registry as lines, for documentation and a debug endpoint."""
    return [
        f"{spec.name:<18} {'+' if spec.direction > 0 else '-'}  "
        f"missing={spec.missing}  {spec.description}"
        for spec in FEATURES
    ]
