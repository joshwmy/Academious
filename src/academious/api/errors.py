"""One place where an exception becomes a response.

The rule: a client learns *what* went wrong, never *where*. A traceback names
modules, file paths and library versions; a SQLAlchemy error quotes the
statement and often the schema; a torch error names the model directory. All of
those are reconnaissance, and all of them reach the client for free if an
unhandled exception is allowed to render itself.

So every unexpected exception becomes the same short 500, and the detail goes to
the log with the traceback attached.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from academious.api.concurrency import CapacityExceededError
from academious.core.logging import get_logger

log = get_logger(__name__)

#: Starlette renamed its 422 constant; the number is stable and unambiguous.
UNPROCESSABLE = 422

GENERIC_500 = "Internal server error"
BUSY_503 = "Search is temporarily at capacity. Please retry shortly."
RATE_LIMITED_429 = "Rate limit exceeded. Please slow down."


def _json(status_code: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _json(exc.status_code, detail, dict(exc.headers or {}))


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 that says which parameter was wrong without echoing the value back.

    Pydantic's default rendering includes `input`, which puts whatever the
    client sent into the response body. That is a reflection primitive for
    anything that later renders an error, and it is not information the caller
    lacks - they sent it.
    """
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "query")
        problems.append(f"{location or 'request'}: {error.get('msg', 'invalid')}")
    return _json(UNPROCESSABLE, "; ".join(problems) or "Invalid request")


async def capacity_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_503_SERVICE_UNAVAILABLE, BUSY_503, {"Retry-After": "5"})


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    retry_after = "60"
    if isinstance(exc, RateLimitExceeded):
        # slowapi knows the window; expose the wait, not the policy internals.
        retry_after = str(getattr(exc, "retry_after", None) or retry_after)
    return _json(
        status.HTTP_429_TOO_MANY_REQUESTS, RATE_LIMITED_429, {"Retry-After": retry_after}
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception(
        "api.unhandled_exception",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
    )
    return _json(status.HTTP_500_INTERNAL_SERVER_ERROR, GENERIC_500)


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(CapacityExceededError, capacity_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
