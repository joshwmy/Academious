"""Of these candidates, which deserve attention now.

One interface, one implementation today, and the interface is the point. A
`Ranker` maps feature vectors to scores; `DeterministicRanker` does it with a
weight table because there is no data to learn one from. When impressions with
outcomes exist, a gradient-boosted ranker implements the same protocol over the
same `FeatureVector` and nothing upstream changes - which is the whole reason
`features.py` is a separate stage.

**The weights are a stated prior fitted to nothing.** They come from
phase-0-report.md section 6.3, extended only where this architecture added a
feature that section did not have. They will be wrong. Centralising them makes
being wrong a measurable, changeable fact rather than a diffuse property of the
code, and `Weights` is data so an experiment can vary it without editing this
module. Nothing in the codebase may hard-code a weight.

**Direction comes from the feature registry, not from the sign of a weight.**
Every weight here is positive, and `FeatureSpec.direction` decides whether a
feature adds or subtracts. A negative weight would encode direction twice, and
the two encodings would eventually disagree.

**Scores are diagnostics, not percentages.** A blended score orders a feed; it
does not measure relevance on a scale any reader should see. The product
presents buckets and reasons (section 6.4), and the number stays available for
evaluation and debugging.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from academious.personalise.features import FEATURE_SPECS, FeatureVector

#: Weight per feature. All positive; direction lives in the registry.
#:
#: Section 6.3's table mapped onto this architecture. `semantic_similarity`
#: 0.35 becomes `semantic_affinity`; `topic_overlap` 0.20 splits across topic
#: and field; `author_follow`, `venue_follow`, `freshness` and `quality_prior`
#: carry over unchanged. Features that section did not have - negative
#: affinity, novelty, source agreement, preprint fit - get deliberately small
#: weights, because inventing a large one for an untested signal would be
#: inventing evidence. The exception is `negative_affinity`, weighted heavily
#: on purpose: an explicit "not this" is the strongest statement a reader can
#: make with no behavioural history behind them.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "semantic_affinity": 0.35,
    # Inputs to semantic_affinity. Scoring them again would count one
    # similarity three times.
    "affinity_long": 0.0,
    "affinity_short": 0.0,
    # What makes a profile weight do anything. Without it a weight only picks
    # the argmax, and a reader emphasising one subject sees no change at all.
    "interest_emphasis": 0.12,
    "negative_affinity": 0.30,
    "topic_affinity": 0.15,
    "field_affinity": 0.05,
    "author_affinity": 0.10,
    "venue_affinity": 0.05,
    "lexical_affinity": 0.05,
    "freshness": 0.15,
    "novelty": 0.03,
    "source_agreement": 0.05,
    "quality_prior": 0.05,
    "preprint_fit": 0.04,
    "seen_fatigue": 0.20,
    "retracted": 0.60,
}


@dataclass(frozen=True, slots=True)
class Weights:
    """A weight table, validated against the feature registry.

    Validation matters more than it looks: a feature renamed in `features.py`
    and not here would otherwise drop silently out of every score, and the feed
    would get quietly worse with nothing failing.
    """

    values: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        unknown = set(self.values) - set(FEATURE_SPECS)
        if unknown:
            raise ValueError(f"weights for features that do not exist: {sorted(unknown)}")
        missing = set(FEATURE_SPECS) - set(self.values)
        if missing:
            raise ValueError(f"features with no weight: {sorted(missing)}")
        negative = [name for name, weight in self.values.items() if weight < 0]
        if negative:
            raise ValueError(
                f"negative weights: {sorted(negative)}. Direction belongs to "
                "FeatureSpec.direction; a negative weight would encode it twice."
            )

    def __getitem__(self, name: str) -> float:
        return self.values[name]

    def positive_mass(self) -> float:
        """Total weight of features that can raise a score.

        The denominator that keeps scores comparable across profiles and weight
        tables. Without it, adding a feature changes every score's magnitude and
        no threshold survives.
        """
        return sum(
            weight
            for name, weight in self.values.items()
            if weight > 0 and FEATURE_SPECS[name].direction > 0
        )

    def replace(self, **overrides: float) -> Weights:
        return Weights({**self.values, **overrides})


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """A ranked paper, with the arithmetic that put it there.

    `contributions` is what a developer inspects and what evaluation reads. It
    is deliberately not what a reader is shown.
    """

    paper_id: uuid.UUID
    score: float
    features: FeatureVector
    contributions: Mapping[str, float] = field(default_factory=dict)

    @property
    def matched_interest_label(self) -> str | None:
        return self.features.matched_interest_label

    @property
    def matched_interest_key(self) -> str | None:
        return self.features.matched_interest_key

    def top_contributions(self, limit: int = 3) -> list[tuple[str, float]]:
        """Largest positive contributions first, for a templated reason."""
        ranked = sorted(self.contributions.items(), key=lambda kv: -kv[1])
        return [(name, value) for name, value in ranked[:limit] if value > 0.0]

    def penalties(self) -> list[tuple[str, float]]:
        """What pushed this paper down, largest first."""
        ranked = sorted(self.contributions.items(), key=lambda kv: kv[1])
        return [(name, value) for name, value in ranked if value < 0.0]


@runtime_checkable
class Ranker(Protocol):
    """Score candidates for one reader.

    Takes every candidate at once rather than one at a time, because a learned
    ranker will want to batch and a listwise one needs the whole list. The
    deterministic implementation ignores that freedom; the interface keeps it.
    """

    name: str

    def rank(self, features: Sequence[FeatureVector]) -> list[ScoredCandidate]: ...


@dataclass(frozen=True, slots=True)
class DeterministicRanker:
    """A weighted sum over normalised features. The Stage A baseline.

    Not a placeholder to apologise for: with no interaction data, a transparent
    prior that can be reasoned about and adjusted by hand beats a model trained
    on nothing - and it is what a learned ranker will have to prove itself
    against.
    """

    weights: Weights = field(default_factory=Weights)
    name: str = "deterministic"

    def rank(self, features: Sequence[FeatureVector]) -> list[ScoredCandidate]:
        scored = [self.score(vector) for vector in features]
        # Ties break on paper id, so two runs over one corpus produce one feed.
        # An unstable feed is indistinguishable from a changed one, which makes
        # any measurement of ranking quality unreadable.
        scored.sort(key=lambda hit: (-hit.score, hit.paper_id.bytes))
        return scored

    def score(self, vector: FeatureVector) -> ScoredCandidate:
        contributions = {
            name: FEATURE_SPECS[name].direction * self.weights[name] * value
            for name, value in vector.values.items()
            if self.weights[name] != 0.0
        }
        # Normalise by reachable positive mass so scores mean the same thing
        # across profiles. Clamped at zero because a paper penalties drove
        # negative is simply last; a negative score invites being read as
        # "anti-relevant", which it is not.
        denominator = self.weights.positive_mass() or 1.0
        return ScoredCandidate(
            paper_id=vector.paper_id,
            score=max(0.0, sum(contributions.values()) / denominator),
            features=vector,
            contributions=contributions,
        )
