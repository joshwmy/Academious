"""Response headers this application is responsible for.

Which layer owns which control matters more than the list itself, so it is
stated here and in docs/security.md rather than left implicit:

* **This application** owns headers that describe how *its own* responses must
  be treated - MIME sniffing, referrer leakage, caching, and a policy that says
  a JSON API renders nothing.
* **The reverse proxy** owns transport. `Strict-Transport-Security` is a claim
  about TLS, and an application that cannot see whether TLS terminated in front
  of it cannot honestly make that claim - so it is off unless deployment says
  FastAPI is the edge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from academious.core.config import get_settings

#: A JSON API loads nothing and frames nothing. If a response is ever coaxed
#: into being rendered as HTML, this makes it inert.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    """Adds the response headers the API layer owns."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for key, value in _headers().items():
                    headers.append((key.encode("latin-1"), value.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "Permissions-Policy": PERMISSIONS_POLICY,
        # Public, unauthenticated, and cheap to re-fetch. Short and shared
        # rather than private: nothing here varies per caller.
        "Cache-Control": "public, max-age=60",
    }
    if settings.security_hsts_enabled:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


async def noop(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    return await call_next(request)
