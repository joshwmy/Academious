"""Health and ingestion-metrics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from academious.db.models.ops import IngestionRun
from academious.db.models.paper import Paper
from academious.db.session import session_scope

router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> dict[str, Any]:
    with session_scope() as session:
        papers = session.execute(select(func.count()).select_from(Paper)).scalar_one()
    return {"status": "ok", "papers": papers}


@router.get("/metrics/ingestion")
def ingestion_metrics(limit: int = 20) -> dict[str, Any]:
    """Most recent ingestion runs. This table is the ingestion metrics store."""
    with session_scope() as session:
        runs = session.execute(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        ).scalars().all()
        return {
            "runs": [
                {
                    "source": run.source_key,
                    "status": run.status,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "records_fetched": run.records_fetched,
                    "records_skipped": run.records_skipped,
                    "papers_created": run.papers_created,
                    "papers_updated": run.papers_updated,
                    "papers_merged": run.papers_merged,
                    "relations_created": run.relations_created,
                    "oa_locations_created": run.oa_locations_created,
                    "errors": run.errors,
                }
                for run in runs
            ]
        }
