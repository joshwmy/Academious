"""HTTP access to scholarly sources: identified, rate-limited, retried.

Every outbound request goes through `SourceHttpClient`. It enforces the source's
token bucket before the request, retries transient failures with exponential
backoff and jitter, honours Retry-After on 429, and raises the error hierarchy in
core.errors so callers can distinguish 'try later' from 'never going to work'.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from academious.core.config import Settings, get_settings
from academious.core.errors import (
    PermanentSourceError,
    RateLimitedError,
    TransientSourceError,
)
from academious.core.logging import get_logger
from academious.core.ratelimit import TokenBucket, bucket_for

log = get_logger(__name__)

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class SourceHttpClient:
    """A client bound to one source key, so limits and logs are attributable."""

    def __init__(
        self,
        source: str,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        bucket: TokenBucket | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self._settings = settings or get_settings()
        self._bucket = bucket if bucket is not None else bucket_for(source)
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self._settings.user_agent},
        )

    def __enter__(self) -> SourceHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _backoff(self, attempt: int) -> float:
        # Full jitter: avoids a thundering herd when several sources recover at once.
        return random.uniform(0.0, min(30.0, 2.0**attempt))

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform a request, retrying transient failures. Raises SourceError."""
        attempts = self._settings.http_max_attempts
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            waited = self._bucket.acquire()
            if waited > 0:
                log.debug("ratelimit.waited", source=self.source, seconds=round(waited, 3))
            try:
                response = self._client.request(method, url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = TransientSourceError(self.source, f"timeout: {exc}")
            except httpx.TransportError as exc:
                last_error = TransientSourceError(self.source, f"transport error: {exc}")
            else:
                if response.status_code < 400:
                    return response

                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if response.status_code == 429:
                    self._bucket.penalise(retry_after or 60.0)
                    last_error = RateLimitedError(
                        self.source, "429 rate limited", retry_after=retry_after
                    )
                elif response.status_code in _RETRYABLE_STATUS:
                    last_error = TransientSourceError(
                        self.source, f"HTTP {response.status_code}"
                    )
                else:
                    # 4xx other than 429: the request itself is wrong. Do not retry.
                    raise PermanentSourceError(
                        self.source,
                        f"HTTP {response.status_code} for {url}: {response.text[:200]}",
                    )

            if attempt < attempts:
                delay = getattr(last_error, "retry_after", None) or self._backoff(attempt)
                log.warning(
                    "source.retry",
                    source=self.source,
                    url=url,
                    attempt=attempt,
                    of=attempts,
                    sleep=round(delay, 2),
                    error=str(last_error),
                )
                self._sleep(delay)

        assert last_error is not None
        raise last_error

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.request("GET", url, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise PermanentSourceError(self.source, f"invalid JSON from {url}: {exc}") from exc

    def get_text(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        return self.request("GET", url, params=params).text
