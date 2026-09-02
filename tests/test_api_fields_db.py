"""Browsing and searching by subject field.

The property worth testing is not that a filter filters. It is that **one**
filter reaches papers classified by four disagreeing source vocabularies: an
OpenAlex record carrying `field`, an arXiv preprint carrying `cs.LG`, and a
bioRxiv preprint carrying `neuroscience` must all be reachable from the same
`field=` value, and a Europe PMC paper carrying only MeSH must be honestly
reported as reachable from none of them.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from academious.api.dependencies import get_retrieval_service
from academious.api.limits import limiter
from academious.api.main import app
from tests.factories import make_paper

pytestmark = pytest.mark.db


@pytest.fixture
def client(session):
    limiter.reset()
    limiter.enabled = False
    try:
        yield TestClient(app)
    finally:
        limiter.enabled = True
        limiter.reset()


def _searching_client(session):
    """A client whose search runs for real, on the torch-free hashing backend.

    Search is the one endpoint a stub cannot answer for here: the claim is that
    a field filter reaches the SQL *before* ranking, which only the real
    retrieval path can demonstrate. The hashing backend keeps that honest and
    fast - it produces real vectors with real similarity structure and needs no
    model download.
    """
    from academious.embeddings import service as embedding_service
    from academious.embeddings.hashing import HashingBackend
    from academious.embeddings.registry import HASHING_AUTO
    from academious.retrieval.service import RetrievalService

    pending = embedding_service.select_pending_paper_ids(session, HASHING_AUTO.key, limit=1000)
    embedding_service.embed_papers(
        session, pending, profile=HASHING_AUTO, backend=HashingBackend()
    )
    session.commit()

    service = RetrievalService(backend=HashingBackend(), model_key=HASHING_AUTO.key)
    app.dependency_overrides[get_retrieval_service] = lambda: service
    return TestClient(app)


def _paper(session, title, *, day=1, topics=(), **kwargs):
    return make_paper(
        session,
        title,
        published_date=date(2026, 1, day),
        abstract="An abstract about learning systems.",
        topics=topics,
        **kwargs,
    )


OPENALEX_CS = ({"scheme": "openalex", "id": "T1", "field": "Computer Science"},)
ARXIV_CS = ({"scheme": "arxiv", "id": "cs.LG", "label": "cs.LG"},)
BIORXIV_NEURO = ({"scheme": "biorxiv", "id": "neuroscience", "label": "neuroscience"},)
MESH_ONLY = ({"scheme": "mesh", "id": "Neoplasms", "label": "Neoplasms"},)


# --- the cross-source property ----------------------------------------------


def test_one_field_filter_reaches_every_source_vocabulary(client, session):
    _paper(session, "OpenAlex says computer science", day=1, topics=OPENALEX_CS)
    _paper(session, "arXiv says cs.LG", day=2, topics=ARXIV_CS)
    _paper(session, "bioRxiv says neuroscience", day=3, topics=BIORXIV_NEURO)
    session.commit()

    payload = client.get("/papers", params={"field": "computer-science"}).json()

    titles = {result["title"] for result in payload["results"]}
    assert titles == {"OpenAlex says computer science", "arXiv says cs.LG"}
    assert payload["page"]["total"] == 2


def test_a_paper_classified_only_in_mesh_is_reachable_by_no_field(client, session):
    _paper(session, "Europe PMC only knows MeSH", topics=MESH_ONLY)
    session.commit()

    assert client.get("/papers").json()["page"]["total"] == 1
    for slug in ("medicine", "computer-science", "neuroscience"):
        assert client.get("/papers", params={"field": slug}).json()["page"]["total"] == 0


def test_the_summary_reports_the_fields_a_paper_carries(client, session):
    _paper(session, "Learning in brains", topics=(*ARXIV_CS, *BIORXIV_NEURO))
    session.commit()

    result = client.get("/papers").json()["results"][0]
    assert result["fields"] == ["computer-science", "neuroscience"]


# --- several fields, and rejecting a slug that is not one -------------------


def test_several_fields_are_a_union_not_an_intersection(client, session):
    _paper(session, "Computing", day=1, topics=ARXIV_CS)
    _paper(session, "Brains", day=2, topics=BIORXIV_NEURO)
    _paper(session, "Neither", day=3, topics=MESH_ONLY)
    session.commit()

    payload = client.get("/papers", params={"field": ["computer-science", "neuroscience"]}).json()

    assert {result["title"] for result in payload["results"]} == {"Computing", "Brains"}


@pytest.mark.parametrize("endpoint", ["/papers", "/search"])
def test_an_unknown_field_is_refused_rather_than_ignored(client, session, endpoint):
    # Ignoring it would answer a filtered request with an unfiltered page, and
    # an empty page would make a typo look like an empty field.
    params = {"field": "compter-science"}
    if endpoint == "/search":
        params["q"] = "learning"

    response = client.get(endpoint, params=params)

    assert response.status_code == 422
    assert "compter-science" in response.json()["detail"]


def test_a_known_field_is_accepted_on_search(client, session):  # noqa: ARG001
    _paper(session, "Learning systems in computing", topics=ARXIV_CS)
    _paper(session, "Learning systems in brains", topics=BIORXIV_NEURO)
    session.commit()

    payload = (
        _searching_client(session)
        .get("/search", params={"q": "learning systems", "field": "computer-science"})
        .json()
    )

    titles = [hit["paper"]["title"] for hit in payload["results"]]
    assert titles == ["Learning systems in computing"]


def test_search_filters_before_ranking(client, session):  # noqa: ARG001
    # Five computing papers and three neuroscience ones. Filtering after ranking
    # would return however many of the top three happened to be neuroscience;
    # filtering before it returns three.
    for index in range(5):
        _paper(session, f"Learning systems {index}", day=index + 1, topics=ARXIV_CS)
    for index in range(3):
        _paper(session, f"Learning brains {index}", day=index + 6, topics=BIORXIV_NEURO)
    session.commit()

    payload = (
        _searching_client(session)
        .get("/search", params={"q": "learning", "field": "neuroscience", "limit": 3})
        .json()
    )

    assert len(payload["results"]) == 3
    assert all("neuroscience" in hit["paper"]["fields"] for hit in payload["results"])


# --- the vocabulary endpoint -------------------------------------------------


def test_fields_lists_the_whole_vocabulary_with_counts(client, session):
    _paper(session, "Computing", day=1, topics=ARXIV_CS)
    _paper(session, "More computing", day=2, topics=OPENALEX_CS)
    _paper(session, "Brains", day=3, topics=BIORXIV_NEURO)
    session.commit()

    payload = client.get("/fields").json()

    counts = {entry["slug"]: entry["paper_count"] for entry in payload["fields"]}
    assert len(payload["fields"]) == 26
    assert counts["computer-science"] == 2
    assert counts["neuroscience"] == 1
    # A field nothing is published in is still listed, at zero: a vocabulary
    # that shrinks with the corpus makes a filter appear and disappear.
    assert counts["dentistry"] == 0
    labels = {entry["slug"]: entry["label"] for entry in payload["fields"]}
    assert labels["computer-science"] == "Computer Science"


def test_fields_reports_how_many_papers_no_field_can_reach(client, session):
    _paper(session, "Computing", day=1, topics=ARXIV_CS)
    _paper(session, "MeSH only", day=2, topics=MESH_ONLY)
    _paper(session, "No topics at all", day=3)
    session.commit()

    payload = client.get("/fields").json()

    assert payload["papers_without_field"] == 2


def test_field_counts_exclude_retracted_papers_like_the_feed_does(client, session):
    _paper(session, "Standing work", day=1, topics=ARXIV_CS)
    _paper(session, "Withdrawn work", day=2, topics=ARXIV_CS, retraction_status="retracted")
    session.commit()

    payload = client.get("/fields").json()

    counts = {entry["slug"]: entry["paper_count"] for entry in payload["fields"]}
    assert counts["computer-science"] == 1
    feed_total = client.get("/papers", params={"field": "computer-science"}).json()["page"]["total"]
    assert feed_total == 1
