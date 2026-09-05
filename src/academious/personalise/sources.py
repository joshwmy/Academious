"""Candidate sources that need no database.

Two audiences. Tests and the offline benchmark need sources that run over a
dictionary of papers, so the pipeline is exercisable without PostgreSQL and
without a model. And the exploration source is genuinely simplest in memory,
because it works over a retrieved candidate set rather than over the corpus.

The production semantic source lives in `pgvector.py`, where the corpus is.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from academious.personalise.candidates import Candidate, CandidateOrigin, CandidateReason
from academious.personalise.features import PaperFacts
from academious.personalise.profile import EncodedProfile, InterestKind

#: An adjacent paper must be at least this similar to something the reader
#: cares about. Below it, "adjacent" means "unrelated" and the exploration slot
#: is being spent on noise.
ADJACENCY_FLOOR = 0.60

#: ...and no more similar than this, or it is not exploration at all: it is a
#: paper the semantic source would have found anyway, relabelled.
ADJACENCY_CEILING = 0.80


@dataclass(slots=True)
class StaticSource:
    """Proposes a fixed list. For tests about ranking rather than retrieval."""

    candidates: Sequence[Candidate]
    name: str = "static"

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        return list(self.candidates)[:budget]


@dataclass(slots=True)
class InMemorySemanticSource:
    """Exact cosine over a dictionary of papers - the pgvector source's twin.

    Deliberately mirrors what `pgvector.SemanticInterestSource` returns,
    including one reason per matching interest rather than one per paper, so a
    test passing here means something about production. It differs only in where
    the vectors live.
    """

    facts: Mapping[uuid.UUID, PaperFacts]
    name: str = "semantic"
    #: Candidates per interest, before the pool merges them.
    per_interest: int = 100

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        papers = [(pid, f.vector) for pid, f in self.facts.items() if f.vector is not None]
        if not papers or len(profile.positive) == 0:
            return []

        matrix = np.vstack([vector for _, vector in papers])
        # One matrix product covering every interest - the in-memory equivalent
        # of the single-scan requirement the SQL source has to meet.
        similarities = matrix @ profile.positive_vectors.T

        proposed: dict[uuid.UUID, list[CandidateReason]] = {}
        for column, interest in enumerate(profile.positive):
            for row in np.argsort(-similarities[:, column])[: self.per_interest]:
                score = float(similarities[row, column])
                if score <= 0.0:
                    continue
                proposed.setdefault(papers[row][0], []).append(
                    CandidateReason(
                        origin=CandidateOrigin.SEMANTIC_INTEREST,
                        interest_key=interest.key,
                        detail=interest.label,
                        strength=score,
                    )
                )

        candidates = [
            Candidate(paper_id=paper_id, reasons=tuple(reasons))
            for paper_id, reasons in proposed.items()
        ]
        # Best single match first, so a truncated budget keeps the strongest.
        candidates.sort(
            key=lambda c: (-c.strength(CandidateOrigin.SEMANTIC_INTEREST), c.paper_id.bytes)
        )
        return candidates[:budget]


@dataclass(slots=True)
class ExactMatchSource:
    """Papers carrying a followed topic, field, author or venue.

    Cheap, precise, and the only source that works for a reader who has stated
    no free text at all: someone who signed up by ticking three fields gets a
    usable feed because of this.
    """

    facts: Mapping[uuid.UUID, PaperFacts]
    name: str = "exact"

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        wanted = {
            CandidateOrigin.TOPIC: profile.profile.values_of(InterestKind.TOPIC),
            CandidateOrigin.FIELD: profile.profile.values_of(InterestKind.FIELD),
            CandidateOrigin.AUTHOR: profile.profile.values_of(InterestKind.AUTHOR),
            CandidateOrigin.VENUE: profile.profile.values_of(InterestKind.VENUE),
        }
        if not any(wanted.values()):
            return []

        labels = {
            interest.value: interest.label
            for interest in profile.profile.interests
            if interest.value is not None
        }

        found: list[Candidate] = []
        for paper_id, facts in self.facts.items():
            reasons: list[CandidateReason] = []
            for origin, values in wanted.items():
                if not values:
                    continue
                for hit in sorted(_attribute(facts, origin) & values):
                    reasons.append(
                        CandidateReason(origin=origin, detail=labels.get(hit, hit), strength=1.0)
                    )
            if reasons:
                found.append(Candidate(paper_id=paper_id, reasons=tuple(reasons)))

        found.sort(key=lambda c: (-len(c.reasons), c.paper_id.bytes))
        return found[:budget]


def _attribute(facts: PaperFacts, origin: CandidateOrigin) -> frozenset[str]:
    if origin is CandidateOrigin.TOPIC:
        return facts.topic_ids
    if origin is CandidateOrigin.FIELD:
        return facts.field_slugs
    if origin is CandidateOrigin.AUTHOR:
        return facts.author_ids
    if origin is CandidateOrigin.VENUE:
        return frozenset({facts.venue_name}) if facts.venue_name else frozenset()
    return frozenset()


@dataclass(slots=True)
class AdjacentSource:
    """Papers near the edge of what the reader already cares about.

    Exploration with a definition rather than a shrug. A candidate qualifies
    when its best similarity to any positive interest falls inside a band: close
    enough to be intelligible, far enough that the semantic source would not
    have surfaced it anyway. Papers above the ceiling are excluded *because*
    they are too relevant - they are not exploration, and counting them as such
    would spend the exploration budget on things that needed no budget.

    Not a bandit and not pretending to be. `product.md` asks for room for
    serendipity; a policy that learns how much to explore needs an online reward
    stream, which needs users.
    """

    facts: Mapping[uuid.UUID, PaperFacts]
    name: str = "adjacent"
    floor: float = ADJACENCY_FLOOR
    ceiling: float = ADJACENCY_CEILING
    #: Topics already covered by the reader's stated interests. A paper sharing
    #: one is not adjacent, it is more of the same.
    exclude_topics: frozenset[str] = field(default_factory=frozenset)

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        if len(profile.positive) == 0:
            return []
        followed = profile.profile.values_of(InterestKind.TOPIC) | self.exclude_topics

        found: list[tuple[float, Candidate]] = []
        for paper_id, facts in self.facts.items():
            if facts.vector is None or (facts.topic_ids & followed):
                continue
            best = float(np.max(profile.positive_vectors @ facts.vector))
            if not self.floor <= best <= self.ceiling:
                continue
            found.append(
                (
                    best,
                    Candidate(
                        paper_id=paper_id,
                        reasons=(
                            CandidateReason(
                                origin=CandidateOrigin.EXPLORATION,
                                detail="adjacent to your interests",
                                strength=best,
                            ),
                        ),
                    ),
                )
            )

        found.sort(key=lambda pair: (-pair[0], pair[1].paper_id.bytes))
        return [candidate for _, candidate in found[:budget]]
