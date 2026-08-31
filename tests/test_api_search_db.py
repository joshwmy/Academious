"""The public search endpoint.

Search is the expensive endpoint, so almost every test here stubs the retrieval
service at the dependency boundary. That is deliberate: what these tests are
about is the HTTP contract - validation, projection, ordering, what is and is
not in the response - and running SPECTER2 to assert that a blank query is
rejected would make the suite slow without making it stronger.

One test at the bottom does run the real retrieval path, because "the API
preserves the ranking the retrieval service produced" is not a claim a stub can
support.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from academious.api.dependencies import get_retrieval_service
from academious.api.limits import limiter
from academious.api.main import app
from academious.core.config import get_settings
from academious.retrieval.filters import PreprintPolicy, RetractionPolicy, SearchFilters
from academious.retrieval.types import RetrievalHit, RetrievalResult, ScoreKind
from tests.factories import make_paper

pytestmark = pytest.mark.db


class StubRetrieval:
    """Returns a fixed ranking and records how it was called."""

    def __init__(self, paper_ids=()):
        self.paper_ids = list(paper_ids)
        self.calls: list[dict] = []

    def search_by_interest(self, session, query, *, limit=20, method="semantic", **kwargs):
        self.calls.append({"query": query, "limit": limit, "method": method, **kwargs})
        hits = [
            RetrievalHit(
                paper_id=paper_id,
                rank=index + 1,
                score=1.0 / (index + 1),
                score_kind=ScoreKind.COSINE_SIMILARITY,
            )
            for index, paper_id in enumerate(self.paper_ids[:limit])
        ]
        return RetrievalResult(query=query, method=method, hits=hits, elapsed_ms=1.0)


@pytest.fixture
def stub():
    return StubRetrieval()


@pytest.fixture
def client(session, stub):
    limiter.reset()
    limiter.enabled = False
    app.dependency_overrides[get_retrieval_service] = lambda: stub
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        limiter.enabled = True
        limiter.reset()


def _paper(session, title, *, day=1):
    return make_paper(session, title, published_date=date(2026, 1, day), abstract="Abstract.")


# --------------------------------------------------------------- validation


@pytest.mark.parametrize("raw", ["", " ", "   ", "\t", "\n\r"])
def test_a_query_with_no_searchable_content_is_rejected(client, raw, stub):
    response = client.get("/search", params={"q": raw})
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert stub.calls == [], "nothing should reach retrieval"


def test_a_missing_query_is_rejected(client, stub):
    assert client.get("/search").status_code == 422
    assert stub.calls == []


def test_an_oversized_query_is_rejected_before_retrieval(client, stub):
    response = client.get("/search", params={"q": "a" * 5000})
    assert response.status_code == 422
    assert stub.calls == [], "the tokeniser must never see it"


def test_a_query_at_the_documented_maximum_is_accepted(client, stub):
    response = client.get("/search", params={"q": "a" * get_settings().api_max_query_length})
    assert response.status_code == 200


@pytest.mark.parametrize("limit", [0, -1, 51, 1_000_000])
def test_pathological_result_counts_are_rejected(client, limit, stub):
    response = client.get("/search", params={"q": "graph", "limit": limit})
    assert response.status_code == 422
    assert stub.calls == []


def test_whitespace_in_a_query_is_normalised(client, stub):
    payload = client.get("/search", params={"q": "  graph   neural\tnetworks  "}).json()
    assert payload["query"] == "graph neural networks"
    assert stub.calls[0]["query"] == "graph neural networks"


def test_control_characters_are_stripped_from_the_query(client, stub):
    """A newline in a query is how a caller forges a second log line."""
    payload = client.get("/search", params={"q": "graph\n\rnetworks"}).json()
    assert payload["query"] == "graph networks"
    assert "\n" not in stub.calls[0]["query"]


# ---------------------------------------------------------------- responses


def test_results_are_returned_in_the_order_retrieval_ranked_them(client, session, stub):
    papers = [_paper(session, f"Paper {index}", day=index + 1) for index in range(5)]
    session.commit()
    # Deliberately neither the corpus order nor the publication order.
    stub.paper_ids = [papers[3].id, papers[0].id, papers[4].id]

    payload = client.get("/search", params={"q": "anything"}).json()

    assert [hit["rank"] for hit in payload["results"]] == [1, 2, 3]
    assert [hit["paper"]["id"] for hit in payload["results"]] == [
        str(papers[3].id),
        str(papers[0].id),
        str(papers[4].id),
    ]
    assert payload["count"] == 3


def test_a_query_with_no_matches_is_an_empty_result_not_an_error(client, stub):
    payload = client.get("/search", params={"q": "nothing matches this"}).json()
    assert payload["count"] == 0
    assert payload["results"] == []


def test_a_ranked_id_that_no_longer_exists_is_dropped(client, session, stub):
    paper = _paper(session, "Real paper")
    session.commit()
    stub.paper_ids = [paper.id, uuid.uuid4()]

    payload = client.get("/search", params={"q": "anything"}).json()

    assert payload["count"] == 1
    assert payload["results"][0]["rank"] == 1, "ranks stay contiguous after a drop"


def test_the_limit_is_passed_through_to_retrieval(client, stub):
    client.get("/search", params={"q": "graph", "limit": 7})
    assert stub.calls[0]["limit"] == 7


def test_the_method_is_server_configuration_not_a_query_parameter(client, stub):
    """A caller must not be able to select the retrieval method.

    Method selection would let anyone force the expensive path, and would make
    the response mean something different without its shape changing.
    """
    client.get("/search", params={"q": "graph", "method": "hybrid", "model_key": "anything"})

    assert stub.calls[0]["method"] == get_settings().retrieval_default_method
    assert "model_key" not in stub.calls[0]


# ------------------------------------------------------------------ filters


def test_filters_reach_the_retrieval_service(client, stub):
    """The router translates query parameters into SearchFilters and hands them on.

    It does not filter anything itself. Filtering in the router would mean
    filtering a page that ranking has already produced, which is the bug this
    endpoint exists on the other side of.
    """
    client.get(
        "/search",
        params={
            "q": "graph",
            "source": ["arxiv", "biorxiv"],
            "preprints": "only_preprints",
            "peer_reviewed": "true",
            "open_access": "true",
        },
    )

    passed = stub.calls[0]["search_filters"]
    assert passed.sources == ("arxiv", "biorxiv")
    assert passed.preprints is PreprintPolicy.ONLY_PREPRINTS
    assert passed.peer_reviewed_only is True
    assert passed.open_access_only is True


def test_an_unfiltered_search_is_identical_to_one_with_no_filter_support(client, stub):
    """The Phase 2 benchmark measured an unfiltered search. It must still be that.

    Adding parameters must not change what happens when nobody passes them, or
    every number in performance.md silently stops describing this endpoint.
    """
    client.get("/search", params={"q": "graph"})

    assert stub.calls[0]["search_filters"] == SearchFilters()


@pytest.mark.parametrize(
    "params",
    [
        {"preprints": "whatever"},
        {"peer_reviewed": "sometimes"},
        {"open_access": "maybe"},
    ],
)
def test_an_unsupported_filter_value_is_rejected(client, stub, params):
    response = client.get("/search", params={"q": "graph", **params})
    assert response.status_code == 422
    assert stub.calls == [], "an invalid filter must not reach retrieval"


def test_retraction_policy_is_not_a_query_parameter(client, stub):
    """Retracted papers stay hidden. The default is a product decision, not a preference.

    Exposing it would let a caller surface withdrawn claims through ordinary
    discovery, which is exactly what filters.py declines to allow by default.
    """
    client.get("/search", params={"q": "graph", "retraction": "include_all"})

    assert stub.calls[0]["search_filters"].retraction is RetractionPolicy.EXCLUDE_RETRACTED


# -------------------------------------------------------------- integration


@pytest.mark.model
def test_the_api_returns_exactly_the_ranking_the_retrieval_service_produces(session):
    """The API is a projection of retrieval, not a second ranker.

    If these ever disagree, the Phase 2 benchmark stops being evidence about
    this endpoint, so the equality is asserted rather than assumed.
    """
    from academious.db.session import session_scope
    from academious.embeddings import service as embedding_service
    from academious.embeddings.hashing import HashingBackend
    from academious.embeddings.registry import HASHING_AUTO
    from academious.retrieval.service import RetrievalService

    for index in range(6):
        make_paper(
            session,
            f"Graph neural networks for topic {index}",
            abstract="Message passing over molecular graphs predicts chemical properties.",
            published_date=date(2026, 1, index + 1),
        )
    session.commit()
    pending = embedding_service.select_pending_paper_ids(session, HASHING_AUTO.key, limit=100)
    embedding_service.embed_papers(
        session, pending, profile=HASHING_AUTO, backend=HashingBackend()
    )
    session.commit()

    service = RetrievalService(backend=HashingBackend(), model_key=HASHING_AUTO.key)
    with session_scope() as direct:
        expected = service.search_by_interest(
            direct,
            "graph neural networks",
            limit=5,
            method=get_settings().retrieval_default_method,
        )

    limiter.reset()
    limiter.enabled = False
    app.dependency_overrides[get_retrieval_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/search", params={"q": "graph neural networks", "limit": 5}
        )
    finally:
        app.dependency_overrides.clear()
        limiter.enabled = True
        limiter.reset()

    assert response.status_code == 200
    assert [hit["paper"]["id"] for hit in response.json()["results"]] == [
        str(paper_id) for paper_id in expected.paper_ids()
    ]


@pytest.mark.model
def test_a_filtered_search_fills_the_page_because_filtering_precedes_ranking(session):
    """A filtered search returns a full page, not a ranked page with rows removed.

    This is the whole point of applying filters in SQL. With three preprints and
    three journal articles in the corpus, a three-result search for preprints
    must return three preprints. Filtering the output of an unfiltered ranking
    would return however many of the top three happened to be preprints - the
    failure that makes filtered search feel broken.
    """
    from academious.db.session import session_scope
    from academious.embeddings import service as embedding_service
    from academious.embeddings.hashing import HashingBackend
    from academious.embeddings.registry import HASHING_AUTO
    from academious.retrieval.service import RetrievalService

    for index in range(6):
        make_paper(
            session,
            f"Graph neural networks for topic {index}",
            abstract="Message passing over molecular graphs predicts chemical properties.",
            published_date=date(2026, 1, index + 1),
            # Alternating, so an unfiltered top three cannot be all preprints.
            is_preprint=index % 2 == 0,
        )
    session.commit()
    pending = embedding_service.select_pending_paper_ids(session, HASHING_AUTO.key, limit=100)
    embedding_service.embed_papers(
        session, pending, profile=HASHING_AUTO, backend=HashingBackend()
    )
    session.commit()

    service = RetrievalService(backend=HashingBackend(), model_key=HASHING_AUTO.key)
    limiter.reset()
    limiter.enabled = False
    app.dependency_overrides[get_retrieval_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/search",
            params={"q": "graph neural networks", "limit": 3, "preprints": "only_preprints"},
        )
    finally:
        app.dependency_overrides.clear()
        limiter.enabled = True
        limiter.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3, "the page is filled from the filtered corpus"
    assert all(hit["paper"]["is_preprint"] for hit in payload["results"])

    with session_scope() as direct:
        unfiltered = service.search_by_interest(
            direct, "graph neural networks", limit=3, method=get_settings().retrieval_default_method
        )
    assert len(unfiltered.hits) == 3
