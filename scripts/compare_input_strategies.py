"""Does the abstract change what retrieval returns?

Embeds the same corpus twice - once from `title[SEP]abstract` and once from the
title alone - and compares the two rankings query by query.

    python scripts/compare_input_strategies.py --corpus 1200

**This measures difference, not quality.** With no relevance judgments, the only
honest question is *how much does the ranking move?*, and that is what is
reported. A large divergence means the abstract is doing real work and the two
strategies must be judged separately before one is chosen; a small divergence
means the cheaper input would do. Neither outcome says which ranking is better,
and this script does not pretend otherwise.

Both vector sets live under different model_keys at the same time, so this is a
second run against the same database rather than a rebuild.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import func, select  # noqa: E402

from academious.db.models.embedding import PaperEmbedding  # noqa: E402
from academious.db.models.paper import Paper  # noqa: E402
from academious.db.session import session_scope  # noqa: E402
from academious.embeddings import service as embedding_service  # noqa: E402
from academious.embeddings.registry import EmbeddingProfile  # noqa: E402
from academious.embeddings.text import InputMode  # noqa: E402
from academious.eval.queries import ALL_QUERIES  # noqa: E402
from academious.retrieval import semantic  # noqa: E402

OUTPUT = ROOT / "docs" / "phase-2-input-strategy.json"

AUTO = EmbeddingProfile(
    key="specter2-proximity@v1",
    backend_name="specter2",
    input_mode=InputMode.AUTO,
    description="title[SEP]abstract, title-only fallback",
)
TITLE_ONLY = EmbeddingProfile(
    key="specter2-title-only@v1",
    backend_name="specter2",
    input_mode=InputMode.TITLE_ONLY,
    description="titles only, ablation",
)


def populate(profile: EmbeddingProfile, backend: Any, corpus: int) -> int:
    embedded = 0
    started = time.perf_counter()
    while embedded < corpus:
        with session_scope() as session:
            wanted = min(64, corpus - embedded)
            batch = embedding_service.select_pending_paper_ids(
                session, profile.key, limit=wanted
            )
            if not batch:
                break
            stats = embedding_service.embed_papers(
                session, batch, profile=profile, backend=backend
            )
        embedded += stats.embedded
        print(f"  {profile.key}: {embedded} embedded", end="\r")
    elapsed = time.perf_counter() - started
    print(f"  {profile.key}: {embedded} embedded in {elapsed:.0f}s" + " " * 16)
    return embedded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=int, default=1200)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--show", type=int, default=3)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    from academious.embeddings.specter2 import Specter2Backend

    backend = Specter2Backend(batch_size=16)

    print("=" * 78)
    print("Embedding the corpus under both input strategies")
    print("=" * 78)
    populate(AUTO, backend, args.corpus)
    populate(TITLE_ONLY, backend, args.corpus)

    with session_scope() as session:
        counts = dict(
            session.execute(
                select(PaperEmbedding.model_key, func.count()).group_by(PaperEmbedding.model_key)
            ).all()
        )
        papers = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        with_abstract = session.execute(
            select(func.count()).select_from(Paper).where(Paper.abstract.is_not(None))
        ).scalar_one()
        strategies = dict(
            session.execute(
                select(PaperEmbedding.input_strategy, func.count())
                .where(PaperEmbedding.model_key == AUTO.key)
                .group_by(PaperEmbedding.input_strategy)
            ).all()
        )

    rows: list[dict[str, Any]] = []
    print()
    print("=" * 78)
    print(f"Ranking divergence at k={args.k}")
    print("=" * 78)

    with session_scope() as session:
        for query in ALL_QUERIES:
            auto = semantic.search_text(
                session, query.text, backend=backend, model_key=AUTO.key, limit=args.k
            )
            titles = semantic.search_text(
                session, query.text, backend=backend, model_key=TITLE_ONLY.key, limit=args.k
            )
            auto_ids = auto.paper_ids()
            title_ids = titles.paper_ids()
            overlap = len(set(auto_ids) & set(title_ids)) / max(1, len(auto_ids))
            same_top1 = bool(auto_ids and title_ids and auto_ids[0] == title_ids[0])

            by_id = {hit.paper_id: hit.title for hit in [*auto.hits, *titles.hits]}
            rows.append(
                {
                    "id": query.id,
                    "text": query.text,
                    "overlap_at_k": round(overlap, 4),
                    "top1_same": same_top1,
                    "only_in_auto": [by_id[i] for i in auto_ids if i not in set(title_ids)][
                        : args.show
                    ],
                    "only_in_title_only": [by_id[i] for i in title_ids if i not in set(auto_ids)][
                        : args.show
                    ],
                }
            )
            marker = "same" if same_top1 else "DIFFERS"
            print(f"  [{query.id}] overlap {overlap:5.0%}  top-1 {marker}   {query.text}")
            for title in rows[-1]["only_in_auto"][:1]:
                print(f"        only with abstract: {title[:60]}")
            for title in rows[-1]["only_in_title_only"][:1]:
                print(f"        only title-only   : {title[:60]}")

    overlaps = [r["overlap_at_k"] for r in rows]
    summary = {
        "mean_overlap_at_k": round(sum(overlaps) / len(overlaps), 4),
        "min_overlap_at_k": round(min(overlaps), 4),
        "queries_with_same_top1": sum(1 for r in rows if r["top1_same"]),
        "queries": len(rows),
    }

    print()
    print("=" * 78)
    for key, value in summary.items():
        print(f"  {key:<32} {value}")
    print("=" * 78)
    print("This is divergence, not quality. Judging which ranking is better needs")
    print("relevance labels; see docs/evaluation.md.")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "k": args.k,
        "profiles": {
            AUTO.key: {"description": AUTO.description, "vectors": counts.get(AUTO.key, 0)},
            TITLE_ONLY.key: {
                "description": TITLE_ONLY.description,
                "vectors": counts.get(TITLE_ONLY.key, 0),
            },
        },
        "corpus": {
            "papers": papers,
            "papers_with_abstract": with_abstract,
            "auto_strategy_breakdown": strategies,
        },
        "queries": rows,
        "summary": summary,
        "caveat": (
            "Measures how much the ranking moves, not which ranking is better. "
            "No relevance judgments were used."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWritten to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
