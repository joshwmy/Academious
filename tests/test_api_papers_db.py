"""The public browse and detail endpoints.

These run against a real database because the contract they have to keep is a
SQL one: deterministic ordering across pages, filters applied before pagination,
and a projection that cannot widen when a column is added to `paper`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from academious.api.limits import limiter
from academious.api.main import app
from tests.factories import make_paper

pytestmark = pytest.mark.db


@pytest.fixture
def client(session):
    """A client with rate limiting off, so functional tests are not throttled."""
    limiter.reset()
    limiter.enabled = False
    try:
        yield TestClient(app)
    finally:
        limiter.enabled = True
        limiter.reset()


def _paper(session, title, *, day=1, **kwargs):
    return make_paper(
        session, title, published_date=date(2026, 1, day), abstract="An abstract.", **kwargs
    )


def test_an_empty_corpus_returns_an_empty_page_rather_than_an_error(client):
    payload = client.get("/papers").json()
    assert payload["results"] == []
    assert payload["page"]["total"] == 0
    assert payload["page"]["has_more"] is False


def test_papers_are_listed_newest_first(client, session):
    _paper(session, "Oldest", day=1)
    _paper(session, "Newest", day=3)
    _paper(session, "Middle", day=2)
    session.commit()

    titles = [row["title"] for row in client.get("/papers").json()["results"]]
    assert titles == ["Newest", "Middle", "Oldest"]


def test_a_postdated_paper_is_treated_as_arriving_today(session):
    """The feed sorts on availability, not on the date a paper claims.

    Journals postdate issues, so `published_date` alone put work that is not
    published yet above work that is - on 2026-09-03 the whole first page of the
    live site was dated 2027. `feed_date` is the earlier of the claimed date and
    the date the paper reached us.
    """
    paper = make_paper(session, "Postdated issue", published_date=date(2099, 1, 1))
    session.commit()
    session.refresh(paper)

    assert paper.published_date == date(2099, 1, 1)  # the claim is still recorded
    # UTC, not local: the column casts through an explicit UTC conversion
    # because a session-dependent cast cannot be used in a generated column.
    assert paper.feed_date == datetime.now(UTC).date()  # it ranks as arriving today


def test_genuinely_old_papers_stay_old(client, session):
    # feed_date takes the *earlier* of the two dates, so harvesting a
    # 19th-century article today must not present it as new.
    make_paper(session, "Victorian", published_date=date(1817, 3, 1), abstract="Text.")
    make_paper(session, "Recent", published_date=date.today(), abstract="Text.")
    session.commit()

    titles = [r["title"] for r in client.get("/papers").json()["results"]]

    assert titles == ["Recent", "Victorian"]


def test_a_postdated_paper_does_not_outrank_one_published_today(client, session):
    make_paper(session, "Postdated issue", published_date=date(2099, 1, 1), abstract="Text.")
    make_paper(session, "Yesterday", published_date=date.today(), abstract="Text.")
    make_paper(session, "Last year", published_date=date(2025, 1, 1), abstract="Text.")
    session.commit()

    titles = [r["title"] for r in client.get("/papers").json()["results"]]

    # The first two share a feed_date of today and tie on id; what must not
    # happen is the 2099 paper leading the feed for the next 73 years.
    assert titles[-1] == "Last year"
    assert set(titles[:2]) == {"Postdated issue", "Yesterday"}


def test_a_paper_with_no_date_sorts_last_rather_than_first(client, session):
    # The rows whose implausible dates were cleared must not be promoted to
    # "newest" by having been repaired.
    make_paper(session, "Dated", published_date=date.today(), abstract="Text.")
    make_paper(session, "No date", abstract="Text.")
    session.commit()

    titles = [r["title"] for r in client.get("/papers").json()["results"]]

    assert titles == ["Dated", "No date"]


def test_ordering_is_total_so_pages_neither_repeat_nor_skip(client, session):
    """Same-day papers must still have one defined order.

    `published_date` alone is not a total order and the corpus holds many papers
    per day, so PostgreSQL may return ties in any order it likes - which makes
    page two overlap page one. The id breaks the tie.
    """
    for index in range(10):
        _paper(session, f"Same day {index}", day=5)
    session.commit()

    first = [r["id"] for r in client.get("/papers?limit=5&offset=0").json()["results"]]
    second = [r["id"] for r in client.get("/papers?limit=5&offset=5").json()["results"]]

    assert len(first) == len(second) == 5
    assert set(first).isdisjoint(second)
    assert first == [r["id"] for r in client.get("/papers?limit=5&offset=0").json()["results"]]


def test_pagination_reports_the_total_that_matched_not_the_page_size(client, session):
    for index in range(7):
        _paper(session, f"Paper {index}", day=index + 1)
    session.commit()

    page = client.get("/papers?limit=3&offset=3").json()["page"]
    assert page == {"limit": 3, "offset": 3, "total": 7, "returned": 3, "has_more": True}

    last = client.get("/papers?limit=3&offset=6").json()["page"]
    assert last["returned"] == 1
    assert last["has_more"] is False


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=-1", "limit=101", "limit=1000000", "offset=-1", "limit=abc", "offset=1e9"],
)
def test_pathological_pagination_is_rejected_rather_than_clamped(client, query):
    """A clamped page silently answers a question nobody asked.

    A client that requested 1,000,000 and received 100 cannot tell that from a
    short final page, so it never learns its request was wrong.
    """
    response = client.get(f"/papers?{query}")
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}


def test_filters_apply_before_pagination(client, session):
    _paper(session, "A preprint", is_preprint=True)
    _paper(session, "A journal article", is_preprint=False)
    session.commit()

    payload = client.get("/papers?preprints=only_preprints").json()
    assert payload["page"]["total"] == 1
    assert payload["results"][0]["title"] == "A preprint"

    excluded = client.get("/papers?preprints=exclude_preprints").json()
    assert [r["title"] for r in excluded["results"]] == ["A journal article"]


def test_peer_reviewed_and_open_access_filters_are_backed_by_real_columns(client, session):
    _paper(session, "Open and reviewed", is_peer_reviewed=True, oa_status="gold")
    _paper(session, "Closed", is_peer_reviewed=False, oa_status="closed")
    session.commit()

    assert client.get("/papers?peer_reviewed=true").json()["page"]["total"] == 1
    assert client.get("/papers?open_access=true").json()["page"]["total"] == 1


def test_an_unsupported_filter_value_is_rejected(client):
    assert client.get("/papers?preprints=whatever").status_code == 422


def test_a_summary_carries_what_a_paper_card_needs(client, session):
    paper = _paper(session, "A titled paper", doi="10.1234/abc")
    paper.authors = [{"name": "Ada Lovelace", "position": 0, "orcid": None, "affiliations": []}]
    paper.topics = [{"id": "ml", "label": "Machine learning", "scheme": "arxiv"}]
    session.commit()

    row = client.get("/papers").json()["results"][0]
    assert row["title"] == "A titled paper"
    assert row["doi"] == "10.1234/abc"
    assert row["authors"] == [
        {"name": "Ada Lovelace", "position": 0, "orcid": None, "affiliations": []}
    ]
    assert row["topics"][0]["label"] == "Machine learning"
    assert row["abstract_preview"] == "An abstract."


def test_a_known_paper_is_returned_in_full(client, session):
    paper = _paper(session, "Detailed paper", doi="10.5555/xyz")
    paper.abstract = "The full abstract, which the detail endpoint returns whole."
    session.commit()

    payload = client.get(f"/papers/{paper.id}").json()
    assert payload["id"] == str(paper.id)
    assert payload["abstract"] == "The full abstract, which the detail endpoint returns whole."
    assert payload["open_access"]["status"] == "closed"
    assert payload["open_access"]["is_open"] is False


def test_an_unknown_paper_is_a_404_with_a_stable_body(client):
    response = client.get(f"/papers/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Paper not found"}


def test_a_malformed_paper_id_is_a_422_not_a_500(client):
    response = client.get("/papers/not-a-uuid")
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}


def test_a_paper_id_that_looks_like_sql_is_rejected_as_an_id(client, session):
    _paper(session, "Untouched")
    session.commit()

    response = client.get("/papers/'; DROP TABLE paper; --")
    assert response.status_code == 422
    # The corpus is intact, because the value never reached SQL as anything but
    # a failed UUID parse.
    assert client.get("/papers").json()["page"]["total"] == 1
