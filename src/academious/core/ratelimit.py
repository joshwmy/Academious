"""Per-source token-bucket rate limiting.

Rate limits here are contractual, not cosmetic. arXiv permits one request every
three seconds across all of a client's machines, and NCBI enforces its limits
with IP bans. A ban is an outage with no support ticket, so every outbound
scholarly request passes through a bucket keyed by source.

Buckets are process-local. That is correct for the single-worker deployment
approved in Phase 0; when a second worker process is added, this must move to a
shared store (Redis) or the workers must be partitioned by source.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Tolerance for float accumulation in the token count, and a floor on sleeps so
# a near-miss can never turn into a busy loop.
_EPSILON = 1e-9
_MIN_SLEEP = 1e-3


@dataclass(frozen=True)
class RateLimit:
    """`requests` permitted per `per_seconds`, with burst capacity `burst`."""

    requests: float
    per_seconds: float = 1.0
    burst: int = 1

    @property
    def rate_per_second(self) -> float:
        return self.requests / self.per_seconds


class TokenBucket:
    """Blocking token bucket. `acquire()` returns only when a token is available."""

    def __init__(self, limit: RateLimit, *, sleep=time.sleep, monotonic=time.monotonic) -> None:
        self._limit = limit
        self._capacity = float(max(limit.burst, 1))
        self._tokens = self._capacity
        self._updated = monotonic()
        self._lock = threading.Lock()
        self._sleep = sleep
        self._monotonic = monotonic

    def _refill_locked(self, now: float) -> None:
        # `_updated` may sit in the future while a penalty is in force; refilling
        # then would silently cancel the penalty, so it is left alone.
        if now < self._updated:
            return
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._limit.rate_per_second)

    def acquire(self) -> float:
        """Consume one token, sleeping if necessary. Returns seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = self._monotonic()
                if now < self._updated:
                    # Inside a penalty window: wait it out in one sleep.
                    delay = self._updated - now
                else:
                    self._refill_locked(now)
                    # Epsilon, not >= 1.0: accumulated float error otherwise
                    # leaves tokens at 0.999... forever and the loop busy-spins
                    # on microsecond sleeps.
                    if self._tokens >= 1.0 - _EPSILON:
                        self._tokens = max(0.0, self._tokens - 1.0)
                        return waited
                    delay = (1.0 - self._tokens) / self._limit.rate_per_second
            delay = max(delay, _MIN_SLEEP)
            self._sleep(delay)
            waited += delay

    def penalise(self, seconds: float) -> None:
        """Drain the bucket and push the next refill out by `seconds`.

        Called after a 429 so a Retry-After is honoured by every caller of this
        bucket, not only the request that received it.
        """
        with self._lock:
            now = self._monotonic()
            self._refill_locked(now)
            self._tokens = 0.0
            self._updated = now + max(0.0, seconds)


# Published limits, verified during Phase 0 research. Each is set at or below the
# documented ceiling; see docs/sources.md for the citation behind every number.
SOURCE_LIMITS: dict[str, RateLimit] = {
    # 100 req/s is the hard cap, but credits (10 per list call) bind first.
    "openalex": RateLimit(requests=5, per_seconds=1.0, burst=5),
    # Terms of use: no more than one request every three seconds, one connection.
    "arxiv": RateLimit(requests=1, per_seconds=3.0, burst=1),
    "biorxiv": RateLimit(requests=2, per_seconds=1.0, burst=2),
    # Polite pool: 3 req/s on list endpoints, 3 concurrent.
    "crossref": RateLimit(requests=3, per_seconds=1.0, burst=3),
    "retractionwatch": RateLimit(requests=1, per_seconds=2.0, burst=1),
    # With a registered API key. Without one the ceiling is 3/s.
    "pubmed": RateLimit(requests=8, per_seconds=1.0, burst=8),
    "unpaywall": RateLimit(requests=5, per_seconds=1.0, burst=5),
}

_buckets: dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()


def bucket_for(source: str) -> TokenBucket:
    """Process-wide bucket for a source key. Unknown sources get a cautious 1/s."""
    with _buckets_lock:
        existing = _buckets.get(source)
        if existing is None:
            limit = SOURCE_LIMITS.get(source, RateLimit(requests=1, per_seconds=1.0))
            existing = TokenBucket(limit)
            _buckets[source] = existing
        return existing


def reset_buckets() -> None:
    """Test hook. Never call from application code."""
    with _buckets_lock:
        _buckets.clear()
