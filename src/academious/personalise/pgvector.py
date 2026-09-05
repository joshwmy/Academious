"""Candidate generation and paper facts, from PostgreSQL.

**The requirement this module exists to meet: k interests must not cost k
scans.** The naive implementation calls `retrieval.semantic.search` once per
interest, which at 61.9 ms a scan (docs/performance.md) makes a five-interest
profile 310 ms of retrieval before anything is ranked - and the cost grows with
a number the *reader* controls, which is the wrong thing to let scale.

Instead one statement carries every interest vector and computes the best
affinity across them in a single pass:

    SELECT paper_id,
           1 - (embedding <=> $1) AS s0,
           1 - (embedding <=> $2) AS s1,
           ...
           GREATEST(s0, s1, ...) AS best
    FROM paper_embedding
    WHERE model_key = ...
    ORDER BY best DESC
    LIMIT n

Each row is read once and the distance computed k times against it while it is
already in memory. The per-interest columns come back too, so attribution -
*which* interest earned this paper - is read off the same result rather than
recomputed.

**Measured, and less flattering than the design intended.** Over 20,000
synthetic embeddings (`scripts/benchmark_feed.py`):

| k | one pass | k passes | saved |
|---|---|---|---|
| 3 | 38.9 ms | 82.2 ms | 2.1x |
| 5 | 54.3 ms | 150.7 ms | 2.8x |
| 8 | 62.7 ms | 236.1 ms | 3.8x |

So the shape is right - k passes grow linearly, one pass does not - but the
tempting claim that *k interests cost one scan* is false. Reading each row once
is amortised; computing k distances over 768 dimensions against it is real work
that scales with k. The honest statement is that one pass removes the repeated
**I/O**, not the repeated **arithmetic**, and at k=5 that is worth about 2.8x.

`MAX_INTERESTS` exists because of the residual growth, not in spite of it.

**This ordering cannot use an ANN index, and that is already the decision.**
ADR 0007 chose exact search deliberately, and `GREATEST` over k distances is not
an expression HNSW can serve. If candidate generation later needs an index, the
shape that works is k indexed subqueries unioned - k index probes, still not k
scans - and that trade should be made against a measurement rather than ahead of
one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from academious.db.models.embedding import PaperEmbedding
from academious.db.models.paper import Paper
from academious.db.models.support import Venue
from academious.personalise.candidates import Candidate, CandidateOrigin, CandidateReason
from academious.personalise.features import PaperFacts
from academious.personalise.profile import EncodedProfile

#: How far back a feed looks by default. Discovery is about what is new, and
#: scanning a decade of corpus to rank twenty recent papers is work whose result
#: is thrown away. Not a hard product rule - an older paper can be exactly right
#: - which is why it is a parameter, and why `freshness` is a soft feature
#: rather than this being the only recency mechanism.
DEFAULT_WINDOW_DAYS = 90


@dataclass(slots=True)
class SemanticInterestSource:
    """Best-matching papers across every positive interest, in one scan."""

    session: Session
    model_key: str
    name: str = "semantic"
    #: Only consider papers with a feed date inside this window. None scans all.
    window_days: int | None = DEFAULT_WINDOW_DAYS
    #: Evaluated relative to this date, so a benchmark over a fixed corpus is
    #: reproducible instead of depending on when it runs.
    today: date | None = None
    #: Minimum cosine for a paper to be worth proposing at all.
    floor: float = 0.0

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        if len(profile.positive) == 0 or budget <= 0:
            return []

        rows = self.session.execute(self.statement(profile, budget=budget)).all()
        candidates: list[Candidate] = []
        for row in rows:
            similarities = row[1:-1]
            reasons = tuple(
                CandidateReason(
                    origin=CandidateOrigin.SEMANTIC_INTEREST,
                    interest_key=interest.key,
                    detail=interest.label,
                    strength=float(similarity),
                )
                for interest, similarity in zip(profile.positive, similarities, strict=True)
                if similarity is not None and float(similarity) > self.floor
            )
            if reasons:
                candidates.append(Candidate(paper_id=row[0], reasons=reasons))
        return candidates

    def statement(self, profile: EncodedProfile, *, budget: int) -> Select[Any]:
        """The one-pass query. Exposed so a benchmark can EXPLAIN it."""
        similarities = [
            (1.0 - PaperEmbedding.embedding.cosine_distance(np.asarray(vector, dtype=np.float32)))
            for vector in profile.positive_vectors
        ]
        # GREATEST rather than k separate queries: one heap read, k distance
        # computations against the row already in memory.
        best = (func.greatest(*similarities) if len(similarities) > 1 else similarities[0]).label(
            "best"
        )

        statement = (
            select(PaperEmbedding.paper_id, *similarities, best)
            .where(PaperEmbedding.model_key == self.model_key)
            .order_by(best.desc(), PaperEmbedding.paper_id)
            .limit(budget)
        )
        if self.window_days is not None:
            cutoff = (self.today or date.today()) - timedelta(days=self.window_days)
            statement = statement.join(Paper, Paper.id == PaperEmbedding.paper_id).where(
                Paper.feed_date >= cutoff
            )
        return statement


@dataclass(slots=True)
class DatabaseFacts:
    """A `FactsProvider` backed by the corpus, with a per-request cache.

    Cached because `build_feed` asks twice - once for the hard filters, once for
    feature extraction - and the second call is a subset of the first. Two round
    trips for one set of rows is a waste the pipeline should not have to know
    about.
    """

    session: Session
    model_key: str
    _cache: dict[uuid.UUID, PaperFacts] = field(default_factory=dict)

    def __call__(self, paper_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, PaperFacts]:
        wanted = [pid for pid in paper_ids if pid not in self._cache]
        if wanted:
            self._cache.update(self.load(wanted))
        return {pid: self._cache[pid] for pid in paper_ids if pid in self._cache}

    def load(self, paper_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, PaperFacts]:
        rows = self.session.execute(
            select(
                Paper.id,
                Paper.feed_date,
                Paper.topics,
                Paper.fields,
                Paper.is_preprint,
                Paper.is_peer_reviewed,
                Paper.abstract,
                Paper.retraction_status,
                Venue.name,
                Venue.mean_citedness_2y,
                PaperEmbedding.embedding,
            )
            .outerjoin(Venue, Venue.id == Paper.venue_id)
            .outerjoin(
                PaperEmbedding,
                (PaperEmbedding.paper_id == Paper.id)
                & (PaperEmbedding.model_key == self.model_key),
            )
            .where(Paper.id.in_(paper_ids))
        ).all()

        return {
            row[0]: PaperFacts(
                paper_id=row[0],
                vector=np.asarray(row[10], dtype=np.float32) if row[10] is not None else None,
                feed_date=row[1],
                topic_ids=_topic_ids(row[2]),
                field_slugs=frozenset(row[3] or ()),
                # Authors are denormalised onto the paper (ADR 0003) and are not
                # resolved entities, so author affinity stays unpopulated until
                # they are. Empty is honest; a name string would be a fake id.
                author_ids=frozenset(),
                venue_name=row[8],
                venue_mean_citedness=row[9],
                is_preprint=bool(row[4]),
                is_peer_reviewed=bool(row[5]),
                has_abstract=bool(row[6]),
                retraction_status=str(row[7] or "none"),
            )
            for row in rows
        }


def _topic_ids(topics: Sequence[Mapping[str, object]] | None) -> frozenset[str]:
    """Topic identifiers from the JSONB column, ignoring unidentified entries."""
    if not topics:
        return frozenset()
    return frozenset(
        str(topic["id"]) for topic in topics if isinstance(topic, dict) and topic.get("id")
    )
