"""The profile endpoints: contract, privacy posture, and what they refuse.

A small real corpus and the hashing backend, so the whole path runs - encode the
interests, scan pgvector, rank, re-rank, project. What is asserted is the HTTP
contract rather than the quality of the ordering: whether a reader gets a
profile they can read, a preview they can act on, an error they can fix, and
nothing stored about them anywhere.

`HashingBackend` is vocabulary overlap, not a semantic model, so nothing here
asserts that the ranking understood anything.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from academious.api.dependencies import get_retrieval_service
from academious.api.limits import limiter
from academious.api.main import app
from academious.embeddings import service as embedding_service
from academious.embeddings.hashing import HashingBackend
from academious.embeddings.registry import HASHING_AUTO
from academious.retrieval.service import RetrievalService
from tests.factories import make_paper

pytestmark = pytest.mark.db

PROFILE = HASHING_AUTO
RECENT = date(2026, 8, 20)

CS_TOPIC = {
    "scheme": "openalex",
    "id": "T-recsys",
    "label": "Recommender Systems",
    "field": "Computer Science",
}
BIO_TOPIC = {
    "scheme": "openalex",
    "id": "T-genomics",
    "label": "Genomics",
    "field": "Biochemistry, Genetics and Molecular Biology",
}


@pytest.fixture
def corpus(session):
    """Six papers: two subjects, one preprint, one older paper."""
    papers = {
        "recsys": make_paper(
            session,
            "Personalised ranking for research recommendation",
            abstract=(
                "We study personalised ranking and recommendation for scholarly "
                "search, combining retrieval with reader interest profiles."
            ),
            topics=[CS_TOPIC],
            published_date=RECENT,
        ),
        "retrieval": make_paper(
            session,
            "Dense retrieval for scientific search",
            abstract=(
                "Dense retrieval and reranking improve scholarly search over "
                "lexical baselines for research queries."
            ),
            topics=[CS_TOPIC],
            published_date=RECENT,
        ),
        "preprint": make_paper(
            session,
            "A preprint on recommendation and ranking",
            abstract="Preliminary results on personalised recommendation ranking.",
            topics=[CS_TOPIC],
            published_date=RECENT,
            is_preprint=True,
            is_peer_reviewed=False,
        ),
        "genomics": make_paper(
            session,
            "Variant calling for computational genomics",
            abstract=(
                "Computational genomics pipelines for variant calling across "
                "population sequencing cohorts."
            ),
            topics=[BIO_TOPIC],
            published_date=RECENT,
        ),
        "protein": make_paper(
            session,
            "Protein structure prediction from sequence",
            abstract="Protein structure prediction and folding from sequence data.",
            topics=[BIO_TOPIC],
            published_date=RECENT,
        ),
        "old": make_paper(
            session,
            "Recommendation systems, a decade ago",
            abstract="An older survey of recommendation and ranking systems.",
            topics=[CS_TOPIC],
            published_date=date(2015, 1, 1),
        ),
    }
    session.flush()
    pending = embedding_service.select_pending_paper_ids(session, PROFILE.key, limit=100)
    embedding_service.embed_papers(session, pending, profile=PROFILE, backend=HashingBackend())
    session.commit()
    return papers


@pytest.fixture
def client(session, corpus):
    limiter.reset()
    limiter.enabled = False
    app.dependency_overrides[get_retrieval_service] = lambda: RetrievalService(
        backend=HashingBackend(), model_key=PROFILE.key
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        limiter.enabled = True
        limiter.reset()


def _draft(**overrides):
    body = {
        "fields": [],
        "interests": [
            {
                "text": "personalised ranking and recommendation for research",
                "importance": "core",
            }
        ],
        "example_papers": [],
        "negatives": [],
        "negative_papers": [],
        "blocked_topics": [],
        "discovery": {
            "freshness": "balanced",
            "exploration": "balanced",
            "publication": "include_preprints",
        },
    }
    body.update(overrides)
    return body


def _preview(client, **overrides):
    response = client.post("/profiles/preview", json={"draft": _draft(**overrides), "limit": 10})
    assert response.status_code == 200, response.text
    return response.json()


# --- the vocabulary endpoint --------------------------------------------------


def test_options_names_every_level_a_client_could_send(client):
    body = client.get("/profiles/options").json()

    assert {option["value"] for option in body["importance"]} == {
        "core",
        "interested",
        "occasional",
    }
    assert {option["value"] for option in body["publication"]} == {
        "include_preprints",
        "prefer_peer_reviewed",
        "peer_reviewed_only",
    }
    assert body["limits"]["total_interests"] >= 1
    assert all(option["label"] for option in body["freshness"])


# --- the happy path -----------------------------------------------------------


def test_a_profile_is_built_and_previewed_in_one_round_trip(client):
    body = _preview(client)

    assert body["profile"]["interests"], "the profile has interests"
    assert body["preview"], "and the reader can see what it produces"
    assert body["summary"]["sections"], "and read it back in words"


def test_the_preview_carries_enough_to_judge_a_paper(client):
    item = _preview(client)["preview"][0]

    assert item["paper"]["title"]
    assert item["rank"] == 1
    assert item["reasons"], "a recommendation with no reason costs more than it saves"


def test_the_response_carries_a_schema_version(client):
    body = _preview(client)

    assert body["schema_version"] == body["profile"]["schema_version"]
    assert isinstance(body["schema_version"], int)


def test_the_normalised_draft_comes_back_for_the_client_to_keep(client):
    body = _preview(
        client,
        interests=[
            {"text": "personalised ranking and recommendation", "importance": "core"},
            {"text": "Personalised-Ranking  and  Recommendation", "importance": "occasional"},
        ],
    )

    assert len(body["draft"]["interests"]) == 1, "the duplicate was merged"
    assert body["draft"]["interests"][0]["importance"] == "core"
    assert any(issue["code"] == "duplicate_interest" for issue in body["issues"])


def test_the_returned_draft_can_be_posted_straight_back(client):
    """Round-tripping is what makes the client, not the server, hold the state."""
    first = _preview(client)
    again = client.post("/profiles/preview", json={"draft": first["draft"], "limit": 10})

    assert again.status_code == 200
    assert again.json()["draft"] == first["draft"]


# --- what a reader must never be shown ----------------------------------------


def test_no_score_cosine_or_weight_reaches_the_response(client):
    """Diagnostics stop at this boundary; a rank and a reason cross it."""
    rendered = str(_preview(client))

    for leaked in ("score", "cosine", "semantic_affinity", "contributions", "weight"):
        assert leaked not in rendered, f"{leaked!r} leaked into the response"


def test_an_interest_level_is_reported_in_words(client):
    interests = _preview(client)["profile"]["interests"]

    assert interests[0]["level"] == "Core interest"


# --- validation ---------------------------------------------------------------


def test_an_empty_draft_is_refused_with_a_reason(client):
    response = client.post("/profiles/preview", json={"draft": _draft(interests=[]), "limit": 10})

    assert response.status_code == 422
    assert "at least one" in response.json()["detail"]


def test_every_problem_is_reported_in_one_response(client):
    response = client.post(
        "/profiles/preview",
        json={"draft": _draft(fields=["astrology"], interests=[{"text": "RAG"}]), "limit": 10},
    )
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert "astrology" in detail
    assert "RAG" in detail


def test_an_absurd_number_of_interests_is_refused_by_the_parser(client):
    """The bound, as distinct from the message: this must not reach a Python loop."""
    response = client.post(
        "/profiles/preview",
        json={"draft": _draft(interests=[{"text": f"interest number {n}"} for n in range(500)])},
    )

    assert response.status_code == 422


def test_an_unknown_field_in_the_draft_names_the_slug(client):
    response = client.post(
        "/profiles/preview", json={"draft": _draft(fields=["not-a-field"]), "limit": 10}
    )

    assert response.status_code == 422
    assert "not-a-field" in response.json()["detail"]


def test_a_paper_that_does_not_exist_is_a_warning_not_a_failure(client):
    body = _preview(client, example_papers=[{"paper_id": "00000000-0000-4000-8000-000000000000"}])

    assert any(issue["code"] == "unknown_example_paper" for issue in body["issues"])
    assert body["preview"], "the rest of the profile still works"


# --- the choices actually reach the corpus ------------------------------------


def test_peer_reviewed_only_removes_preprints_from_the_preview(client, corpus):
    body = _preview(
        client,
        discovery={
            "freshness": "balanced",
            "exploration": "balanced",
            "publication": "peer_reviewed_only",
        },
    )
    shown = {item["paper"]["id"] for item in body["preview"]}

    assert body["profile"]["peer_reviewed_only"] is True
    assert str(corpus["preprint"].id) not in shown


def test_a_blocked_topic_never_appears(client, corpus):
    body = _preview(
        client,
        blocked_topics=["T-genomics"],
        fields=["biochemistry-genetics-and-molecular-biology"],
    )
    shown = {item["paper"]["id"] for item in body["preview"]}

    assert str(corpus["genomics"].id) not in shown
    assert str(corpus["protein"].id) not in shown


def test_an_example_paper_is_accepted_and_named(client, corpus):
    body = _preview(
        client, example_papers=[{"paper_id": str(corpus["genomics"].id), "importance": "core"}]
    )
    papers = [i for i in body["profile"]["interests"] if i["kind"] == "paper"]

    assert len(papers) == 1
    assert papers[0]["label"] == "Variant calling for computational genomics"
    assert str(corpus["genomics"].id) in papers[0]["provenance"]


def test_a_reader_who_only_picked_a_broad_area_still_gets_a_preview(client):
    """The cold start this phase exists to make work."""
    body = _preview(client, fields=["computer-science"], interests=[])

    assert body["preview"], "ticking one box has to produce something"
    assert body["profile"]["interests"][0]["kind"] == "field"


# --- refinement ---------------------------------------------------------------


def test_refining_changes_the_draft_and_says_what_it_did(client):
    first = _preview(client)
    target = first["preview"][0]

    response = client.post(
        "/profiles/refine",
        json={
            "draft": first["draft"],
            "refinements": [
                {
                    "action": "more_like_this",
                    "paper_id": target["paper"]["id"],
                    "interest_key": target["matched_interest_key"],
                }
            ],
            "limit": 10,
        },
    )
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["changes"], "a correction that says nothing cannot be trusted"
    assert len(body["draft"]["example_papers"]) == 1
    assert body["draft"]["example_papers"][0]["horizon"] == "short"


def test_not_interested_records_a_dislike_and_lowers_the_interest(client):
    first = _preview(client)
    target = first["preview"][0]

    body = client.post(
        "/profiles/refine",
        json={
            "draft": first["draft"],
            "refinements": [
                {
                    "action": "not_interested",
                    "paper_id": target["paper"]["id"],
                    "interest_key": target["matched_interest_key"],
                }
            ],
            "limit": 10,
        },
    ).json()

    assert body["draft"]["negative_papers"][0]["strength"] == "avoid"
    assert body["draft"]["interests"][0]["importance"] == "interested"


def test_a_refinement_needs_at_least_one_action(client):
    first = _preview(client)
    response = client.post("/profiles/refine", json={"draft": first["draft"], "refinements": []})

    assert response.status_code == 422


# --- nothing is stored, and nothing else changed ------------------------------


def test_a_preview_writes_nothing_to_the_database(client, session):
    """No accounts, and no anonymous profile quietly accumulating either."""
    from sqlalchemy import func, select

    from academious.db.models.paper import Paper

    before = session.execute(select(func.count()).select_from(Paper)).scalar_one()
    _preview(client)
    session.expire_all()
    after = session.execute(select(func.count()).select_from(Paper)).scalar_one()

    assert before == after


def test_two_identical_requests_are_independent(client):
    """A server holding anonymous state between requests would diverge here."""
    first = _preview(client)
    second = _preview(client)

    assert first["draft"] == second["draft"]
    assert [i["paper"]["id"] for i in first["preview"]] == [
        i["paper"]["id"] for i in second["preview"]
    ]


def test_the_papers_endpoint_is_unchanged(client):
    """`/papers` is still newest-first for everyone, and knows nothing about profiles."""
    body = client.get("/papers", params={"limit": 5}).json()

    assert "page" in body and "results" in body
    assert all("reasons" not in paper for paper in body["results"])


def test_search_is_unchanged(client):
    body = client.get("/search", params={"q": "recommendation ranking", "limit": 5}).json()

    assert set(body) == {"query", "count", "limit", "results"}


def test_the_profile_endpoints_appear_in_the_openapi_document(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/profiles/preview" in paths
    assert "/profiles/refine" in paths
    assert "/profiles/options" in paths
