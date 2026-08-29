"""Running the benchmark and scoring it.

The harness has two halves that must not be confused with each other:

* **Retrieval**, which always works. Run the query set through every method and
  produce inspectable output. This needs no labels and is useful on day one.
* **Scoring**, which requires judgments. Metrics are computed only over queries
  that actually have judged papers, and the report says how many that was.

If nothing has been judged, the report contains rankings and no metrics. It does
not contain zeros, and it does not contain a number derived from treating
"retrieved" as "relevant" - that would be measuring the system against itself.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from academious.eval import judgments as judgments_module
from academious.eval import metrics
from academious.eval.queries import ALL_QUERIES, BenchmarkQuery
from academious.retrieval.filters import SearchFilters
from academious.retrieval.service import ALL_METHODS, RetrievalService
from academious.retrieval.types import RetrievalResult

DEFAULT_DEPTH = 20


@dataclass(slots=True)
class QueryRun:
    query: BenchmarkQuery
    results: dict[str, RetrievalResult]

    def ranked_ids(self, method: str) -> list[uuid.UUID]:
        return self.results[method].paper_ids()


@dataclass(slots=True)
class MethodScores:
    method: str
    queries_scored: int = 0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_10: float = 0.0
    mean_latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvaluationReport:
    depth: int
    runs: list[QueryRun]
    scores: dict[str, MethodScores] = field(default_factory=dict)
    judged: int = 0
    pooled: int = 0
    scored_query_ids: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def has_metrics(self) -> bool:
        return bool(self.scores)


def run_queries(
    session: Session,
    service: RetrievalService,
    *,
    queries: tuple[BenchmarkQuery, ...] = ALL_QUERIES,
    depth: int = DEFAULT_DEPTH,
    search_filters: SearchFilters | None = None,
) -> list[QueryRun]:
    """Run every query through lexical, semantic and hybrid retrieval."""
    runs: list[QueryRun] = []
    for query in queries:
        results = service.search_all_methods(
            session, query.text, limit=depth, search_filters=search_filters
        )
        runs.append(QueryRun(query=query, results=results))
    return runs


def build_pool(runs: list[QueryRun]) -> list[judgments_module.Judgment]:
    """Union the rankings from every method into one set of papers to judge.

    Pooling across methods rather than judging each ranking separately is what
    keeps the comparison fair: every candidate gets judged, so no method is
    penalised for surfacing a good paper that the others missed.
    """
    pooled: list[judgments_module.Judgment] = []
    for run in runs:
        by_paper: dict[uuid.UUID, judgments_module.Judgment] = {}
        for method, result in run.results.items():
            for hit in result.hits:
                entry = by_paper.get(hit.paper_id)
                if entry is None:
                    entry = judgments_module.Judgment(
                        query_id=run.query.id,
                        paper_id=str(hit.paper_id),
                        title=hit.title,
                        canonical_doi=hit.canonical_doi,
                        retrieved_by=[],
                    )
                    by_paper[hit.paper_id] = entry
                if method not in entry.retrieved_by:
                    entry.retrieved_by.append(method)
        for entry in by_paper.values():
            entry.retrieved_by.sort()
        pooled.extend(by_paper.values())
    return pooled


def score(
    runs: list[QueryRun],
    grades_by_query: dict[str, dict[uuid.UUID, int]],
) -> tuple[dict[str, MethodScores], list[str]]:
    """Compute metrics for each method over the queries that have judgments."""
    scorable = [run for run in runs if grades_by_query.get(run.query.id)]
    if not scorable:
        return {}, []

    scores: dict[str, MethodScores] = {}
    for method in ALL_METHODS:
        precision_5: list[float] = []
        precision_10: list[float] = []
        recall_10: list[float] = []
        rr: list[float] = []
        ndcg_10: list[float] = []
        latency: list[float] = []

        for run in scorable:
            result = run.results.get(method)
            if result is None:
                continue
            ranked = result.paper_ids()
            grades = grades_by_query[run.query.id]
            precision_5.append(metrics.precision_at_k(ranked, grades, 5))
            precision_10.append(metrics.precision_at_k(ranked, grades, 10))
            recall_10.append(metrics.recall_at_k(ranked, grades, 10))
            rr.append(metrics.reciprocal_rank(ranked, grades))
            ndcg_10.append(metrics.ndcg_at_k(ranked, grades, 10))
            latency.append(result.elapsed_ms)

        scores[method] = MethodScores(
            method=method,
            queries_scored=len(precision_5),
            precision_at_5=metrics.mean(precision_5),
            precision_at_10=metrics.mean(precision_10),
            recall_at_10=metrics.mean(recall_10),
            mrr=metrics.mean(rr),
            ndcg_at_10=metrics.mean(ndcg_10),
            mean_latency_ms=metrics.mean(latency),
        )
    return scores, [run.query.id for run in scorable]


def evaluate(
    session: Session,
    service: RetrievalService,
    *,
    existing_judgments: list[judgments_module.Judgment] | None = None,
    queries: tuple[BenchmarkQuery, ...] = ALL_QUERIES,
    depth: int = DEFAULT_DEPTH,
    search_filters: SearchFilters | None = None,
) -> tuple[EvaluationReport, list[judgments_module.Judgment]]:
    """Run the benchmark, pool it, score it if possible. Returns (report, pool)."""
    started = time.perf_counter()
    runs = run_queries(
        session, service, queries=queries, depth=depth, search_filters=search_filters
    )
    pool = judgments_module.merge(existing_judgments or [], build_pool(runs))
    grades = judgments_module.grade_map(pool)
    scores, scored_ids = score(runs, grades)
    judged, total = judgments_module.coverage(pool)

    report = EvaluationReport(
        depth=depth,
        runs=runs,
        scores=scores,
        judged=judged,
        pooled=total,
        scored_query_ids=scored_ids,
        elapsed_s=time.perf_counter() - started,
    )
    return report, pool


def render(report: EvaluationReport, *, show_hits: int = 5) -> str:
    """Human-readable report. The rankings are the point when metrics are absent."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"Retrieval benchmark: {len(report.runs)} queries, pool depth {report.depth}")
    lines.append(f"Judgments: {report.judged} of {report.pooled} pooled papers judged")
    lines.append("=" * 78)

    for run in report.runs:
        lines.append("")
        lines.append(f"[{run.query.id}] {run.query.text}")
        lines.append(f"    intent: {run.query.intent}")
        for method in ALL_METHODS:
            result = run.results.get(method)
            if result is None:
                continue
            lines.append(f"  {method:9} {len(result.hits):3} hits  {result.elapsed_ms:7.1f} ms")
            for hit in result.hits[:show_hits]:
                flag = "" if hit.retraction_status == "none" else f" [{hit.retraction_status}]"
                lines.append(f"      {hit.rank:2}. {hit.score:7.4f}  {hit.title[:60]}{flag}")

    lines.append("")
    lines.append("=" * 78)
    if not report.has_metrics:
        lines.append("No relevance judgments recorded yet, so no quality metrics are reported.")
        lines.append("Label the pool file, then re-run to obtain P@5, P@10, recall, MRR, NDCG.")
    else:
        lines.append(f"Metrics over {len(report.scored_query_ids)} judged queries")
        header = "  {:10} {:>6} {:>6} {:>6} {:>6} {:>8} {:>8}".format(
            "method", "P@5", "P@10", "R@10", "MRR", "NDCG@10", "ms"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for method in ALL_METHODS:
            row = report.scores.get(method)
            if row is None:
                continue
            lines.append(
                f"  {row.method:10} {row.precision_at_5:6.3f} {row.precision_at_10:6.3f} "
                f"{row.recall_at_10:6.3f} {row.mrr:6.3f} {row.ndcg_at_10:8.3f} "
                f"{row.mean_latency_ms:8.1f}"
            )
    lines.append("=" * 78)
    return "\n".join(lines)
