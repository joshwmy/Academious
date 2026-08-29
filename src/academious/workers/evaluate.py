"""The evaluation entry point: run the benchmark, refresh the pool, report.

Running this is safe at any time. It re-queries, re-pools and re-scores, and the
merge in `judgments.merge` guarantees that no grade a human has recorded is lost
when the pool changes underneath it.
"""

from __future__ import annotations

from pathlib import Path

from academious.core.logging import get_logger
from academious.db.session import session_scope
from academious.eval import harness
from academious.eval import judgments as judgments_module
from academious.eval.queries import ALL_QUERIES, BIOMEDICAL, COMPUTING, BenchmarkQuery
from academious.retrieval.service import RetrievalService
from academious.workers import embed as embed_worker

log = get_logger(__name__)

#: Judgments are an input to the project, not an output of a run, so they live
#: in the repository rather than in a scratch directory.
DEFAULT_JUDGMENTS_PATH = Path("data/eval/judgments.jsonl")

DOMAIN_SETS: dict[str, tuple[BenchmarkQuery, ...]] = {
    "all": ALL_QUERIES,
    "biomedical": BIOMEDICAL,
    "computing": COMPUTING,
}


def run(
    *,
    profile_key: str | None = None,
    depth: int = harness.DEFAULT_DEPTH,
    domain: str = "all",
    judgments_path: Path = DEFAULT_JUDGMENTS_PATH,
    write_pool: bool = True,
    show_hits: int = 5,
) -> harness.EvaluationReport:
    """Run the benchmark and print the report. Returns it for programmatic use."""
    profile = embed_worker.resolve_profile(profile_key)
    backend = embed_worker.build(profile)
    service = RetrievalService(backend=backend, model_key=profile.key)

    try:
        queries = DOMAIN_SETS[domain]
    except KeyError:
        raise ValueError(
            f"unknown domain {domain!r}; expected one of {sorted(DOMAIN_SETS)}"
        ) from None

    existing = judgments_module.read(judgments_path)

    with session_scope() as session:
        report, pool = harness.evaluate(
            session,
            service,
            existing_judgments=existing,
            queries=queries,
            depth=depth,
        )

    if write_pool:
        written = judgments_module.write(judgments_path, pool)
        log.info(
            "eval.pool_written",
            path=str(judgments_path),
            rows=written,
            judged=report.judged,
        )

    print(harness.render(report, show_hits=show_hits))
    if not report.has_metrics:
        print()
        print(f"Pool written to {judgments_path}.")
        print("Set the `grade` field on each line to 0, 1, 2 or 3, then re-run:")
        for grade, label in sorted(judgments_module.describe_scale().items()):
            print(f"    {grade} = {label}")
    return report
