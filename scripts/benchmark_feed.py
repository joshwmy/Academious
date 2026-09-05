"""Does k interests cost k scans? Measure it rather than assuming.

    python scripts/benchmark_feed.py --synthetic 20000 --database-url postgresql+psycopg://...
    python scripts/benchmark_feed.py --model-key specter2@v1     # a real corpus

The claim `personalise/pgvector.py` rests on is that one statement carrying k
interest vectors reads each row once and computes k distances against it while
it is in memory, so candidate generation costs about one scan however many
interests a reader has. The alternative - `retrieval.semantic.search` once per
interest - costs k scans, and k is a number the *reader* controls.

That is a claim about PostgreSQL's execution rather than about Python, so it is
settled by timing both shapes over the same rows. This script does that and
prints the ratio. It also times the pipeline's stages separately, because "the
feed is slow" is not actionable and "ranking is slow" is.

**Synthetic vectors are random unit vectors.** They say nothing about ranking
quality and are not meant to: the question is how many times the database
touches a row, and a random vector is touched exactly as often as a meaningful
one. Quality is `eval/recommend.py`'s job.

`--synthetic` writes rows. Point it at a throwaway database, never at the live
corpus; without it the script only reads.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial

import numpy as np
from sqlalchemy import Engine, create_engine, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from academious.db.models.embedding import EMBEDDING_DIM, PaperEmbedding
from academious.db.models.paper import Paper
from academious.personalise.candidates import CandidateBudget, gather
from academious.personalise.features import extract
from academious.personalise.feed import FeedConfig, build_feed
from academious.personalise.pgvector import DatabaseFacts, SemanticInterestSource
from academious.personalise.profile import (
    EncodedProfile,
    Interest,
    InterestKind,
    InterestProfile,
)
from academious.personalise.ranking import DeterministicRanker
from academious.personalise.rerank import diversify

MODEL_KEY = "benchmark@v1"
TODAY = date(2026, 9, 5)
REPEATS = 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic",
        type=int,
        default=0,
        help="INSERT this many synthetic papers first. Use a throwaway database.",
    )
    parser.add_argument("--database-url", default=None, help="defaults to the app's own")
    parser.add_argument("--model-key", default=MODEL_KEY)
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args(argv)

    engine = _engine(args.database_url)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with maker() as session:
        if args.synthetic:
            _populate(session, args.synthetic)
            session.commit()

        total = session.scalar(
            select(func.count())
            .select_from(PaperEmbedding)
            .where(PaperEmbedding.model_key == args.model_key)
        )
        if not total:
            print(f"no embeddings under model_key={args.model_key!r}; nothing to measure")
            return 1

        print(f"corpus: {total} embedded papers, model_key={args.model_key}")
        print(f"budget: {args.budget} candidates, {args.repeats} repeats, median reported")
        print()

        _scan_comparison(session, args)
        print()
        _stage_breakdown(session, args)

    engine.dispose()
    return 0


def _scan_comparison(session: Session, args: argparse.Namespace) -> None:
    """The measurement the architecture rests on."""
    print("Candidate generation: one pass over k interests vs k separate passes")
    print()
    print(f"{'k':>3} {'one pass':>12} {'k passes':>12} {'ratio':>8} {'vs k=1':>8}")

    baseline: float | None = None
    for k in (1, 3, 5, 8):
        profile = _profile(k)
        source = SemanticInterestSource(
            session=session, model_key=args.model_key, window_days=None, today=TODAY
        )
        singles = [_profile(1, axis=index) for index in range(k)]

        # Bound through partial rather than captured by a closure: a lambda
        # closing over a loop variable would time whichever profile the loop had
        # reached, which in a benchmark is a wrong number rather than an error.
        single = _median_ms(
            partial(_run_one, session, source, profile, args.budget), args.repeats
        )
        separate = _median_ms(
            partial(_run_each, session, source, singles, args.budget), args.repeats
        )

        if baseline is None:
            baseline = single
        print(
            f"{k:>3} {single:>10.1f}ms {separate:>10.1f}ms "
            f"{separate / single:>8.2f} {single / baseline:>7.2f}x"
        )

    print()
    print("  'vs k=1' is the one-pass cost relative to a single interest.")
    print("  Near-flat means k interests cost about one scan, which is the claim.")


def _stage_breakdown(session: Session, args: argparse.Namespace) -> None:
    """Where a feed request actually spends its time."""
    print("Pipeline stages, 5-interest profile")
    print()
    profile = _profile(5)
    source = SemanticInterestSource(
        session=session, model_key=args.model_key, window_days=None, today=TODAY
    )
    budget = CandidateBudget(total=args.budget)

    generation = _median_ms(lambda: gather([source], profile, budget=budget), args.repeats)

    pool = gather([source], profile, budget=budget)
    ids = pool.paper_ids()
    facts_time = _median_ms(lambda: DatabaseFacts(session, args.model_key)(ids), args.repeats)

    facts = DatabaseFacts(session, args.model_key)(ids)
    candidates = [c for c in pool if c.paper_id in facts]
    extraction = _median_ms(
        lambda: [extract(c, facts[c.paper_id], profile, today=TODAY) for c in candidates],
        args.repeats,
    )

    vectors = [extract(c, facts[c.paper_id], profile, today=TODAY) for c in candidates]
    ranker = DeterministicRanker()
    ranking = _median_ms(lambda: ranker.rank(vectors), args.repeats)

    ranked = ranker.rank(vectors)
    topics = {pid: known.topic_ids for pid, known in facts.items()}
    reranking = _median_ms(lambda: diversify(ranked, limit=20, topics=topics), args.repeats)

    end_to_end = _median_ms(
        lambda: build_feed(
            profile,
            [source],
            DatabaseFacts(session, args.model_key),
            today=TODAY,
            config=FeedConfig(limit=20, budget=budget),
        ),
        args.repeats,
    )

    for label, value in (
        ("candidate generation", generation),
        ("fetch paper facts", facts_time),
        ("feature extraction", extraction),
        ("ranking", ranking),
        ("diversity re-ranking", reranking),
        ("end to end", end_to_end),
    ):
        print(f"  {label:<22} {value:>8.1f} ms")
    print()
    print(f"  pool: {len(pool)} candidates, {len(vectors)} with facts")


def _run_one(
    session: Session, source: SemanticInterestSource, profile: EncodedProfile, budget: int
) -> object:
    return session.execute(source.statement(profile, budget=budget)).all()


def _run_each(
    session: Session,
    source: SemanticInterestSource,
    profiles: Sequence[EncodedProfile],
    budget: int,
) -> object:
    return [session.execute(source.statement(one, budget=budget)).all() for one in profiles]


def _median_ms(work: Callable[[], object], repeats: int) -> float:
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        work()
        timings.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(timings)


def _profile(count: int, *, axis: int | None = None) -> EncodedProfile:
    """`count` orthogonal interests, deterministically."""
    interests = []
    for index in range(count):
        position = axis if axis is not None else index
        vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vector[position % EMBEDDING_DIM] = 1.0
        interests.append(
            Interest(
                key=f"i{index}",
                kind=InterestKind.STATED,
                label=f"Interest {index}",
                text=f"a benchmark research interest number {index}",
                vector=vector,
            )
        )
    return EncodedProfile(profile=InterestProfile(interests=tuple(interests)), model_key=MODEL_KEY)


def _populate(session: Session, count: int) -> None:
    """Random unit vectors: nothing about quality, everything about scans."""
    print(f"creating {count} synthetic papers...", flush=True)
    rng = np.random.default_rng(20260905)
    now = datetime.now(UTC)

    for start in range(0, count, 1000):
        batch = min(1000, count - start)
        papers = []
        embeddings = []
        for index in range(batch):
            paper_id = uuid.uuid4()
            title = f"Benchmark paper {start + index}"
            # feed_date is a generated column - LEAST(published_date,
            # created_at::date) - so it is produced by setting both, not by
            # writing to it. DATA-010 made it generated precisely so it cannot
            # drift from its row, and that applies to benchmark rows too.
            when = TODAY - timedelta(days=(start + index) % 365)
            stamped = datetime.combine(when, datetime.min.time(), tzinfo=UTC)
            papers.append(
                {
                    "id": paper_id,
                    "title": title,
                    "title_norm": title.lower(),
                    "topics": [],
                    "fields": [],
                    "published_date": when,
                    "created_at": stamped,
                    "updated_at": now,
                }
            )
            vector = rng.normal(size=EMBEDDING_DIM).astype(np.float32)
            vector /= np.linalg.norm(vector)
            embeddings.append(
                {
                    "paper_id": paper_id,
                    "model_key": MODEL_KEY,
                    "embedding": vector,
                    "dim": EMBEDDING_DIM,
                    "input_strategy": "benchmark",
                    "input_text_hash": f"{start + index:064d}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        session.execute(insert(Paper), papers)
        session.execute(insert(PaperEmbedding), embeddings)
        session.flush()
    print("done", flush=True)


def _engine(url: str | None) -> Engine:
    if url:
        return create_engine(url, future=True)
    from academious.db.session import get_engine

    return get_engine()


if __name__ == "__main__":
    sys.exit(main())
