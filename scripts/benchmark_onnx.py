"""RETR-005: is ONNX int8 faster, and is it still the same retrieval?

Speed alone does not settle this. Quantisation changes the vectors, so the
question is not "how much faster" but "how much faster, at what cost to the
ranking" - and a backfill run at a precision that reorders results is a backfill
that has to be done again.

Three things are measured, against the same texts, in one process:

1. **Throughput.** Papers per second per backend. The number RETR-005 exists for.
2. **Fidelity.** Cosine similarity between each backend's vectors and PyTorch
   fp32. ONNX fp32 should be ~1.0 - anything else means the export is wrong
   rather than merely quantised. int8 is where the real error lives.
3. **Retrieval agreement.** For each of the twelve judged benchmark queries,
   rank the sampled corpus under each backend and compare the top ten against
   the PyTorch fp32 ordering. This is the measure that matters: a mean cosine of
   0.999 is reassuring but does not say whether results three and four swapped
   places, and only the ranking is user-visible.

Judgments are deliberately not used. This asks whether int8 retrieval *agrees
with fp32 retrieval*, which needs no labels; whether that ranking is any good is
what the Phase 2 benchmark and `data/eval/judgments.jsonl` already answer.

    python scripts/benchmark_onnx.py --limit 200
    python scripts/benchmark_onnx.py --limit 500 --json data/onnx-benchmark.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from academious.db.models.paper import Paper  # noqa: E402
from academious.db.session import session_scope  # noqa: E402
from academious.embeddings.text import InputMode, build_embedding_input  # noqa: E402
from academious.eval.queries import ALL_QUERIES  # noqa: E402

#: How deep to compare rankings. Ten is what a reader sees on one screen, and
#: what NDCG@10 in the Phase 2 benchmark already reports.
TOP_K = 10


@dataclass
class Report:
    machine: dict[str, Any] = field(default_factory=dict)
    corpus: dict[str, Any] = field(default_factory=dict)
    throughput: list[dict[str, Any]] = field(default_factory=list)
    fidelity: list[dict[str, Any]] = field(default_factory=list)
    retrieval_agreement: list[dict[str, Any]] = field(default_factory=list)


def banner(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def peak_rss_mb() -> float:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 1e6, 1)
    except Exception:
        return 0.0


def load_texts(limit: int) -> tuple[list[str], dict[str, Any]]:
    """Real paper texts, built exactly as production would build them."""
    with session_scope() as session:
        rows = session.execute(
            select(Paper.title, Paper.abstract).order_by(Paper.created_at.desc()).limit(limit)
        ).all()

    built = [build_embedding_input(row.title, row.abstract, mode=InputMode.AUTO) for row in rows]
    texts = [item.text for item in built if item.text]
    stats = {
        "sampled": len(texts),
        "mean_characters": round(statistics.mean(len(t) for t in texts), 1) if texts else 0,
    }
    return texts, stats


def make_backend(name: str, batch_size: int, threads: int | None) -> Any:
    if name == "torch-fp32":
        from academious.embeddings.specter2 import Specter2Backend

        return Specter2Backend(batch_size=batch_size, num_threads=threads)

    precision = name.removeprefix("onnx-")
    from academious.embeddings.onnx_specter2 import OnnxSpecter2Backend

    return OnnxSpecter2Backend(
        precision=precision,
        model_dir=REPO_ROOT / "data" / "onnx",
        batch_size=batch_size,
        num_threads=threads,
    )


def measure(name: str, backend: Any, texts: list[str], queries: list[str]) -> dict[str, Any]:
    """Encode the corpus and the queries once, timing only the corpus pass."""
    backend.load()

    started = time.perf_counter()
    documents = backend.encode_documents(texts)
    elapsed = time.perf_counter() - started

    query_vectors = backend.encode_queries(queries)
    return {
        "name": name,
        "documents": documents.vectors,
        "queries": query_vectors.vectors,
        "seconds": round(elapsed, 2),
        "papers_per_second": round(len(texts) / elapsed, 2),
        "peak_rss_mb": peak_rss_mb(),
    }


def top_k(query_vector: np.ndarray, document_vectors: np.ndarray, k: int) -> list[int]:
    """Indices of the k nearest documents.

    Vectors are already L2-normalised, so a dot product is cosine similarity.
    """
    scores = document_vectors @ query_vector
    return list(np.argsort(-scores)[:k])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200, help="papers to encode")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--json", type=Path, default=None, help="write the report here")
    args = parser.parse_args()

    report = Report()
    report.machine = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }

    texts, corpus_stats = load_texts(args.limit)
    if not texts:
        print("No papers in the database; nothing to measure.")
        return 1
    report.corpus = corpus_stats

    queries = [query.text for query in ALL_QUERIES]

    banner("1. Machine and corpus")
    print(f"  {report.machine['platform']}")
    print(f"  {corpus_stats['sampled']} papers, mean {corpus_stats['mean_characters']} characters")
    print(f"  {len(queries)} benchmark queries")

    banner("2. Throughput")
    print(f"  {'backend':14} {'papers/s':>10} {'seconds':>9} {'RSS MB':>9}")
    results: list[dict[str, Any]] = []
    for name in ("torch-fp32", "onnx-fp32", "onnx-int8"):
        try:
            backend = make_backend(name, args.batch_size, args.threads)
            result = measure(name, backend, texts, queries)
        except FileNotFoundError as error:
            print(f"  {name:14} skipped: {error}")
            continue
        results.append(result)
        print(
            f"  {name:14} {result['papers_per_second']:>10} {result['seconds']:>9} "
            f"{result['peak_rss_mb']:>9}"
        )
        report.throughput.append(
            {key: result[key] for key in ("name", "papers_per_second", "seconds", "peak_rss_mb")}
        )

    if not results or results[0]["name"] != "torch-fp32":
        print("\nNo PyTorch baseline; fidelity and agreement need one.")
        return 1

    baseline = results[0]
    fastest = max(results, key=lambda r: r["papers_per_second"])
    if fastest is not baseline:
        speedup = fastest["papers_per_second"] / baseline["papers_per_second"]
        print(f"\n  fastest: {fastest['name']} at {speedup:.2f}x the PyTorch fp32 rate")

    banner("3. Fidelity against PyTorch fp32")
    print(f"  {'backend':14} {'mean cosine':>12} {'min cosine':>12}")
    for result in results[1:]:
        # Row-wise dot product: both sides are L2-normalised, so this is cosine.
        similarities = np.sum(baseline["documents"] * result["documents"], axis=1)
        entry = {
            "name": result["name"],
            "mean_cosine": round(float(similarities.mean()), 6),
            "min_cosine": round(float(similarities.min()), 6),
        }
        report.fidelity.append(entry)
        print(f"  {result['name']:14} {entry['mean_cosine']:>12} {entry['min_cosine']:>12}")

    banner(f"4. Retrieval agreement (top {TOP_K}, {len(queries)} queries)")
    print(f"  {'backend':14} {'mean overlap':>13} {'identical order':>16}")
    baseline_rankings = [
        top_k(baseline["queries"][index], baseline["documents"], TOP_K)
        for index in range(len(queries))
    ]
    for result in results[1:]:
        overlaps: list[float] = []
        identical = 0
        for index in range(len(queries)):
            ranking = top_k(result["queries"][index], result["documents"], TOP_K)
            expected = baseline_rankings[index]
            overlaps.append(len(set(ranking) & set(expected)) / TOP_K)
            identical += int(ranking == expected)
        entry = {
            "name": result["name"],
            "mean_overlap_at_10": round(statistics.mean(overlaps), 4),
            "identical_top_10": identical,
            "queries": len(queries),
        }
        report.retrieval_agreement.append(entry)
        print(
            f"  {result['name']:14} {entry['mean_overlap_at_10']:>13} "
            f"{f'{identical}/{len(queries)}':>16}"
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        print(f"\nWritten to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
