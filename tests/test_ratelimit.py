"""Rate limits are contractual (arXiv 1 req/3s, NCBI bans by IP), so they are tested."""

from __future__ import annotations

from academious.core.ratelimit import SOURCE_LIMITS, RateLimit, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_bucket(limit: RateLimit) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    return TokenBucket(limit, sleep=clock.sleep, monotonic=clock.monotonic), clock


def test_burst_is_free_then_requests_are_spaced():
    bucket, clock = make_bucket(RateLimit(requests=1, per_seconds=3.0, burst=1))
    assert bucket.acquire() == 0.0
    waited = bucket.acquire()
    assert waited == 3.0
    assert clock.slept == [3.0]


def test_tokens_refill_over_time():
    bucket, clock = make_bucket(RateLimit(requests=2, per_seconds=1.0, burst=2))
    bucket.acquire()
    bucket.acquire()
    clock.now += 1.0
    assert bucket.acquire() == 0.0


def test_penalise_blocks_every_caller_not_just_the_one_that_got_429():
    bucket, clock = make_bucket(RateLimit(requests=10, per_seconds=1.0, burst=10))
    bucket.penalise(60.0)
    waited = bucket.acquire()
    assert waited > 0
    assert sum(clock.slept) >= 60.0


def test_arxiv_limit_matches_published_terms():
    limit = SOURCE_LIMITS["arxiv"]
    assert limit.rate_per_second <= 1 / 3
    assert limit.burst == 1


def test_unknown_source_gets_a_cautious_default():
    from academious.core.ratelimit import bucket_for, reset_buckets

    reset_buckets()
    bucket = bucket_for("some-new-source")
    assert bucket is bucket_for("some-new-source")
