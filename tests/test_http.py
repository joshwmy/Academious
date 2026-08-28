"""HTTP behaviour: retries, Retry-After, and the transient/permanent split.

Surviving source failures and rate limits is a Phase 1 acceptance criterion, so
each failure mode is exercised explicitly. No real network is used.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from academious.core.config import Settings
from academious.core.errors import PermanentSourceError, RateLimitedError, TransientSourceError
from academious.core.http import SourceHttpClient
from academious.core.ratelimit import RateLimit, TokenBucket

URL = "https://example.test/works"


class NoWait:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def client() -> SourceHttpClient:
    clock = NoWait()
    settings = Settings(
        http_max_attempts=3, http_timeout_seconds=1.0, contact_email="t@example.com"
    )
    bucket = TokenBucket(
        RateLimit(requests=1000, per_seconds=1.0, burst=1000),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    instance = SourceHttpClient("test", settings=settings, bucket=bucket, sleep=clock.sleep)
    instance.test_clock = clock  # type: ignore[attr-defined]
    return instance


@respx.mock
def test_success_returns_payload(client):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    assert client.get_json(URL) == {"ok": True}


@respx.mock
def test_user_agent_identifies_us_with_a_contact_address(client):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    client.get_json(URL)
    agent = route.calls[0].request.headers["user-agent"]
    assert "Academious" in agent and "t@example.com" in agent


@respx.mock
def test_transient_5xx_is_retried_then_succeeds(client):
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"recovered": True}),
        ]
    )
    assert client.get_json(URL) == {"recovered": True}
    assert route.call_count == 2


@respx.mock
def test_retries_are_bounded_and_raise_transient(client):
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(TransientSourceError):
        client.get_json(URL)


@respx.mock
def test_429_honours_retry_after_and_penalises_the_bucket(client):
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    assert client.get_json(URL) == {"ok": 1}
    assert 7.0 in client.test_clock.slept


@respx.mock
def test_429_everywhere_raises_rate_limited(client):
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "1"}))
    with pytest.raises(RateLimitedError):
        client.get_json(URL)


@respx.mock
def test_404_is_permanent_and_not_retried(client):
    route = respx.get(URL).mock(return_value=httpx.Response(404, text="gone"))
    with pytest.raises(PermanentSourceError):
        client.get_json(URL)
    assert route.call_count == 1


@respx.mock
def test_timeouts_are_transient(client):
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(TransientSourceError):
        client.get_json(URL)


@respx.mock
def test_invalid_json_is_permanent(client):
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(PermanentSourceError):
        client.get_json(URL)
