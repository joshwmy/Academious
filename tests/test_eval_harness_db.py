"""The evaluation harness: pooling, and refusing to report metrics it cannot compute.

The most important behaviour under test is negative. With no judgments, the
harness must produce rankings and *no* quality numbers - not zeros, and not a
score derived from treating whatever was retrieved as relevant.
"""

from __future__ import annotations

import uuid

import pytest

from academious.embeddings import service as embedding_service
from academious.embeddings.hashing import HashingBackend
from academious.embeddings.registry import HASHING_AUTO
from academious.eval import harness
from academious.eval import judgments as judgments_module
from academious.eval.queries import BenchmarkQuery, Domain
from academious.retrieval.service import RetrievalService
from tests.factories import make_paper

pytestmark = pytest.mark.db

PROFILE = HASHING_AUTO

QUERIES = (
    BenchmarkQuery("t-01", "cancer genomics", Domain.BIOMEDICAL, "obvious single answer"),
    BenchmarkQuery("t-02", "graph neural networks", Domain.COMPUTING, "exact architecture name"),
)


@pytest.fixture
def service(session):
    make_paper(
        session,
        "Deep learning for cancer genomics",
        abstract="Convolutional networks over tumour sequencing data predict driver mutations.",
    )
    make_paper(
        session,
        "Graph neural networks for molecular property prediction",
        abstract="Message passing over molecular graphs predicts chemical properties.",
    )
    make_paper(
        session,
        "Sediment transport in braided rivers",
        abstract="Field measurements of bedload flux in a braided alluvial channel.",
    )
    session.flush()
    pending = embedding_service.select_pending_paper_ids(session, PROFILE.key, limit=100)
    embedding_service.embed_papers(session, pending, profile=PROFILE, backend=HashingBackend())
    session.commit()
    return RetrievalService(backend=HashingBackend(), model_key=PROFILE.key)


def test_every_query_is_run_through_every_method(session, service):
    runs = harness.run_queries(session, service, queries=QUERIES, depth=5)
    assert len(runs) == 2
    for run in runs:
        assert set(run.results) == {"lexical", "semantic", "hybrid"}


def test_the_pool_unions_the_methods_and_records_which_found_what(session, service):
    runs = harness.run_queries(session, service, queries=QUERIES, depth=5)
    pool = harness.build_pool(runs)

    assert pool
    assert {entry.query_id for entry in pool} == {"t-01", "t-02"}
    # Every pooled paper names at least one method, and the list is sorted so
    # the file diffs cleanly.
    for entry in pool:
        assert entry.retrieved_by
        assert entry.retrieved_by == sorted(entry.retrieved_by)
    # A paper is pooled once per query, not once per method.
    keys = [(entry.query_id, entry.paper_id) for entry in pool]
    assert len(keys) == len(set(keys))


def test_the_pool_carries_enough_metadata_to_judge_without_a_second_window(session, service):
    runs = harness.run_queries(session, service, queries=QUERIES, depth=5)
    pool = harness.build_pool(runs)
    assert all(entry.title for entry in pool)
    assert all(entry.grade is None for entry in pool)


def test_no_judgments_means_no_metrics_rather_than_zeros(session, service):
    report, pool = harness.evaluate(session, service, queries=QUERIES, depth=5)

    assert report.scores == {}
    assert report.has_metrics is False
    assert report.judged == 0
    assert report.pooled == len(pool)

    rendered = harness.render(report)
    assert "No relevance judgments recorded yet" in rendered
    # The instructions mention the metric names; the metrics table must not appear.
    assert "Metrics over" not in rendered


def test_metrics_appear_once_something_has_been_judged(session, service):
    report, pool = harness.evaluate(session, service, queries=QUERIES, depth=5)

    for entry in pool:
        if entry.query_id == "t-01":
            relevant = "cancer" in entry.title.lower()
            judgments_module.stamp(entry, 3 if relevant else 0, "test")

    scored, _ = harness.evaluate(
        session, service, existing_judgments=pool, queries=QUERIES, depth=5
    )

    assert scored.has_metrics
    assert scored.scored_query_ids == ["t-01"]
    for method in ("lexical", "semantic", "hybrid"):
        assert scored.scores[method].queries_scored == 1
        assert scored.scores[method].precision_at_5 > 0
        assert scored.scores[method].mrr == 1.0

    rendered = harness.render(scored)
    assert "NDCG@10" in rendered
    assert "Metrics over 1 judged queries" in rendered


def test_an_unjudged_query_is_excluded_from_the_averages(session, service):
    report, pool = harness.evaluate(session, service, queries=QUERIES, depth=5)
    for entry in pool:
        if entry.query_id == "t-02":
            judgments_module.stamp(entry, 2, "test")

    scored, _ = harness.evaluate(
        session, service, existing_judgments=pool, queries=QUERIES, depth=5
    )
    assert scored.scored_query_ids == ["t-02"]
    assert scored.scores["hybrid"].queries_scored == 1


def test_rankings_are_shown_even_without_judgments(session, service):
    report, _ = harness.evaluate(session, service, queries=QUERIES, depth=5)
    rendered = harness.render(report, show_hits=3)
    assert "cancer genomics" in rendered
    assert "lexical" in rendered
    assert "semantic" in rendered
    assert "hybrid" in rendered


def test_a_partially_judged_query_is_flagged_when_unjudged_papers_sit_in_scored_ranks(
    session, service
):
    """Metrics over a half-judged query are not trustworthy and must say so.

    Every unjudged id in a ranking scores zero. That is the right conservative
    assumption, but it means a query whose best hits are simply unlabelled
    reports a confidently wrong number - and the reader cannot tell it apart
    from a genuinely bad ranking unless the report says which ranks were dark.
    """
    report, pool = harness.evaluate(session, service, queries=QUERIES, depth=5)

    run = next(run for run in report.runs if run.query.id == "t-01")
    top_lexical = run.results["lexical"].paper_ids()[0]
    for entry in pool:
        if entry.query_id == "t-01" and uuid.UUID(entry.paper_id) != top_lexical:
            judgments_module.stamp(entry, 0, "test")

    scored, _ = harness.evaluate(
        session, service, existing_judgments=pool, queries=QUERIES, depth=5
    )

    assert scored.scored_query_ids == ["t-01"]
    coverage = {entry.query_id: entry for entry in scored.query_coverage}
    assert set(coverage) == {"t-01"}, "coverage is reported for scored queries only"

    t01 = coverage["t-01"]
    assert t01.pooled > t01.judged
    assert t01.unjudged_in_scored_ranks["lexical"] >= 1
    assert t01.is_contaminated

    rendered = harness.render(scored)
    assert "unjudged" in rendered.lower()
    assert "t-01" in rendered


def test_a_fully_judged_query_is_not_flagged(session, service):
    report, pool = harness.evaluate(session, service, queries=QUERIES, depth=5)
    for entry in pool:
        if entry.query_id == "t-01":
            judgments_module.stamp(entry, 2 if "cancer" in entry.title.lower() else 0, "test")

    scored, _ = harness.evaluate(
        session, service, existing_judgments=pool, queries=QUERIES, depth=5
    )

    t01 = next(entry for entry in scored.query_coverage if entry.query_id == "t-01")
    assert t01.judged == t01.pooled
    assert not t01.is_contaminated
    assert sum(t01.unjudged_in_scored_ranks.values()) == 0
