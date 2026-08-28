"""Operational tables: ingestion runs (metrics) and the job queue."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academious.db.base import Base, uuid_pk


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IngestionRun(Base):
    """One harvest of one source. This table is the ingestion metrics store."""

    __tablename__ = "ingestion_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RunStatus.RUNNING.value
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cursor_start: Mapped[str | None] = mapped_column(Text)
    cursor_end: Mapped[str | None] = mapped_column(Text)

    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    papers_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    papers_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    papers_merged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relations_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oa_locations_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_ingestion_run_source_started", "source_key", "started_at"),)

    def __repr__(self) -> str:
        return f"<IngestionRun {self.source_key} {self.status} fetched={self.records_fetched}>"


class SourceCursor(Base):
    """Where each source got to, so the next run is incremental and idempotent."""

    __tablename__ = "source_cursor"

    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Job(Base):
    """Postgres-backed work queue, drained with SELECT ... FOR UPDATE SKIP LOCKED.

    Deliberately not Celery: at roughly 30k jobs/day Postgres handles this
    trivially, and it keeps Redis and a broker out of the deployment (ADR 0002).
    """

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dedup_key: Mapped[str | None] = mapped_column(String(255), unique=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=JobStatus.PENDING.value
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_job_claim", "status", "priority", "run_after"),
    )
