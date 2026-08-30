"""FastAPI application.

Two routers with different audiences, mounted on one app but not on one
security posture:

* the **public read API** (`/papers`, `/search`) is unauthenticated, rate
  limited and safe to expose to the internet;
* the **operational API** (`/health`, `/metrics/*`) reports corpus size, job
  queue state, embedding coverage and which model profile is active. That is
  useful to an operator and useful to someone deciding whether this host is
  worth attacking. It is tagged `ops` and docs/security.md requires the reverse
  proxy to restrict it. Nothing here can enforce that, so nothing here claims to.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIASGIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from academious.api import errors
from academious.api.limits import limiter
from academious.api.middleware import SecurityHeadersMiddleware
from academious.api.routers import health, papers, search
from academious.core.config import get_settings
from academious.core.logging import configure_logging

configure_logging()

DESCRIPTION = """
A discovery layer over global scientific literature.

Public, unauthenticated, read-only. Browse the corpus with `/papers`, read one
paper with `/papers/{id}`, and search by research interest with `/search`.

Search runs the retrieval stack measured in Phase 2. The method is server
configuration rather than a request parameter, and results carry a rank rather
than a score, because the underlying methods score in units that are not
comparable with one another.
""".strip()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Academious",
        version="0.2.0",
        description=DESCRIPTION,
        openapi_tags=[
            {"name": "papers", "description": "Browse and read papers."},
            {"name": "search", "description": "Rank papers against a research interest."},
            {
                "name": "ops",
                "description": "Operational health and metrics. Restrict at the proxy.",
            },
        ],
    )

    app.state.limiter = limiter
    errors.install(app)

    # Order matters: the outermost middleware is added last. Host validation
    # should reject before anything else does work, and security headers should
    # wrap every response including error responses.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SlowAPIASGIMiddleware)

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            # Read-only API. A browser needs no other verb, and `allow_methods`
            # is not a place to be generous.
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["Accept", "Content-Type"],
            # No cookies, no Authorization: there is nothing to authenticate
            # with yet, and credentialed CORS plus a wide origin list is the
            # classic way to make a read API into a confused deputy later.
            allow_credentials=False,
            max_age=600,
        )

    hosts = settings.allowed_host_list
    if hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    app.include_router(health.router)
    app.include_router(papers.router)
    app.include_router(search.router)
    return app


app = create_app()
