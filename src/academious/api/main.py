"""FastAPI application.

Phase 1 exposes health and ingestion metrics only. Public browsing, search and
paper pages are Phase 2; nothing here anticipates them.
"""

from __future__ import annotations

from fastapi import FastAPI

from academious.api.routers import health
from academious.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="Academious",
    version="0.1.0",
    description="A discovery layer over global scientific literature (Phase 1: ingestion).",
)
app.include_router(health.router)
