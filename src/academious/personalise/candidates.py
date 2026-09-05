"""Which few hundred papers might plausibly interest this reader.

A different question from *which ten deserve their attention*, and it gets a
different interface for a reason that only shows up later. Generation is
recall-oriented, cheap per item and allowed to be sloppy - it runs against the
whole corpus. Ranking is precision-oriented, expensive per item and allowed to
be slow - it runs against a few hundred. Collapsing them into one scored scan is
what forces a redesign when a collaborative or sequential model arrives, because
that model *is* a candidate source and nothing about ranking should have to
notice it appear.

**Every candidate keeps its provenance, and provenance is a list.** One paper
can arrive from a semantic interest, a followed topic and an author at once, and
that agreement is a signal worth keeping rather than a duplicate worth
discarding. It is also what answers *why am I seeing this* honestly: the reason
is recorded at the moment it applied, not reconstructed afterwards from a score.

**Strengths are source-local and deliberately not comparable.** A cosine from
the semantic source and a `ts_rank_cd` from a lexical one are not on one scale,
and this module never pretends otherwise: it does not sort by strength, blend
strengths, or allocate budget by them. They are carried so `features.py` can
normalise them explicitly, where the transform is visible. Everything here
treats a candidate as present or absent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from academious.personalise.profile import EncodedProfile

#: How many candidates a feed request may consider. Hundreds, not thousands:
#: ranking cost is linear in this, and recall past a few hundred buys very
#: little for a feed that shows ten. Configurable rather than magic - the
#: measurement behind the number is in docs/performance.md.
DEFAULT_BUDGET = 400

#: Share of the budget an exploration source may occupy. Spent only on
#: candidates clearing the relevance floor in `rerank.py`, and unspent
#: otherwise, because a random paper is noise rather than serendipity.
DEFAULT_EXPLORATION_SHARE = 0.15


class CandidateOrigin(StrEnum):
    """What kind of source produced a candidate.

    The last two exist now so Stage C and Stage D can arrive without touching
    this enum's consumers: a feed item explaining itself as "readers with
    interests like yours" has to be representable before the model that
    produces it exists, or the explanation layer gets redesigned as well.
    """

    SEMANTIC_INTEREST = "semantic_interest"
    TOPIC = "topic"
    FIELD = "field"
    AUTHOR = "author"
    VENUE = "venue"
    LEXICAL = "lexical"
    EXPLORATION = "exploration"
    COLLABORATIVE = "collaborative"
    SEQUENTIAL = "sequential"


@dataclass(frozen=True, slots=True)
class CandidateReason:
    """Why one source proposed one paper.

    `strength` is whatever that source measures in - cosine, `ts_rank_cd`, a
    count - and means something only against other candidates from the *same*
    source. Nothing outside `features.py` may compare two strengths.
    """

    origin: CandidateOrigin
    #: The interest that matched, when one did. `Interest.key`, not a label:
    #: labels belong to the reader and can change without changing identity.
    interest_key: str | None = None
    #: Human-readable specifics for an explanation - a topic name, an author.
    detail: str = ""
    strength: float = 0.0

    def describe(self) -> str:
        return self.detail or self.interest_key or str(self.origin)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A paper proposed for ranking, with every reason it was proposed."""

    paper_id: uuid.UUID
    reasons: tuple[CandidateReason, ...] = ()

    @property
    def origins(self) -> frozenset[CandidateOrigin]:
        return frozenset(reason.origin for reason in self.reasons)

    def strength(self, origin: CandidateOrigin) -> float:
        """Best strength recorded by sources of one kind; 0.0 if none did."""
        return max(
            (reason.strength for reason in self.reasons if reason.origin is origin),
            default=0.0,
        )

    def best_reason(self, origin: CandidateOrigin) -> CandidateReason | None:
        matching = [reason for reason in self.reasons if reason.origin is origin]
        return max(matching, key=lambda reason: reason.strength) if matching else None

    def is_exploration(self) -> bool:
        """True only when exploration is the *sole* reason this paper is here.

        A paper an exploration source also happened to propose is not an
        exploration slot: it earned its place through an established interest,
        and charging it to the exploration budget would quietly shrink the
        exploration actually being done towards zero.
        """
        return self.origins == {CandidateOrigin.EXPLORATION}

    def merged_with(self, other: Candidate) -> Candidate:
        if other.paper_id != self.paper_id:
            raise ValueError("cannot merge candidates for different papers")
        return replace(self, reasons=self.reasons + other.reasons)


@runtime_checkable
class CandidateSource(Protocol):
    """One way of proposing papers.

    Deliberately narrow. A source sees the profile and a budget and returns
    papers with reasons; it does not rank, judge quality, or know what other
    sources exist. That is what lets Stage C arrive as forty lines instead of a
    refactor.
    """

    #: Stable identifier, used for budget allocation and diagnostics.
    name: str

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        """Propose at most `budget` candidates. Fewer is fine; more is ignored."""
        ...


@dataclass(frozen=True, slots=True)
class CandidateBudget:
    """How much of the pool each source may fill.

    Sources are asked in order and later ones see what is left, so ordering is a
    priority statement. Exploration is capped rather than reserved: it may spend
    up to its share, and nothing holds that space open for it.
    """

    total: int = DEFAULT_BUDGET
    exploration_share: float = DEFAULT_EXPLORATION_SHARE
    #: Per-source overrides by `CandidateSource.name`. Absent means "an even
    #: split of what remains" - a starting point, not a claim that sources are
    #: equally valuable.
    per_source: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise ValueError(f"candidate budget must be positive, got {self.total}")
        if not 0.0 <= self.exploration_share <= 1.0:
            raise ValueError(f"exploration_share must be in [0, 1], got {self.exploration_share}")

    @property
    def exploration_slots(self) -> int:
        return int(self.total * self.exploration_share)

    def allocate(self, source: CandidateSource, *, remaining_sources: int, taken: int) -> int:
        """Budget for one source, given what has already been used."""
        left = max(0, self.total - taken)
        override = self.per_source.get(source.name)
        if override is not None:
            return min(override, left)
        return left if remaining_sources <= 1 else max(1, left // remaining_sources)


@dataclass(slots=True)
class CandidatePool:
    """Candidates from every source, deduplicated with their reasons unioned.

    Mutable on purpose: it is built by appending, and copying the pool once per
    source would be the expensive part of a stage whose job is to be cheap.
    """

    _items: dict[uuid.UUID, Candidate] = field(default_factory=dict)
    #: How many candidates each source contributed before deduplication - the
    #: diagnostic that says whether a source is pulling its weight.
    contributions: dict[str, int] = field(default_factory=dict)

    def add(self, candidate: Candidate, *, source_name: str = "") -> None:
        existing = self._items.get(candidate.paper_id)
        self._items[candidate.paper_id] = (
            existing.merged_with(candidate) if existing is not None else candidate
        )
        if source_name:
            self.contributions[source_name] = self.contributions.get(source_name, 0) + 1

    def extend(self, candidates: Iterable[Candidate], *, source_name: str = "") -> int:
        added = 0
        for candidate in candidates:
            self.add(candidate, source_name=source_name)
            added += 1
        return added

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Candidate]:
        return iter(self._items.values())

    def __contains__(self, paper_id: object) -> bool:
        return paper_id in self._items

    def get(self, paper_id: uuid.UUID) -> Candidate | None:
        return self._items.get(paper_id)

    def paper_ids(self) -> list[uuid.UUID]:
        return list(self._items)

    def agreement(self) -> dict[uuid.UUID, int]:
        """How many distinct kinds of source proposed each paper."""
        return {paper_id: len(c.origins) for paper_id, c in self._items.items()}


def gather(
    sources: Sequence[CandidateSource],
    profile: EncodedProfile,
    *,
    budget: CandidateBudget | None = None,
) -> CandidatePool:
    """Run every source under one budget and merge what they propose.

    Sources run in the order given, and one that proposes a paper an earlier
    source already found spends budget the pool did not gain by. Accepted
    deliberately: avoiding it means letting sources see each other's output, and
    a source that depends on what ran before it cannot be tested, reordered or
    removed on its own.
    """
    plan = budget or CandidateBudget()
    pool = CandidatePool()
    for index, source in enumerate(sources):
        allocation = plan.allocate(source, remaining_sources=len(sources) - index, taken=len(pool))
        if allocation <= 0:
            continue
        produced = list(source.generate(profile, budget=allocation))[:allocation]
        pool.extend(produced, source_name=source.name)
    return pool
