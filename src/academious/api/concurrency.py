"""A bounded gate in front of expensive retrieval.

Rate limiting caps how often one client may ask. It does not cap how many
requests are being served at once, and those are different failures: a hundred
clients each politely under their own limit can still put a hundred SPECTER2
query encodes on a four-core box simultaneously. One encode is ~160 ms of
largely CPU-bound work, so the machine does not degrade gracefully under that -
every request slows down together until they all time out.

So the model path runs behind a counting semaphore with a bounded wait. Past
that wait the honest answer is 503 with `Retry-After`, not a request that will
occupy a worker for a minute and then fail anyway.

`threading.BoundedSemaphore` rather than an asyncio primitive because the work
it guards is synchronous and CPU-bound - SQLAlchemy and torch - and runs in
Starlette's threadpool. An asyncio semaphore would guard the coroutine that
schedules the work rather than the work itself.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from academious.core.config import get_settings
from academious.core.logging import get_logger

log = get_logger(__name__)


class CapacityExceededError(RuntimeError):
    """Every slot was busy for the whole permitted wait."""


class ConcurrencyGate:
    def __init__(self, capacity: int, timeout: float) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self.timeout = timeout
        self._semaphore = threading.BoundedSemaphore(capacity)

    @contextmanager
    def acquire(self) -> Iterator[None]:
        """Hold a slot for the block, or raise `CapacityExceededError` waiting for one.

        The release is in `finally`, so a slot comes back whether the guarded
        call returns, raises, or is abandoned because the client disconnected -
        a leaked permit would shrink capacity permanently and silently.
        """
        if not self._semaphore.acquire(timeout=self.timeout):
            log.warning("search.capacity_exceeded", capacity=self.capacity)
            raise CapacityExceededError(
                f"no capacity within {self.timeout}s (limit {self.capacity})"
            )
        try:
            yield
        finally:
            self._semaphore.release()

    @property
    def available(self) -> int:
        """Free slots. For tests and diagnostics, not for flow control."""
        return self._semaphore._value  # noqa: SLF001


def build_gate() -> ConcurrencyGate:
    settings = get_settings()
    return ConcurrencyGate(
        capacity=settings.search_max_concurrency,
        timeout=settings.search_queue_timeout_seconds,
    )


search_gate = build_gate()
