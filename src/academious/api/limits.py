"""Rate limiting, and deciding who a client is.

**Client identity.** The rate-limit key is the socket peer by default, because
that is the only address a client cannot choose. `X-Forwarded-For` is attacker
controlled unless every hop that appended to it is trusted: a public client can
send `X-Forwarded-For: 1.2.3.4` and, if that header is believed, get a fresh
budget on every request. It is therefore read only when `trusted_proxy_count`
says how many trusted proxies actually sit in front of the app, and then only
the entry those proxies could not have been lied to about - counting from the
right, because each proxy appends and only the rightmost entries are ours.

**Scope.** This limiter keeps its counters in this process. The approved
deployment (docs/deployment.md) is one FastAPI container behind Caddy on one
VPS, so a process-local limiter *is* the global limiter there. It stops being
one the moment a second worker or replica exists: two workers means two budgets
and an effective limit of twice the configured number. Moving to shared state is
a `storage_uri` on the limiter and nothing else, which is why this is written
against `slowapi` rather than hand-rolled.
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from academious.core.config import get_settings

#: Used when the peer address is genuinely unknown (ASGI transports without a
#: client, such as some test transports). One shared bucket is the safe
#: fallback: it can throttle unrelated callers together, but it cannot hand an
#: unidentified caller an unlimited budget.
UNKNOWN_CLIENT = "unknown"


def client_identity(request: Request) -> str:
    """The rate-limit key for this request."""
    settings = get_settings()
    trusted = settings.trusted_proxy_count

    if trusted > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
            if hops:
                # Each trusted proxy appended one entry. The client address is
                # the one immediately left of our own proxies; anything further
                # left was supplied by the caller and cannot be believed.
                index = max(0, len(hops) - trusted)
                return hops[index]

    # Deliberately not slowapi's `get_remote_address`, which substitutes
    # 127.0.0.1 when the transport has no peer - that quietly merges
    # unidentifiable callers into the same bucket as genuine localhost
    # traffic. A distinct key says which case this is.
    client = request.client
    return client.host if client and client.host else UNKNOWN_CLIENT


def read_limit() -> str:
    settings = get_settings()
    return f"{settings.rate_limit_read_requests}/{settings.rate_limit_read_window_seconds}second"


def search_limit() -> str:
    settings = get_settings()
    return (
        f"{settings.rate_limit_search_requests}/"
        f"{settings.rate_limit_search_window_seconds}second"
    )


def build_limiter() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=client_identity,
        enabled=settings.rate_limit_enabled,
        headers_enabled=True,
        # In-memory on purpose; see the module docstring.
        storage_uri="memory://",
    )


limiter = build_limiter()
