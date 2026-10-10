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
from sqlalchemy import Select, func, literal, select, union_all
from sqlalchemy.orm import Session

from academious.db.models.embedding import PaperEmbedding
from academious.db.models.paper import Paper
from academious.db.models.support import Venue
from academious.personalise.candidates import Candidate, CandidateOrigin, CandidateReason
from academious.personalise.features import PaperFacts
from academious.personalise.profile import EncodedProfile, InterestKind
from academious.personalise.sources import ADJACENCY_CEILING, ADJACENCY_FLOOR

#: How far back a feed looks by default. Discovery is about what is new, and
#: scanning a decade of corpus to rank twenty recent papers is work whose result
#: is thrown away. Not a hard product rule - an older paper can be exactly right
#: - which is why it is a parameter, and why `freshness` is a soft feature
#: rather than this being the only recency mechanism.
DEFAULT_WINDOW_DAYS = 90


@dataclass(slots=True)
class InterestScan:
    """One pass over the window, shared by the semantic and adjacent sources.

    Both sources rank the same papers by the same number - the best cosine
    across the reader's positive interests - and differ only in which slice of
    that ranking they keep: the top, or the band between the adjacency floor
    and ceiling. Run separately they scan the window twice, and the adjacent
    query is the worse of the two, because its band test repeats the GREATEST
    expression in WHERE as well as ORDER BY: measured on the production corpus
    (548,824 embeddings, 197,878 inside the 90-day window), semantic took about
    0.6 s and adjacent 2.0 s of a 3.0 s preview.

    This computes each distance once, into a MATERIALIZED CTE, and answers both
    questions from it in one statement. The ordering and the tie-break
    (`best DESC, paper_id`) are the ones each source used on its own, so a
    source reading from a scan returns exactly what its own query would have.

    Per request: it caches the result for the profile object it was last asked
    about, which is what one `gather` call passes to every source.
    """

    session: Session
    model_key: str
    #: How many rows each list holds - the most any source can be allocated.
    limit: int
    window_days: int | None = DEFAULT_WINDOW_DAYS
    today: date | None = None
    floor: float = ADJACENCY_FLOOR
    ceiling: float = ADJACENCY_CEILING
    _profile: EncodedProfile | None = None
    _top: list[Any] = field(default_factory=list)
    _band: list[tuple[uuid.UUID, float]] = field(default_factory=list)
    _fetched: int = 0

    def top(self, profile: EncodedProfile, *, budget: int) -> list[Any]:
        """Rows of `(paper_id, s0..sk, best)`, best first, at most `budget`."""
        self._ensure(profile, budget)
        return self._top[:budget]

    def band(self, profile: EncodedProfile, *, budget: int) -> list[tuple[uuid.UUID, float]]:
        """`(paper_id, best)` inside [floor, ceiling], best first, at most `budget`."""
        self._ensure(profile, budget)
        return self._band[:budget]

    def _ensure(self, profile: EncodedProfile, budget: int) -> None:
        if self._profile is profile and budget <= self._fetched:
            return
        fetch = max(budget, self.limit)
        rows = self.session.execute(self.statement(profile, limit=fetch)).all()
        width = len(profile.positive_vectors)
        self._top = [tuple(row[1:]) for row in rows if row[0] == 0]
        self._band = [(row[1], float(row[2 + width])) for row in rows if row[0] == 1]
        self._profile = profile
        self._fetched = fetch

    def statement(self, profile: EncodedProfile, *, limit: int) -> Any:
        """Both lists in one statement. Exposed so a benchmark can EXPLAIN it."""
        similarities = [
            (
                1.0 - PaperEmbedding.embedding.cosine_distance(np.asarray(vector, dtype=np.float32))
            ).label(f"s{index}")
            for index, vector in enumerate(profile.positive_vectors)
        ]
        scored_select = _window(
            select(PaperEmbedding.paper_id, *similarities).where(
                PaperEmbedding.model_key == self.model_key
            ),
            window_days=self.window_days,
            today=self.today,
            peer_reviewed_only=profile.profile.require_peer_reviewed,
        )
        # MATERIALIZED, or PostgreSQL may inline the CTE into both branches and
        # scan twice - the very thing this class exists to stop.
        scored = scored_select.cte("scored").prefix_with("MATERIALIZED")
        columns = [scored.c[f"s{index}"] for index in range(len(similarities))]
        best = func.greatest(*columns) if len(columns) > 1 else columns[0]

        top = (
            select(literal(0).label("list"), scored.c.paper_id, *columns, best.label("best"))
            .order_by(best.desc(), scored.c.paper_id)
            .limit(limit)
        )
        band = (
            select(literal(1).label("list"), scored.c.paper_id, *columns, best.label("best"))
            .where(best >= self.floor, best <= self.ceiling)
            .order_by(best.desc(), scored.c.paper_id)
            .limit(limit)
        )
        return union_all(top, band)


def _window(
    statement: Select[Any],
    *,
    window_days: int | None,
    today: date | None,
    peer_reviewed_only: bool,
) -> Select[Any]:
    """The recency window and peer-review filter an embedding scan applies."""
    if window_days is None and not peer_reviewed_only:
        return statement
    statement = statement.join(Paper, Paper.id == PaperEmbedding.paper_id)
    if window_days is not None:
        cutoff = (today or date.today()) - timedelta(days=window_days)
        statement = statement.where(Paper.feed_date >= cutoff)
    if peer_reviewed_only:
        statement = statement.where(Paper.is_peer_reviewed.is_(True))
    return statement


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
    #: Read from a shared scan instead of querying alone. It must carry the same
    #: window and date as this source; `_feed` builds both in one place.
    scan: InterestScan | None = None

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        if len(profile.positive) == 0 or budget <= 0:
            return []

        rows = (
            self.scan.top(profile, budget=budget)
            if self.scan is not None
            else self.session.execute(self.statement(profile, budget=budget)).all()
        )
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
        peer_reviewed_only = profile.profile.require_peer_reviewed
        cutoff = (
            (self.today or date.today()) - timedelta(days=self.window_days)
            if self.window_days is not None
            else None
        )
        if cutoff is not None or peer_reviewed_only:
            statement = statement.join(Paper, Paper.id == PaperEmbedding.paper_id)
        if cutoff is not None:
            statement = statement.where(Paper.feed_date >= cutoff)
        if peer_reviewed_only:
            # Applied here as well as in `feed._apply_hard_filters`, which is
            # duplication with a purpose: filtering after generation spends the
            # candidate budget on papers about to be discarded, and a reader who
            # asked for peer-reviewed work only would get a thin feed built from
            # whatever survived. The filter downstream is what makes it correct;
            # this is what makes it useful.
            statement = statement.where(Paper.is_peer_reviewed.is_(True))
        return statement


@dataclass(slots=True)
class AdjacentInterestSource:
    """Papers near the edge of what the reader cares about - exploration, in SQL.

    The corpus twin of `sources.AdjacentSource`, and it exists because without
    it the exploration preference is a control connected to nothing: the feed
    caps how many exploration-only items may appear, and with no source
    proposing any the cap is never approached whatever the reader chose.

    Same band and same argument as the in-memory version: above the ceiling a
    paper is not exploration, it is something the main scan would have found
    anyway and relabelled; below the floor it is not adjacent, it is unrelated,
    and a random paper is noise rather than serendipity.

    A second scan, and honestly so. It runs only when the budget allocates
    exploration slots, and `scripts/benchmark_profile_build.py` reports what it
    costs rather than leaving that to be guessed at.
    """

    session: Session
    model_key: str
    name: str = "adjacent"
    window_days: int | None = DEFAULT_WINDOW_DAYS
    today: date | None = None
    floor: float = ADJACENCY_FLOOR
    ceiling: float = ADJACENCY_CEILING
    #: Read the band from a shared scan instead of a second pass of its own.
    scan: InterestScan | None = None

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        if len(profile.positive) == 0 or budget <= 0:
            return []
        if self.scan is not None:
            return [_adjacent(pid, score) for pid, score in self.scan.band(profile, budget=budget)]

        similarities = [
            (1.0 - PaperEmbedding.embedding.cosine_distance(np.asarray(vector, dtype=np.float32)))
            for vector in profile.positive_vectors
        ]
        best = func.greatest(*similarities) if len(similarities) > 1 else similarities[0]

        statement = (
            select(PaperEmbedding.paper_id, best.label("best"))
            .where(
                PaperEmbedding.model_key == self.model_key,
                best >= self.floor,
                best <= self.ceiling,
            )
            .order_by(best.desc(), PaperEmbedding.paper_id)
            .limit(budget)
        )
        if self.window_days is not None or profile.profile.require_peer_reviewed:
            statement = statement.join(Paper, Paper.id == PaperEmbedding.paper_id)
        if self.window_days is not None:
            cutoff = (self.today or date.today()) - timedelta(days=self.window_days)
            statement = statement.where(Paper.feed_date >= cutoff)
        if profile.profile.require_peer_reviewed:
            statement = statement.where(Paper.is_peer_reviewed.is_(True))

        return [_adjacent(pid, score) for pid, score in self.session.execute(statement).all()]


def _adjacent(paper_id: uuid.UUID, score: float) -> Candidate:
    """An exploration candidate, with the reason the feed explains it by."""
    return Candidate(
        paper_id=paper_id,
        reasons=(
            CandidateReason(
                origin=CandidateOrigin.EXPLORATION,
                detail="adjacent to your interests",
                strength=float(score),
            ),
        ),
    )


@dataclass(slots=True)
class ExactFieldSource:
    """Recent papers in a subject field the reader follows.

    The cold-start floor, and the reason it exists in SQL rather than only in
    `sources.ExactMatchSource`: a reader who ticked three broad areas and typed
    nothing has no semantic interest to scan against, and without this their
    preview is empty. `eval/profiles.py` calls that reader rec-06 and the
    architecture claimed to serve them; nothing served them from the corpus
    until this.

    **Fields, not topics.** `paper.fields` is a normalised `text[]` with a GIN
    index (`ix_paper_fields`) covering all four source vocabularies, so an
    overlap test is an index scan. `paper.topics` is JSONB with no index, and a
    containment test over 98,000 rows per request is not a facility, it is an
    outage. Topic interests still score - `topic_affinity` reads them from
    facts - and a negative topic still blocks; they simply do not *generate*.
    """

    session: Session
    name: str = "field"
    window_days: int | None = DEFAULT_WINDOW_DAYS
    today: date | None = None

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        followed = profile.profile.values_of(InterestKind.FIELD)
        if not followed or budget <= 0:
            return []

        labels = {
            interest.value: interest.label
            for interest in profile.profile.interests
            if interest.kind is InterestKind.FIELD and interest.value is not None
        }

        statement = (
            select(Paper.id, Paper.fields)
            .where(Paper.fields.op("&&")(_text_array(sorted(followed))))
            # Newest first. A field is a broad bucket and the reader asked for
            # *what is new* in it; ranking will reorder within what this finds,
            # but it cannot rank what a stale slice never returned.
            .order_by(Paper.feed_date.desc().nullslast(), Paper.id.desc())
            .limit(budget)
        )
        if profile.profile.require_peer_reviewed:
            statement = statement.where(Paper.is_peer_reviewed.is_(True))
        if self.window_days is not None:
            cutoff = (self.today or date.today()) - timedelta(days=self.window_days)
            statement = statement.where(Paper.feed_date >= cutoff)

        candidates: list[Candidate] = []
        for paper_id, fields in self.session.execute(statement).all():
            matched = sorted(followed & frozenset(fields or ()))
            if not matched:
                continue
            candidates.append(
                Candidate(
                    paper_id=paper_id,
                    reasons=tuple(
                        CandidateReason(
                            origin=CandidateOrigin.FIELD,
                            detail=labels.get(slug, slug),
                            strength=1.0,
                        )
                        for slug in matched
                    ),
                )
            )
        return candidates


def _text_array(values: Sequence[str]) -> Any:
    """A `text[]` literal for the overlap operator.

    Cast explicitly, or psycopg sends an untyped array and PostgreSQL cannot
    resolve `&&` against `text[]`. The same three lines as
    `retrieval/filters._text_array`, kept here rather than imported because
    reaching into another layer's private helper is a worse dependency than
    three lines of duplication.
    """
    from sqlalchemy import Text, cast, literal
    from sqlalchemy.dialects.postgresql import ARRAY

    return cast(literal(list(values), ARRAY(Text)), ARRAY(Text))


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
