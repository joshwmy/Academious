"""The pipeline: a profile in, a ranked and explained feed out.

    profile ─▶ gather(sources) ─▶ hard filters ─▶ extract ─▶ rank ─▶ diversify

Each arrow is a module boundary rather than a call inside one big routine, and
this file is deliberately thin: it wires stages together and owns nothing but
the wiring, the hard filters and the explanation strings. When a collaborative
source or a learned ranker arrives it is a different argument to `build_feed`,
not a change to it.

**The corpus reaches this module through a callable.** `FactsProvider` maps
paper ids to what is known about them, so the pipeline runs against a dictionary
in a test, against PostgreSQL in production and against a fixture corpus in the
benchmark, by the same code path. Nothing here imports SQLAlchemy.

**Hard filters are applied once, before scoring.** A blocked topic removes a
paper rather than lowering it: a reader who blocked something did not ask to see
it ranked politely, and a penalty can always be out-competed by a large enough
bonus elsewhere. Retraction is deliberately *not* a hard filter - a retracted
paper is pushed down and labelled, because a reader following the topic is
exactly who needs to know it was withdrawn.

**Explanations are templated from provenance, never generated.** The interest
that earned a position came from the same `argmax` that produced the score, so a
reason cannot disagree with the ranking. No LLM is involved and none is planned
here: a generated reason costs money per impression to be less faithful than a
formatted one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from academious.personalise.candidates import (
    Candidate,
    CandidateBudget,
    CandidateOrigin,
    CandidatePool,
    CandidateSource,
    gather,
)
from academious.personalise.features import PaperFacts, extract
from academious.personalise.profile import EncodedProfile, InterestKind, Polarity
from academious.personalise.ranking import DeterministicRanker, Ranker, ScoredCandidate
from academious.personalise.rerank import (
    DiversityPolicy,
    diversify,
    interest_coverage,
    intra_list_diversity,
    topic_redundancy,
    vector_redundancy,
)

DEFAULT_FEED_SIZE = 20

#: Everything the pipeline needs to know about the papers it ranks. A callable
#: rather than a repository object, so the stage boundary is a function
#: signature instead of an inheritance hierarchy.
FactsProvider = Callable[[Sequence[uuid.UUID]], Mapping[uuid.UUID, PaperFacts]]

_ORIGIN_TEMPLATES = {
    CandidateOrigin.TOPIC: "in {detail}, which you follow",
    CandidateOrigin.FIELD: "in {detail}",
    CandidateOrigin.AUTHOR: "by {detail}, whom you follow",
    CandidateOrigin.VENUE: "published in {detail}, which you follow",
    CandidateOrigin.COLLABORATIVE: "read by people with interests like yours ({detail})",
    CandidateOrigin.SEQUENTIAL: "follows what you have been reading ({detail})",
}


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One recommendation, with its position, its reason and its arithmetic."""

    rank: int
    paper_id: uuid.UUID
    score: float
    matched_interest: str | None
    reasons: tuple[str, ...]
    scored: ScoredCandidate
    candidate: Candidate

    @property
    def is_exploration(self) -> bool:
        return self.candidate.is_exploration()

    @property
    def is_retracted(self) -> bool:
        return self.scored.features["retracted"] > 0.0


@dataclass(frozen=True, slots=True)
class FeedConfig:
    """Every knob in one place, so an experiment varies data and not code."""

    limit: int = DEFAULT_FEED_SIZE
    budget: CandidateBudget = field(default_factory=CandidateBudget)
    diversity: DiversityPolicy = field(default_factory=DiversityPolicy)


@dataclass(frozen=True, slots=True)
class FeedDiagnostics:
    """What the pipeline did, for evaluation and a debug view.

    Never shown to readers. Present because a feed whose shape nobody can
    explain is a feed nobody can improve: these say whether a source is earning
    its budget and whether diversity is costing relevance.
    """

    candidates_considered: int = 0
    filtered_by_block: int = 0
    missing_facts: int = 0
    ranked: int = 0
    source_contributions: Mapping[str, int] = field(default_factory=dict)
    interest_coverage: Mapping[str, int] = field(default_factory=dict)
    intra_list_diversity: float = 1.0
    exploration_items: int = 0


@dataclass(frozen=True, slots=True)
class FeedResult:
    items: list[FeedItem]
    diagnostics: FeedDiagnostics

    def paper_ids(self) -> list[uuid.UUID]:
        return [item.paper_id for item in self.items]

    def __len__(self) -> int:
        return len(self.items)


def build_feed(
    profile: EncodedProfile,
    sources: Sequence[CandidateSource],
    facts_for: FactsProvider,
    *,
    today: date,
    config: FeedConfig | None = None,
    ranker: Ranker | None = None,
) -> FeedResult:
    """Run the whole pipeline for one reader."""
    settings = config or FeedConfig()
    engine = ranker or DeterministicRanker()

    pool = gather(sources, profile, budget=settings.budget)
    allowed, blocked = _apply_hard_filters(pool, profile, facts_for)

    facts = facts_for([candidate.paper_id for candidate in allowed])
    vectors = []
    missing = 0
    for candidate in allowed:
        known = facts.get(candidate.paper_id)
        if known is None:
            # A candidate a source proposed that the corpus cannot describe.
            # Dropped and counted rather than scored on defaults, which would
            # let a gap in the data look like a mediocre paper.
            missing += 1
            continue
        vectors.append(extract(candidate, known, profile, today=today))

    ranked = engine.rank(vectors)
    by_id = {candidate.paper_id: candidate for candidate in allowed}
    topics = {paper_id: known.topic_ids for paper_id, known in facts.items()}
    embeddings = {
        paper_id: known.vector for paper_id, known in facts.items() if known.vector is not None
    }
    similar = vector_redundancy(embeddings) if embeddings else topic_redundancy(topics)

    selected = diversify(
        ranked,
        limit=settings.limit,
        redundancy=similar,
        topics=topics,
        candidates=by_id,
        policy=settings.diversity,
    )

    items = [
        FeedItem(
            rank=position,
            paper_id=scored.paper_id,
            score=scored.score,
            matched_interest=scored.matched_interest_label,
            reasons=explain(scored, by_id[scored.paper_id], profile),
            scored=scored,
            candidate=by_id[scored.paper_id],
        )
        for position, scored in enumerate(selected, start=1)
    ]

    return FeedResult(
        items=items,
        diagnostics=FeedDiagnostics(
            candidates_considered=len(pool),
            filtered_by_block=blocked,
            missing_facts=missing,
            ranked=len(ranked),
            source_contributions=dict(pool.contributions),
            interest_coverage=interest_coverage(selected),
            intra_list_diversity=intra_list_diversity(selected, similar),
            exploration_items=sum(1 for item in items if item.is_exploration),
        ),
    )


def _apply_hard_filters(
    pool: CandidatePool, profile: EncodedProfile, facts_for: FactsProvider
) -> tuple[list[Candidate], int]:
    """Remove blocked papers. Exclusion is not a low score.

    Also drops anything matching a *negative* interest of an exact-match kind -
    a blocked author or topic expressed as an interest rather than in the block
    set - so the two ways of saying one thing behave identically.

    `require_peer_reviewed` is enforced here for the same reason and not as a
    penalty: it backs a control whose label says *only*, and a penalty can
    always be out-competed by a large enough bonus elsewhere. The soft version
    of the same preference is `preprint_fit`, and both exist because *prefer*
    and *only* are different promises.
    """
    blocked_topics = profile.profile.blocked_topics | profile.profile.values_of(
        InterestKind.TOPIC, Polarity.NEGATIVE
    )
    blocked_authors = profile.profile.blocked_authors | profile.profile.values_of(
        InterestKind.AUTHOR, Polarity.NEGATIVE
    )
    peer_reviewed_only = profile.profile.require_peer_reviewed
    if not blocked_topics and not blocked_authors and not peer_reviewed_only:
        return list(pool), 0

    facts = facts_for(pool.paper_ids())
    allowed: list[Candidate] = []
    removed = 0
    for candidate in pool:
        known = facts.get(candidate.paper_id)
        if known is not None and (
            known.topic_ids & blocked_topics
            or known.author_ids & blocked_authors
            # A paper with no facts at all is left here and dropped downstream
            # as `missing_facts`, so the two diagnostics keep measuring what
            # they say they measure.
            or (peer_reviewed_only and not known.is_peer_reviewed)
        ):
            removed += 1
            continue
        allowed.append(candidate)
    return allowed, removed


#: How the winning interest is phrased, by where that interest came from.
#: *Because you said you follow X* and *because this resembles a paper you
#: chose* are different claims, and a reader deciding whether their profile is
#: right needs to be able to tell them apart. The distinction only survives if
#: provenance is carried this far, which is why `InterestKind` is on the
#: interest rather than inferred from its text.
_INTEREST_TEMPLATES = {
    InterestKind.STATED: "matches your interest in {label}",
    InterestKind.PAPER: "similar to a paper you chose: {label}",
    InterestKind.DERIVED: "based on what you have been reading about {label}",
}
# Only the semantic kinds appear here: the winning interest comes from an argmax
# over `EncodedProfile.positive`, which holds semantic interests alone. A topic
# or field earns its phrasing through `_ORIGIN_TEMPLATES` below, because it
# reaches a candidate as a source rather than as a match.
_DEFAULT_INTEREST_TEMPLATE = "matches your interest in {label}"


def explain(
    scored: ScoredCandidate,
    candidate: Candidate,
    profile: EncodedProfile | None = None,
) -> tuple[str, ...]:
    """Why this paper, for this reader: deterministic, templated, free.

    Ordered by what actually contributed, so the first reason is the true one
    rather than the most flattering. Phrases are short because they sit under a
    title in a feed, not in a paragraph.

    `profile` is optional only so an existing caller with a scored candidate and
    nothing else still works; with it, the winning interest is phrased according
    to where it came from.
    """
    reasons: list[str] = []

    if scored.matched_interest_label:
        kind = _matched_kind(scored, profile)
        template = _INTEREST_TEMPLATES.get(kind, _DEFAULT_INTEREST_TEMPLATE)
        reasons.append(template.format(label=scored.matched_interest_label))

    for origin, template in _ORIGIN_TEMPLATES.items():
        reason = candidate.best_reason(origin)
        if reason is not None and reason.detail:
            reasons.append(template.format(detail=reason.detail))

    if scored.contributions.get("freshness", 0.0) > 0.05:
        reasons.append("published recently")
    if scored.contributions.get("source_agreement", 0.0) > 0.03 and len(candidate.origins) > 1:
        reasons.append(f"found {len(candidate.origins)} different ways")
    if candidate.is_exploration():
        reasons.append("adjacent to your interests")
    if scored.features["retracted"] > 0.0:
        reasons.append("retracted - shown because you follow this area")

    return tuple(dict.fromkeys(reasons))


def _matched_kind(scored: ScoredCandidate, profile: EncodedProfile | None) -> InterestKind | None:
    if profile is None or scored.matched_interest_key is None:
        return None
    for interest in profile.profile.interests:
        if interest.key == scored.matched_interest_key:
            return interest.kind
    return None
