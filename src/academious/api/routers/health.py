"""Health and ingestion-metrics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from academious.core.config import get_settings
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


@router.get("/metrics/embeddings")
def embedding_metrics() -> dict[str, Any]:
    """Coverage and queue state for the embedding pipeline.

    Deliberately reports `pending` per configured profile rather than a single
    global number: a corpus can be fully embedded under one model_key and
    entirely unembedded under another, and treating that as one figure would
    hide a half-finished migration.
    """
    from sqlalchemy import case

    from academious.db.models.embedding import PaperEmbedding
    from academious.db.models.ops import Job
    from academious.embeddings import service as embedding_service
    from academious.embeddings.jobs import JOB_KIND

    settings = get_settings()
    with session_scope() as session:
        papers = session.execute(select(func.count()).select_from(Paper)).scalar_one()

        by_model = session.execute(
            select(
                PaperEmbedding.model_key,
                func.count().label("vectors"),
                func.sum(case((PaperEmbedding.truncated, 1), else_=0)).label("truncated"),
                func.sum(
                    case((PaperEmbedding.input_strategy == "title_only", 1), else_=0)
                ).label("title_only"),
            ).group_by(PaperEmbedding.model_key)
        ).all()

        jobs = session.execute(
            select(Job.status, func.count())
            .where(Job.kind == JOB_KIND)
            .group_by(Job.status)
        ).all()

        models = [
            {
                "model_key": row.model_key,
                "vectors": row.vectors,
                "coverage": round(row.vectors / papers, 4) if papers else 0.0,
                "title_only": int(row.title_only or 0),
                "truncated": int(row.truncated or 0),
                "pending": embedding_service.count_pending(session, row.model_key),
            }
            for row in by_model
        ]
        active = settings.embedding_profile
        if all(entry["model_key"] != active for entry in models):
            models.append(
                {
                    "model_key": active,
                    "vectors": 0,
                    "coverage": 0.0,
                    "title_only": 0,
                    "truncated": 0,
                    "pending": embedding_service.count_pending(session, active),
                }
            )

        return {
            "papers": papers,
            "active_profile": active,
            "models": models,
            "jobs": {status: count for status, count in jobs},
        }
