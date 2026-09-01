"""Cursor and resumption-token handling for every paginated source."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from academious.core.config import Settings
from academious.core.http import SourceHttpClient
from academious.core.ratelimit import RateLimit, TokenBucket
from academious.sources.arxiv.client import ArxivClient
from academious.sources.biorxiv.client import BiorxivClient
from academious.sources.europepmc.client import EuropePmcClient, format_cursor
from academious.sources.openalex.client import OpenAlexClient
from tests.conftest import load_text


def fast_http(source: str, settings: Settings) -> SourceHttpClient:
    bucket = TokenBucket(
        RateLimit(requests=1e6, per_seconds=1.0, burst=1000),
        sleep=lambda _s: None,
        monotonic=lambda: 0.0,
    )
    return SourceHttpClient(source, settings=settings, bucket=bucket, sleep=lambda _s: None)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        contact_email="t@example.com",
        openalex_filters="primary_topic.domain.id:1",
        arxiv_sets="cs",
        biorxiv_servers="biorxiv",
        europepmc_queries="OPEN_ACCESS:Y",
        http_max_attempts=2,
    )


@respx.mock
def test_openalex_follows_cursor_then_stops(settings):
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [{"id": "https://openalex.org/W1", "title": "One"}],
                    "meta": {"next_cursor": "cursor-2", "count": 2},
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [{"id": "https://openalex.org/W2", "title": "Two"}],
                    "meta": {"next_cursor": None, "count": 2},
                },
            ),
        ]
    )
    client = OpenAlexClient(settings=settings, http=fast_http("openalex", settings))
    pages = list(client.harvest(None, None))
    assert [record.source_id for page in pages for record in page.records] == [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
    ]


@respx.mock
def test_openalex_stops_when_cursor_does_not_advance(settings):
    """A non-advancing cursor would otherwise loop until the page cap."""
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "https://openalex.org/W1"}],
                "meta": {"next_cursor": "*", "count": 1},
            },
        )
    )
    client = OpenAlexClient(settings=settings, http=fast_http("openalex", settings))
    pages = list(client.harvest_filter("f:1", None, "*"))
    assert len(pages) == 1


@respx.mock
def test_openalex_sends_api_key_when_configured(settings):
    keyed = settings.model_copy(update={"openalex_api_key": "test-key-123"})
    route = respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json={"results": [], "meta": {}})
    )
    client = OpenAlexClient(settings=keyed, http=fast_http("openalex", keyed))
    list(client.harvest(None, None))
    assert "api_key=test-key-123" in str(route.calls[0].request.url)


@respx.mock
def test_arxiv_follows_resumption_token_until_absent(settings):
    respx.get(url__startswith="https://export.arxiv.org/oai2").mock(
        side_effect=[
            httpx.Response(200, text=load_text("arxiv", "listrecords_page1.xml")),
            httpx.Response(200, text=load_text("arxiv", "listrecords_page2_final.xml")),
        ]
    )
    client = ArxivClient(settings=settings, http=fast_http("arxiv", settings))
    pages = list(client.harvest(None, None))
    assert len(pages) == 2
    assert pages[0].next_cursor is not None
    assert pages[1].next_cursor is None
    assert sum(len(page.records) for page in pages) == 4


@respx.mock
def test_arxiv_resumption_token_is_sent_alone(settings):
    """OAI-PMH forbids combining resumptionToken with any other argument."""
    route = respx.get(url__startswith="https://export.arxiv.org/oai2").mock(
        return_value=httpx.Response(200, text=load_text("arxiv", "listrecords_page2_final.xml"))
    )
    client = ArxivClient(settings=settings, http=fast_http("arxiv", settings))
    list(client.harvest_set("cs", None, "token-abc"))
    query = dict(route.calls[0].request.url.params)
    assert query == {"verb": "ListRecords", "resumptionToken": "token-abc"}


@respx.mock
def test_arxiv_no_records_match_is_not_an_error(settings):
    respx.get(url__startswith="https://export.arxiv.org/oai2").mock(
        return_value=httpx.Response(
            200,
            text='<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            '<error code="noRecordsMatch">nothing</error></OAI-PMH>',
        )
    )
    client = ArxivClient(settings=settings, http=fast_http("arxiv", settings))
    pages = list(client.harvest_set("cs", None, None))
    assert pages and pages[0].records == []


@respx.mock
def test_biorxiv_paginates_until_total_reached(settings):
    respx.get(url__startswith="https://api.biorxiv.org/details").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "messages": [{"status": "ok", "count": 2, "total": "3"}],
                    "collection": [
                        {"doi": "10.1101/a", "version": "1", "title": "A"},
                        {"doi": "10.1101/b", "version": "1", "title": "B"},
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "messages": [{"status": "ok", "count": 1, "total": "3"}],
                    "collection": [{"doi": "10.1101/c", "version": "2", "title": "C"}],
                },
            ),
        ]
    )
    client = BiorxivClient(settings=settings, http=fast_http("biorxiv", settings))
    records = [r for page in client.harvest(None, None) for r in page.records]
    assert [r.source_id for r in records] == ["10.1101/av1", "10.1101/bv1", "10.1101/cv2"]


@respx.mock
def test_biorxiv_publication_links_yield_doi_pairs(settings):
    respx.get(url__startswith="https://api.biorxiv.org/pubs").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [{"status": "ok", "count": 1, "total": "1"}],
                "collection": [
                    {
                        "preprint_doi": "10.1101/2022.09.11.507474",
                        "published_doi": "10.1038/s41564-023-01548-y",
                    }
                ],
            },
        )
    )
    client = BiorxivClient(settings=settings, http=fast_http("biorxiv", settings))
    links = list(client.publication_links("biorxiv", None))
    assert links[0][0] == "10.1101/2022.09.11.507474"
    assert links[0][1] == "10.1038/s41564-023-01548-y"


def epmc_page(mark: str | None, results: list[dict[str, str]]) -> httpx.Response:
    body: dict[str, object] = {"hitCount": 2, "resultList": {"result": results}}
    if mark is not None:
        body["nextCursorMark"] = mark
    return httpx.Response(200, json=body)


@respx.mock
def test_europepmc_follows_cursor_mark_then_stops(settings):
    respx.get(url__startswith="https://www.ebi.ac.uk/europepmc").mock(
        side_effect=[
            epmc_page("mark-2", [{"id": "34265844", "source": "MED"}]),
            epmc_page("mark-3", [{"id": "PPR1297577", "source": "PPR"}]),
            epmc_page("mark-3", []),
        ]
    )
    client = EuropePmcClient(settings=settings, http=fast_http("europepmc", settings))
    pages = list(client.harvest(None, None))
    assert [record.source_id for page in pages for record in page.records] == [
        "MED:34265844",
        "PPR:PPR1297577",
    ]


@respx.mock
def test_europepmc_stops_when_the_mark_does_not_advance(settings):
    """A non-advancing mark would otherwise loop until the page cap."""
    respx.get(url__startswith="https://www.ebi.ac.uk/europepmc").mock(
        return_value=epmc_page("mark-1", [{"id": "1", "source": "MED"}])
    )
    client = EuropePmcClient(settings=settings, http=fast_http("europepmc", settings))
    pages = list(
        client.harvest_query(
            "OPEN_ACCESS:Y",
            None,
            format_cursor("OPEN_ACCESS:Y", date(2026, 8, 1), date(2026, 8, 8), "mark-1"),
        )
    )
    assert len(pages) == 1


@respx.mock
def test_europepmc_resumes_the_window_the_cursor_belongs_to(settings):
    """A mark is only meaningful against the query that minted it."""
    route = respx.get(url__startswith="https://www.ebi.ac.uk/europepmc").mock(
        return_value=epmc_page(None, [])
    )
    client = EuropePmcClient(settings=settings, http=fast_http("europepmc", settings))
    cursor = format_cursor("OPEN_ACCESS:Y", date(2026, 8, 1), date(2026, 8, 8), "mark-7")
    list(client.harvest_query("OPEN_ACCESS:Y", date(2020, 1, 1), cursor))
    params = dict(route.calls[0].request.url.params)
    assert params["cursorMark"] == "mark-7"
    assert params["query"] == "(OPEN_ACCESS:Y) AND UPDATE_DATE:[2026-08-01 TO 2026-08-08]"


@respx.mock
def test_europepmc_exhausted_window_yields_a_cursor_that_will_not_resume(settings):
    respx.get(url__startswith="https://www.ebi.ac.uk/europepmc").mock(
        return_value=epmc_page(None, [{"id": "1", "source": "MED"}])
    )
    client = EuropePmcClient(settings=settings, http=fast_http("europepmc", settings))
    pages = list(client.harvest_query("OPEN_ACCESS:Y", date(2026, 8, 1), None))
    assert pages[-1].next_cursor is not None
    assert pages[-1].next_cursor.endswith("|")
