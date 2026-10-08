"""Stop one interest, or one paper repeated five ways, from eating the feed.

Ranking maximises relevance per item. A feed is a *set*, and the best set is not
the top ten items scored independently: a reader with three interests whose
strongest centroid happens to score highest gets ten papers about one thing and
learns nothing about the other two. Worse, near-duplicates - a preprint and its
published version, two mirrors of one deposit - score well for exactly the same
reason and spend two slots saying one thing.

So diversity is a separate stage after ranking, and it is a **re-ranking**
rather than a filter: nothing is removed, order changes. That distinction keeps
the trade measurable, because the list before and after can be scored against
the same judgments and the cost of diversity read off directly.

**Marginal relevance, not a quota.** Each slot goes to the candidate maximising
`lambda * score - (1 - lambda) * redundancy against what is already chosen`. A
strong paper still wins a slot it deserves when similar work is present; a
marginal one loses to something that says something new. Caps sit on top for the
case MMR handles badly - one interest producing an unbroken run - and they relax
rather than starve the feed when nothing else qualifies.

**Exploration is a ceiling, not a floor.** Candidates that exist *only* because
an exploration source proposed them may occupy up to a share of the feed, and
only if they clear a relevance threshold. Nothing reserves those slots: an
unspent exploration budget means the feed was full of things the reader actually
wanted, which is not a failure. A random paper is noise, and noise is not
serendipity.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from academious.personalise.candidates import Candidate
from academious.personalise.ranking import ScoredCandidate

#: How much of each slot's decision is relevance rather than novelty against
#: what is already chosen. 1.0 disables diversification, which is the honest
#: way to measure what diversification costs.
DEFAULT_RELEVANCE_LAMBDA = 0.75

#: Above this similarity, two papers are treated as saying the same thing.
#: Versions of one paper sit far above it; genuinely related but distinct work
#: sits below.
NEAR_DUPLICATE_SIMILARITY = 0.95

#: Share of the top score a candidate must reach to be eligible for an
#: exploration slot. Relative rather than absolute, because scores are
#: comparable within one feed and not between profiles.
DEFAULT_EXPLORATION_FLOOR = 0.5


#: Similarity between two papers, in [0, 1]. Injected so the policy is testable
#: without embeddings, and so a cheaper measure can replace cosine if pairwise
#: comparison over the candidate set ever becomes the expensive part.
Redundancy = Callable[[uuid.UUID, uuid.UUID], float]


@dataclass(frozen=True, slots=True)
class DiversityPolicy:
    """The trade, as data. Every knob is measurable against the benchmark."""

    relevance_lambda: float = DEFAULT_RELEVANCE_LAMBDA
    #: Most items attributable to any one interest. None disables the cap. A
    #: cap of 3 in a feed of 10 means a three-interest reader sees all three.
    max_per_interest: int | None = 3
    #: Most items sharing any one topic id.
    max_per_topic: int | None = 4
    #: Share of the feed exploration-only candidates may occupy.
    exploration_share: float = 0.15
    #: Relevance floor for exploration, as a fraction of the best score.
    exploration_floor: float = DEFAULT_EXPLORATION_FLOOR
    #: Similarity above which a candidate is refused as a duplicate of
    #: something already chosen, whatever lambda says.
    near_duplicate_similarity: float = NEAR_DUPLICATE_SIMILARITY

    def __post_init__(self) -> None:
        if not 0.0 <= self.relevance_lambda <= 1.0:
            raise ValueError(f"relevance_lambda must be in [0, 1], got {self.relevance_lambda}")
        if not 0.0 <= self.exploration_share <= 1.0:
            raise ValueError(f"exploration_share must be in [0, 1], got {self.exploration_share}")
        for name in ("max_per_interest", "max_per_topic"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 or None, got {value}")


def vector_redundancy(vectors: Mapping[uuid.UUID, np.ndarray]) -> Redundancy:
    """Cosine between stored vectors. Missing either side means unknown.

    Unknown is 0.0 rather than 1.0: declining to diversify against a paper we
    cannot compare is better than suppressing it on a similarity never measured.
    """

    def similarity(left: uuid.UUID, right: uuid.UUID) -> float:
        a = vectors.get(left)
        b = vectors.get(right)
        if a is None or b is None:
            return 0.0
        return max(0.0, min(1.0, float(np.dot(a, b))))

    return similarity


def topic_redundancy(topics: Mapping[uuid.UUID, frozenset[str]]) -> Redundancy:
    """Jaccard overlap of topic sets - the fallback when vectors are absent."""

    def similarity(left: uuid.UUID, right: uuid.UUID) -> float:
        a = topics.get(left, frozenset())
        b = topics.get(right, frozenset())
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    return similarity


@dataclass(slots=True)
class _Selection:
    """Bookkeeping for what has been chosen so far."""

    chosen: list[ScoredCandidate] = field(default_factory=list)
    per_interest: dict[str, int] = field(default_factory=dict)
    per_topic: dict[str, int] = field(default_factory=dict)
    exploration_used: int = 0

    def accept(self, item: ScoredCandidate, topics: frozenset[str], *, exploration: bool) -> None:
        self.chosen.append(item)
        key = item.matched_interest_key
        if key is not None:
            self.per_interest[key] = self.per_interest.get(key, 0) + 1
        for topic in topics:
            self.per_topic[topic] = self.per_topic.get(topic, 0) + 1
        if exploration:
            self.exploration_used += 1


def diversify(
    ranked: Sequence[ScoredCandidate],
    *,
    limit: int,
    redundancy: Redundancy | None = None,
    topics: Mapping[uuid.UUID, frozenset[str]] | None = None,
    candidates: Mapping[uuid.UUID, Candidate] | None = None,
    policy: DiversityPolicy | None = None,
) -> list[ScoredCandidate]:
    """Re-rank for marginal relevance, subject to caps and the exploration cap.

    `ranked` must already be in descending score order - `Ranker.rank` returns
    it that way. Deterministic: every tie in the selection loop breaks on paper
    id, so identical inputs produce an identical feed.
    """
    rules = policy or DiversityPolicy()
    if limit <= 0 or not ranked:
        return []

    topic_map = topics or {}
    candidate_map = candidates or {}
    similar = redundancy or topic_redundancy(topic_map)

    exploration_cap = int(limit * rules.exploration_share)
    floor = ranked[0].score * rules.exploration_floor

    remaining = list(ranked)
    state = _Selection()
    # Running maximum similarity to anything already chosen, per candidate.
    # Recomputing it against the whole chosen set on every slot is O(limit x n
    # x chosen) and measured at 134 ms for 400 candidates; carrying it forward
    # and updating only against the item just picked is O(limit x n).
    redundancies = dict.fromkeys((item.paper_id for item in ranked), 0.0)

    while remaining and len(state.chosen) < limit:
        pick = _next_pick(
            remaining,
            state,
            rules,
            redundancies,
            topic_map,
            candidate_map,
            exploration_cap=exploration_cap,
            floor=floor,
            strict=True,
        )
        if pick is None:
            # Every remaining candidate is blocked by a cap. Relax rather than
            # return a short feed: a cap is a preference about balance, not a
            # claim that these papers are unfit to be seen.
            pick = _next_pick(
                remaining,
                state,
                rules,
                redundancies,
                topic_map,
                candidate_map,
                exploration_cap=exploration_cap,
                floor=floor,
                strict=False,
            )
        if pick is None:
            break
        remaining.remove(pick)
        candidate = candidate_map.get(pick.paper_id)
        state.accept(
            pick,
            topic_map.get(pick.paper_id, frozenset()),
            exploration=bool(candidate and candidate.is_exploration()),
        )
        for item in remaining:
            redundancies[item.paper_id] = max(
                redundancies[item.paper_id], similar(item.paper_id, pick.paper_id)
            )

    return state.chosen


def _next_pick(
    remaining: Sequence[ScoredCandidate],
    state: _Selection,
    rules: DiversityPolicy,
    redundancies: Mapping[uuid.UUID, float],
    topic_map: Mapping[uuid.UUID, frozenset[str]],
    candidate_map: Mapping[uuid.UUID, Candidate],
    *,
    exploration_cap: int,
    floor: float,
    strict: bool,
) -> ScoredCandidate | None:
    """Highest marginal relevance among candidates the rules still allow."""
    best: ScoredCandidate | None = None
    best_value = float("-inf")

    for item in remaining:
        candidate = candidate_map.get(item.paper_id)
        exploring = bool(candidate and candidate.is_exploration())
        if exploring and (state.exploration_used >= exploration_cap or item.score < floor):
            # Capped and floored in both passes: relaxing exploration would let
            # the relaxation quietly become the policy.
            continue

        redundancy = redundancies[item.paper_id]
        if state.chosen and redundancy >= rules.near_duplicate_similarity:
            continue

        if strict and not _within_caps(item, state, rules, topic_map):
            continue

        value = rules.relevance_lambda * item.score - (1.0 - rules.relevance_lambda) * redundancy
        if value > best_value or (
            value == best_value and best is not None and item.paper_id.bytes < best.paper_id.bytes
        ):
            best, best_value = item, value

    return best


def _within_caps(
    item: ScoredCandidate,
    state: _Selection,
    rules: DiversityPolicy,
    topic_map: Mapping[uuid.UUID, frozenset[str]],
) -> bool:
    key = item.matched_interest_key
    if (
        rules.max_per_interest is not None
        and key is not None
        and state.per_interest.get(key, 0) >= rules.max_per_interest
    ):
        return False
    if rules.max_per_topic is not None:
        for topic in topic_map.get(item.paper_id, frozenset()):
            if state.per_topic.get(topic, 0) >= rules.max_per_topic:
                return False
    return True


def interest_coverage(feed: Sequence[ScoredCandidate]) -> dict[str, int]:
    """How many items each interest earned - the diversity metric that matters."""
    counts: dict[str, int] = {}
    for item in feed:
        key = item.matched_interest_key or "(unmatched)"
        counts[key] = counts.get(key, 0) + 1
    return counts


def intra_list_diversity(feed: Sequence[ScoredCandidate], similar: Redundancy) -> float:
    """Mean pairwise dissimilarity: 1.0 maximally varied, 0.0 identical."""
    if len(feed) < 2:
        return 1.0
    pairs = [
        1.0 - similar(a.paper_id, b.paper_id)
        for index, a in enumerate(feed)
        for b in feed[index + 1 :]
    ]
    return sum(pairs) / len(pairs)
