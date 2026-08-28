"""Single source of 'now'. Injectable so tests are deterministic."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware current time. Never use datetime.now() directly."""
    return datetime.now(UTC)
