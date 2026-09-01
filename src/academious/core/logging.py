"""Structured logging. JSON in production, human-readable in a terminal."""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import Processor

from academious.core.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    # httpx logs every request at INFO as `HTTP Request: GET <full url>`, query
    # string included. OpenAlex takes its API key as a query parameter, so at
    # ACADEMIOUS_LOG_LEVEL=INFO that line publishes the credential into the
    # container log. Pinned rather than inherited: the point is that raising the
    # application's log level must not raise this one with it. WARNING and above
    # still comes through, because a transport warning is often the only
    # explanation for a stalled harvest.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]
