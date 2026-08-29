"""Phase 2 measurements: SPECTER2 throughput, storage, retrieval latency.

Everything printed here is measured on the machine it runs on. Anything that
could not be measured is labelled an estimate and shows the arithmetic that
produced it, so a reader can substitute their own inputs rather than trust a
number whose provenance is invisible.

    docker compose up -d db
    python -m alembic upgrade head
    python -m academious.workers harvest --source biorxiv --max-records 1200
    python scripts/benchmark_phase2.py --papers 400

Requires the `embed` extra. Without it, everything except the SPECTER2 sections
still runs against the hashing backend, which is useful for the storage and
retrieval-latency numbers and useless for throughput.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from academious.db.models.embedding import PaperEmbedding  # noqa: E402
from academious.db.models.paper import Paper  # noqa: E402
from academious.db.session import session_scope  # noqa: E402
from academious.embeddings import index as ann_index  # noqa: E402
from academious.embeddings import service as embedding_service  # noqa: E402
from academious.embeddings.registry import EmbeddingProfile  # noqa: E402
from academious.embeddings.text import InputMode, build_embedding_input  # noqa: E402
from academious.eval.queries import ALL_QUERIES  # noqa: E402
from academious.retrieval import hybrid, lexical, semantic  # noqa: E402

OUTPUT = ROOT / "docs" / "phase-2-benchmark.json"

#: Daily new-paper volume for the two launch domains, taken from the Phase 0
#: cost model (~125,000-130,000 net distinct papers/month). It is an input to
#: the projections, not something measured here, and it is stated in the
#: output so a reader can substitute their own.
DAILY_NEW_PAPERS = 5_000
BACKFILL_MONTHS = 6


@dataclass
class Report:
    generated_at: str
    machine: dict[str, Any] = field(default_factory=dict)
    corpus: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    throughput: list[dict[str, Any]] = field(default_factory=list)
    storage: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, Any] = field(default_factory=dict)
    halfvec_fidelity: dict[str, Any] = field(default_factory=dict)
    ann: dict[str, Any] = field(default_factory=dict)
    projections: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def row(label: str, value: Any) -> None:
    print(f"  {label:<44} {value}")


def peak_rss_mb() -> float:
    info = psutil.Process().memory_info()
    # peak_wset is Windows-only; rss is the portable floor.
    return getattr(info, "peak_wset", info.rss) / (1024 * 1024)


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# ------------------------------------------------------------------- machine


def measure_machine(report: Report) -> None:
    banner("1. Machine")
    memory = psutil.virtual_memory()
    report.machine = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_total_gb": round(memory.total / 1024**3, 2),
        "ram_available_gb": round(memory.available / 1024**3, 2),
        "python": platform.python_version(),
    }
    for key, value in report.machine.items():
        row(key, value)


# --------------------------------------------------------------------- model


def measure_model(report: Report, backend: Any, sample_texts: list[str]) -> None:
    banner("2. SPECTER2: verified model facts and load cost")

    started = time.perf_counter()
    backend.load()
    load_seconds = time.perf_counter() - started

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    weights = sum(
        directory_bytes(cache / name)
        for name in (
            "models--allenai--specter2_base",
            "models--allenai--specter2",
            "models--allenai--specter2_adhoc_query",
        )
    )

    tokenizer = backend._tokenizer  # noqa: SLF001 - a benchmark may look inside
    lengths = [len(ids) for ids in tokenizer(sample_texts)["input_ids"]]

    report.model = {
        "model_id": backend.model_id,
        "base": "allenai/specter2_base",
        "document_adapter": "allenai/specter2 (proximity)",
        "query_adapter": "allenai/specter2_adhoc_query",
        "dimension": backend.dimension,
        "max_sequence_length": backend.max_sequence_length,
        "separator": tokenizer.sep_token,
        "licence": "Apache-2.0",
        "weights_on_disk_mb": round(weights / 1024**2, 1),
        "load_seconds": round(load_seconds, 2),
        "rss_after_load_mb": round(psutil.Process().memory_info().rss / 1024**2, 1),
        "token_length_median": int(statistics.median(lengths)) if lengths else 0,
        "token_length_p95": int(np.percentile(lengths, 95)) if lengths else 0,
        "truncated_fraction": (
            round(sum(1 for n in lengths if n > backend.max_sequence_length) / len(lengths), 4)
            if lengths
            else 0.0
        ),
    }
    for key, value in report.model.items():
        row(key, value)


# ---------------------------------------------------------------- throughput


def measure_throughput(
    report: Report, backend: Any, texts: list[str], batch_sizes: tuple[int, ...]
) -> None:
    banner("3. Embedding throughput")
    print(f"  {len(texts)} real paper texts, encoded once per batch size\n")
    print("  batch  papers  seconds  papers/sec  cores  peak RSS MB")

    for batch_size in batch_sizes:
        backend.batch_size = batch_size
        process = psutil.Process()
        cpu_before = process.cpu_times()
        started = time.perf_counter()
        encoded = backend.encode_documents(texts)
        elapsed = time.perf_counter() - started
        cpu_after = process.cpu_times()

        cpu_seconds = (cpu_after.user - cpu_before.user) + (cpu_after.system - cpu_before.system)
        entry = {
            "batch_size": batch_size,
            "papers": len(texts),
            "seconds": round(elapsed, 2),
            "papers_per_second": round(len(texts) / elapsed, 2),
            "cpu_seconds": round(cpu_seconds, 2),
            "cpu_utilisation_cores": round(cpu_seconds / elapsed, 2),
            "peak_rss_mb": round(peak_rss_mb(), 1),
            "truncated": int(sum(encoded.truncated)),
        }
        report.throughput.append(entry)
        print(
            f"  {batch_size:>5}  {entry['papers']:>6}  {entry['seconds']:>7}  "
            f"{entry['papers_per_second']:>10}  {entry['cpu_utilisation_cores']:>5}  "
            f"{entry['peak_rss_mb']:>11}"
        )


# ------------------------------------------------------------------- storage


def measure_storage(report: Report, model_key: str) -> None:
    banner("4. Storage")
    with session_scope() as session:
        vectors = session.execute(
            select(func.count())
            .select_from(PaperEmbedding)
            .where(PaperEmbedding.model_key == model_key)
        ).scalar_one()
        table_bytes = session.execute(
            text("SELECT pg_total_relation_size('paper_embedding')")
        ).scalar_one()
        paper_bytes = session.execute(
            text("SELECT pg_total_relation_size('paper')")
        ).scalar_one()
        tsv_index_bytes = session.execute(
            text("SELECT pg_relation_size('ix_paper_search_tsv')")
        ).scalar_one()

    per_vector = table_bytes / vectors if vectors else 0
    report.storage.update(
        {
            "vectors": vectors,
            "paper_embedding_total_bytes": int(table_bytes),
            "bytes_per_vector_including_overhead": round(per_vector, 1),
            "halfvec_payload_bytes": 768 * 2,
            "float32_payload_bytes_for_comparison": 768 * 4,
            "paper_table_total_bytes": int(paper_bytes),
            "search_tsv_index_bytes": int(tsv_index_bytes),
            "projected_mb_per_10k_vectors": round(per_vector * 10_000 / 1024**2, 1),
            "projected_gb_per_100k_vectors": round(per_vector * 100_000 / 1024**3, 3),
        }
    )
    for key, value in report.storage.items():
        row(key, value)


# ------------------------------------------------------------------- latency


def time_calls(callable_, repeats: int) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    return {
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 2),
        "min_ms": round(samples[0], 2),
        "max_ms": round(samples[-1], 2),
        "samples": len(samples),
    }


def measure_latency(report: Report, backend: Any, model_key: str, repeats: int) -> None:
    banner("5. Retrieval latency")
    queries = [query.text for query in ALL_QUERIES]
    vectors = {query: semantic.encode_query(backend, query) for query in queries}

    with session_scope() as session:

        def run_lexical() -> None:
            for query in queries:
                lexical.search(session, query, limit=20)

        def run_semantic() -> None:
            for query in queries:
                semantic.search(session, vectors[query], model_key=model_key, limit=20)

        def run_hybrid() -> None:
            for query in queries:
                components = {
                    "lexical": lexical.search(session, query, limit=100),
                    "semantic": semantic.search(
                        session, vectors[query], model_key=model_key, limit=100
                    ),
                }
                hybrid.fuse(session, components, limit=20)

        report.latency = {
            "queries_per_pass": len(queries),
            "lexical": time_calls(run_lexical, repeats),
            "semantic_exact": time_calls(run_semantic, repeats),
            "hybrid": time_calls(run_hybrid, repeats),
        }

    for name in ("lexical", "semantic_exact", "hybrid"):
        entry = report.latency[name]
        per_query = entry["median_ms"] / len(queries)
        entry["median_ms_per_query"] = round(per_query, 2)
        row(f"{name} median per query", f"{per_query:.2f} ms")


# ---------------------------------------------------------- halfvec fidelity


def measure_halfvec_fidelity(
    report: Report, backend: Any, model_key: str, k: int, sample: int
) -> None:
    """What does storing at half precision actually cost?

    Measured over one sample of papers encoded once. The float32 vectors the
    model produced are the reference; rounding them to float16 and back is
    exactly what the halfvec column does to them. Comparing the two rankings
    therefore isolates the storage precision and nothing else.

    A separate round-trip check confirms the vectors PostgreSQL gives back match
    that rounding, so the numpy result describes the real storage path rather
    than a model of it.
    """
    banner("6. Half precision fidelity")

    with session_scope() as session:
        rows = session.execute(
            select(Paper.id, Paper.title, Paper.abstract, PaperEmbedding.embedding)
            .join(PaperEmbedding, PaperEmbedding.paper_id == Paper.id)
            .where(PaperEmbedding.model_key == model_key)
            .order_by(Paper.id)
            .limit(sample)
        ).all()
    if len(rows) < 2:
        report.halfvec_fidelity = {"skipped": "not enough vectors stored"}
        print("  skipped: not enough vectors stored")
        return

    texts = [build_embedding_input(r.title, r.abstract, mode=InputMode.AUTO).text for r in rows]
    print(f"  encoding {len(texts)} papers once to obtain the float32 reference ...")
    reference = backend.encode_documents(texts).vectors.astype(np.float32)
    quantised = reference.astype(np.float16).astype(np.float32)
    stored = np.asarray([np.asarray(r.embedding, dtype=np.float32) for r in rows])

    # Does what PostgreSQL hands back match what float16 rounding predicts?
    round_trip_error = float(np.max(np.abs(stored - quantised)))

    overlaps = []
    top1 = []
    for query in ALL_QUERIES:
        vector = semantic.encode_query(backend, query.text)
        exact_order = np.argsort(-(reference @ vector))[:k]
        half_order = np.argsort(-(quantised @ vector))[:k]
        overlaps.append(len(set(exact_order.tolist()) & set(half_order.tolist())) / k)
        top1.append(bool(exact_order[0] == half_order[0]))

    report.halfvec_fidelity = {
        "k": k,
        "sample_papers": len(rows),
        "queries": len(ALL_QUERIES),
        "max_component_error_vs_stored": round(round_trip_error, 8),
        "mean_topk_overlap": round(float(np.mean(overlaps)), 4),
        "min_topk_overlap": round(float(np.min(overlaps)), 4),
        "top1_agreement": round(float(np.mean(top1)), 4),
        "note": (
            "Vectors are L2-normalised before storage, so every component lies in "
            "[-1, 1] where float16 carries about three decimal digits."
        ),
    }
    for key, value in report.halfvec_fidelity.items():
        row(key, value)


# ----------------------------------------------------------------------- ANN


def measure_ann(report: Report, backend: Any, model_key: str, k: int, repeats: int) -> None:
    banner("7. Approximate search (HNSW)")
    queries = [q.text for q in ALL_QUERIES]
    vectors = {query: semantic.encode_query(backend, query) for query in queries}

    with session_scope() as session:
        exact = {
            query: semantic.search(
                session, vectors[query], model_key=model_key, limit=k
            ).paper_ids()
            for query in queries
        }

    started = time.perf_counter()
    with session_scope() as session:
        ann_index.create_hnsw(session)
    build_seconds = time.perf_counter() - started

    with session_scope() as session:
        state = ann_index.state(session)

        def run_ann() -> None:
            for query in queries:
                semantic.search(session, vectors[query], model_key=model_key, limit=k)

        timings = time_calls(run_ann, repeats)

        recalls = []
        for query in queries:
            got = semantic.search(session, vectors[query], model_key=model_key, limit=k)
            truth = exact[query]
            recalls.append(len(set(truth) & set(got.paper_ids())) / max(1, len(truth)))

    report.ann = {
        "k": k,
        "build_seconds": round(build_seconds, 2),
        "index_bytes": state.size_bytes,
        "definition": state.definition,
        "latency": timings,
        "median_ms_per_query": round(timings["median_ms"] / len(queries), 2),
        "recall_at_k_vs_exact": round(float(np.mean(recalls)), 4),
    }
    for key, value in report.ann.items():
        row(key, value)

    # The index is a measurement artefact, not a shipped default. Leaving it
    # behind would silently change what later runs measure.
    with session_scope() as session:
        ann_index.drop_hnsw(session)
    print("  index dropped again (no migration creates it; see docs/retrieval.md)")


# ------------------------------------------------------------------ estimates


def project(report: Report) -> None:
    banner("8. Projections (ESTIMATES, derived from the measurements above)")
    if not report.throughput:
        print("  skipped: no throughput measured")
        return

    best = max(report.throughput, key=lambda entry: entry["papers_per_second"])
    rate = best["papers_per_second"]
    daily_seconds = DAILY_NEW_PAPERS / rate
    backfill_papers = DAILY_NEW_PAPERS * 30 * BACKFILL_MONTHS
    per_vector = report.storage.get("bytes_per_vector_including_overhead", 0)

    report.projections = {
        "basis": "ESTIMATE - measured papers/sec applied to an assumed daily volume",
        "assumed_daily_new_papers": DAILY_NEW_PAPERS,
        "best_measured_papers_per_second": rate,
        "best_batch_size": best["batch_size"],
        "daily_delta_minutes": round(daily_seconds / 60, 1),
        "backfill_months": BACKFILL_MONTHS,
        "backfill_papers": backfill_papers,
        "backfill_hours_this_machine": round(backfill_papers / rate / 3600, 1),
        "backfill_storage_gb": round(backfill_papers * per_vector / 1024**3, 2),
        "annual_new_papers": DAILY_NEW_PAPERS * 365,
        "annual_storage_growth_gb": round(DAILY_NEW_PAPERS * 365 * per_vector / 1024**3, 2),
    }
    for key, value in report.projections.items():
        row(key, value)


# ---------------------------------------------------------------------- main


def load_texts(limit: int) -> tuple[list[str], dict[str, Any]]:
    """Real paper texts from the ingested corpus, built exactly as production would."""
    with session_scope() as session:
        papers = session.execute(
            select(Paper.title, Paper.abstract).order_by(Paper.created_at.desc()).limit(limit)
        ).all()
        total = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        with_abstract = session.execute(
            select(func.count()).select_from(Paper).where(Paper.abstract.is_not(None))
        ).scalar_one()

    built = [build_embedding_input(p.title, p.abstract, mode=InputMode.AUTO) for p in papers]
    texts = [b.text for b in built if b.text]
    stats = {
        "papers_in_database": total,
        "papers_with_abstract": with_abstract,
        "abstract_coverage": round(with_abstract / total, 4) if total else 0.0,
        "sampled": len(texts),
        "sampled_title_only": sum(
            1 for b in built if b.strategy.value == "title_only" and b.text
        ),
        "mean_characters": round(statistics.mean(len(t) for t in texts), 1) if texts else 0,
    }
    return texts, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers", type=int, default=300, help="Texts used for throughput")
    parser.add_argument(
        "--corpus",
        type=int,
        default=800,
        help="How many papers to give vectors. Bounds a run on a slow machine; "
        "the embedding path is idempotent so a later run resumes rather than repeats.",
    )
    parser.add_argument("--fidelity-sample", type=int, default=200)
    parser.add_argument("--batch-sizes", default="8,16,32")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--backend",
        default="specter2",
        choices=("specter2", "hashing"),
        help="hashing runs everything except real model numbers, with no torch",
    )
    parser.add_argument("--skip-ann", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    report = Report(generated_at=datetime.now(UTC).isoformat())
    measure_machine(report)

    texts, corpus_stats = load_texts(args.papers)
    report.corpus = corpus_stats
    banner("Corpus")
    for key, value in corpus_stats.items():
        row(key, value)
    if not texts:
        print("\nNo papers ingested. Harvest first; see the module docstring.")
        return 1

    if args.backend == "specter2":
        from academious.embeddings.specter2 import Specter2Backend

        backend: Any = Specter2Backend(batch_size=16)
        profile = EmbeddingProfile(
            key="specter2-benchmark@v1", backend_name="specter2", input_mode=InputMode.AUTO
        )
        measure_model(report, backend, texts[:200])
        batch_sizes = tuple(int(v) for v in args.batch_sizes.split(","))
        measure_throughput(report, backend, texts, batch_sizes)
    else:
        from academious.embeddings.hashing import HashingBackend

        backend = HashingBackend()
        profile = EmbeddingProfile(
            key="hashing-benchmark@v1", backend_name="hashing", input_mode=InputMode.AUTO
        )
        report.notes.append("Model and throughput sections skipped: hashing backend selected.")

    banner("Populating vectors for the storage and retrieval measurements")
    embedded = 0
    started = time.perf_counter()
    while embedded < args.corpus:
        with session_scope() as session:
            wanted = min(64, args.corpus - embedded)
            batch = embedding_service.select_pending_paper_ids(
                session, profile.key, limit=wanted
            )
            if not batch:
                break
            stats = embedding_service.embed_papers(
                session, batch, profile=profile, backend=backend
            )
        embedded += stats.embedded
        print(f"  embedded {embedded} papers", end="\r")
    insert_seconds = time.perf_counter() - started
    print(f"  embedded {embedded} papers in {insert_seconds:.1f}s" + " " * 20)
    report.storage["write_papers_per_second"] = (
        round(embedded / insert_seconds, 2) if insert_seconds else None
    )

    measure_storage(report, profile.key)
    measure_latency(report, backend, profile.key, args.repeats)
    measure_halfvec_fidelity(report, backend, profile.key, args.k, args.fidelity_sample)
    if not args.skip_ann:
        measure_ann(report, backend, profile.key, args.k, args.repeats)
    project(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.__dict__, indent=2, default=str), encoding="utf-8")
    print(f"\nWritten to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
