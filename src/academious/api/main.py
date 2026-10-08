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
from academious.api.middleware import CookieOriginMiddleware, SecurityHeadersMiddleware
from academious.api.routers import account, health, papers, profiles, search
from academious.auth import UserCreate, UserRead, UserUpdate, auth_backend, fastapi_users
from academious.core.config import get_settings
from academious.core.logging import configure_logging

configure_logging()

DESCRIPTION = """
A discovery layer over global scientific literature.

Public, unauthenticated, read-only. Browse the corpus with `/papers`, read one
paper with `/papers/{id}`, and search by research interest with `/search`.

Readers may also create a consented account to sync a research profile, saved
papers and explicit recommendation feedback. Account state is private and is
served only through a revocable, HTTP-only session cookie.

Search runs the retrieval stack measured in Phase 2. The method is server
configuration rather than a request parameter, and results carry a rank rather
than a score, because the underlying methods score in units that are not
comparable with one another.
""".strip()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.env == "production":
        if settings.auth_secret == "development-only-change-me":
            raise RuntimeError("ACADEMIOUS_AUTH_SECRET must be set in production")
        if not settings.auth_cookie_secure:
            raise RuntimeError("ACADEMIOUS_AUTH_COOKIE_SECURE must be true in production")
        if not settings.smtp_host or not settings.smtp_from:
            raise RuntimeError("SMTP must be configured for verification and password reset")

    app = FastAPI(
        title="Academious",
        version="0.2.0",
        description=DESCRIPTION,
        openapi_tags=[
            {"name": "papers", "description": "Browse and read papers."},
            {"name": "search", "description": "Rank papers against a research interest."},
            {"name": "auth", "description": "Account registration and secure sessions."},
            {"name": "account", "description": "Synced reader-owned recommendation state."},
            {
                "name": "profiles",
                "description": (
                    "Build a research profile and preview the feed it produces. Stateless: "
                    "nothing is stored and no account is involved."
                ),
            },
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
    app.add_middleware(CookieOriginMiddleware)
    app.add_middleware(SlowAPIASGIMiddleware)

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            # Credentialed account writes are allowed only from explicit
            # origins; CookieOriginMiddleware independently checks unsafe
            # requests carrying the session cookie.
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Content-Type"],
            allow_credentials=True,
            max_age=600,
        )

    hosts = settings.allowed_host_list
    if hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    app.include_router(health.router)
    app.include_router(papers.router)
    app.include_router(search.router)
    app.include_router(profiles.router)
    app.include_router(
        fastapi_users.get_auth_router(auth_backend), prefix="/auth/session", tags=["auth"]
    )
    app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth")
    app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth")
    app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth")
    app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users")
    app.include_router(account.router)
    return app


app = create_app()
