"""Third-party loggers must not be allowed to print credentials.

`httpx` logs every request at INFO as `HTTP Request: GET <full url>`, and the
OpenAlex client passes its key as a query parameter, so an INFO root logger
publishes the credential to stdout - and from there into the container log,
wherever that is shipped. This is the only path by which the key can escape:
nothing in `academious` logs a URL with its query string attached.

These assert the levels `configure_logging` sets explicitly, rather than what
`isEnabledFor` reports. Under pytest the root logger is WARNING regardless, so
an inherited-level assertion passes whether or not the fix is present.
"""

from __future__ import annotations

import logging

import academious.core.logging as app_logging


def _reconfigure() -> None:
    app_logging._configured = False
    app_logging.configure_logging()


def test_httpx_request_logging_is_pinned_below_info() -> None:
    _reconfigure()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_application_loggers_are_left_to_inherit() -> None:
    # Silencing httpx must not turn into clamping everything: application
    # loggers keep NOTSET so ACADEMIOUS_LOG_LEVEL still governs them.
    _reconfigure()

    assert logging.getLogger("academious.ingest").level == logging.NOTSET
