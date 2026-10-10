"""What does building a research profile cost, stage by stage?

    python scripts/benchmark_profile_build.py
    python scripts/benchmark_profile_build.py --backend hashing --repeats 5

`benchmark_feed.py` measures the recommender given a profile. This measures
everything before that: encoding the interests a reader typed, resolving the
papers they picked, assembling the profile, and then the preview the endpoint
actually returns. The split matters because "profile creation is slow" is not
actionable and "encoding five interests took 380 ms" is.

The number that decides whether onboarding is usable is the **end to end**
figure, because a reader watches it. Everything above it says where it went.

Interest counts are 3, 5 and 8 rather than a sweep: three is a plausible
minimum, five is the shape the six benchmark profiles cluster around, and eight
is halfway to `MAX_INTERESTS`. If the curve between them is not roughly linear,
that is itself the finding.

Read-only. It writes nothing, so it can be pointed at the live corpus.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import date
from functools import partial

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from academious.db.models.embedding import PaperEmbedding
from academious.db.models.paper import Paper
from academious.onboarding.builder import BuildResult, ProfileBuilder
from academious.onboarding.corpus import DatabasePapers
from academious.onboarding.draft import ExamplePaper, ProfileDraft, TextInterest
from academious.onboarding.levels import Importance
from academious.personalise.candidates import CandidateBudget, CandidateSource
from academious.personalise.feed import FeedConfig, FeedResult, build_feed
from academious.personalise.pgvector import (
    AdjacentInterestSource,
    DatabaseFacts,
    ExactFieldSource,
    InterestScan,
    SemanticInterestSource,
)
from academious.personalise.ranking import DeterministicRanker, weights_for

REPEATS = 3
INTEREST_COUNTS = (3, 5, 8)

#: Research interests of the length a reader actually types. Not lorem ipsum:
#: tokenisation cost scales with real vocabulary, and a repeated nonsense string
#: would be silently deduplicated before it ever reached the encoder.
INTERESTS = (
    "recommendation systems and personalised ranking for research",
    "information retrieval, search ranking and evaluation methodology",
    "distributed training and serving of large machine learning models",
    "retrieval augmented generation and grounding for language models",
    "computational genomics, variant calling and population sequencing",
    "protein structure prediction and molecular folding simulation",
    "carbon pricing, emissions policy and climate economics",
    "consensus, replication and fault tolerance in distributed systems",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="defaults to the app's own")
    parser.add_argument("--model-key", default=None, help="defaults to the configured profile")
    parser.add_argument(
        "--backend",
        choices=("configured", "hashing"),
        default="configured",
        help="'hashing' skips loading SPECTER2, to time everything except the model",
    )
    parser.add_argument("--limit", type=int, default=20, help="preview size")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args(argv)

    backend, model_key = _backend(args)
    engine = _engine(args.database_url)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with maker() as session:
        embedded = session.scalar(
            select(func.count())
            .select_from(PaperEmbedding)
            .where(PaperEmbedding.model_key == model_key)
        )
        if not embedded:
            print(f"no embeddings under model_key={model_key!r}; nothing to measure")
            return 1

        example_ids = list(
            session.scalars(
                select(Paper.id)
                .join(PaperEmbedding, PaperEmbedding.paper_id == Paper.id)
                .where(PaperEmbedding.model_key == model_key)
                .limit(2)
            )
        )

        print(f"corpus: {embedded} embedded papers, model_key={model_key}")
        print(f"backend: {backend.model_id}, {args.repeats} repeats, median reported")
        print(f"preview: {args.limit} items from {args.budget} candidates")
        print()
        _report(session, backend, model_key, example_ids, args)

    engine.dispose()
    return 0


def _report(
    session: Session,
    backend: object,
    model_key: str,
    example_ids: Sequence[uuid.UUID],
    args: argparse.Namespace,
) -> None:
    print(
        f"{'interests':>10} {'encode':>10} {'papers':>10} {'build':>10} "
        f"{'preview':>10} {'end to end':>12}"
    )

    for count in INTEREST_COUNTS:
        draft = _draft(count, example_ids)
        encode = partial(_encode, backend)
        papers = DatabasePapers(session, model_key)
        builder = ProfileBuilder(encode=encode, papers=papers, model_key=model_key)
        texts = [interest.text for interest in draft.interests]

        # Bound through partial rather than captured by a closure: a lambda
        # closing over `draft` would time whichever draft the loop had reached.
        encode_ms = _median(partial(encode, texts), args.repeats)
        papers_ms = _median(partial(papers, list(example_ids)), args.repeats)
        build_ms = _median(partial(builder.build, draft), args.repeats)

        built = builder.build(draft)
        preview_ms = _median(
            partial(_preview, session, model_key, built, args), args.repeats
        )
        total_ms = _median(
            partial(_build_and_preview, session, model_key, builder, draft, args), args.repeats
        )

        print(
            f"{count:>10} {encode_ms:>8.1f}ms {papers_ms:>8.1f}ms {build_ms:>8.1f}ms "
            f"{preview_ms:>8.1f}ms {total_ms:>10.1f}ms"
        )

    print()
    print("  'build' includes 'encode' and 'papers'; 'end to end' is build plus preview.")
    print("  A reader waits for the last column.")


def _build_and_preview(
    session: Session,
    model_key: str,
    builder: ProfileBuilder,
    draft: ProfileDraft,
    args: argparse.Namespace,
) -> FeedResult:
    return _preview(session, model_key, builder.build(draft), args)


def _preview(
    session: Session, model_key: str, built: BuildResult, args: argparse.Namespace
) -> FeedResult:
    preferences = built.profile.preferences
    # The shared scan, as `/profiles/preview` builds it.
    scan = InterestScan(session=session, model_key=model_key, limit=args.budget)
    sources: list[CandidateSource] = [
        SemanticInterestSource(session=session, model_key=model_key, scan=scan),
        ExactFieldSource(session=session),
        AdjacentInterestSource(session=session, model_key=model_key, scan=scan),
    ]
    return build_feed(
        built.encoded,
        sources,
        DatabaseFacts(session, model_key),
        today=date.today(),
        config=FeedConfig(
            limit=args.limit,
            budget=CandidateBudget(total=args.budget, exploration_share=preferences.exploration),
        ),
        ranker=DeterministicRanker(weights=weights_for(preferences)),
    )


def _draft(count: int, example_ids: Sequence[uuid.UUID]) -> ProfileDraft:
    return ProfileDraft(
        fields=("computer-science",),
        interests=tuple(
            TextInterest(text, Importance.CORE if index < 2 else Importance.INTERESTED)
            for index, text in enumerate(INTERESTS[:count])
        ),
        example_papers=tuple(ExamplePaper(paper_id=pid) for pid in example_ids),
    )


def _encode(backend: object, texts: Sequence[str]) -> list:
    return list(backend.encode_queries(list(texts)).vectors)  # type: ignore[attr-defined]


def _median(work: Callable[[], object], repeats: int) -> float:
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        work()
        timings.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(timings)


def _backend(args: argparse.Namespace) -> tuple[object, str]:
    if args.backend == "hashing":
        from academious.embeddings.hashing import HashingBackend
        from academious.embeddings.registry import HASHING_AUTO

        return HashingBackend(), args.model_key or HASHING_AUTO.key

    from academious.core.config import get_settings
    from academious.workers import embed as embed_worker

    profile = embed_worker.resolve_profile(get_settings().embedding_profile)
    return embed_worker.build(profile), args.model_key or profile.key


def _engine(url: str | None) -> Engine:
    if url:
        return create_engine(url, future=True)
    from academious.db.session import get_engine

    return get_engine()


if __name__ == "__main__":
    sys.exit(main())
