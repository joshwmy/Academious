"""Venue, open-access locations, raw source records, retraction notices."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from academious.db.base import Base, TimestampMixin, uuid_pk


class HostType(StrEnum):
    PUBLISHER = "publisher"
    REPOSITORY = "repository"
    PREPRINT = "preprint"
    UNKNOWN = "unknown"


class OaVersion(StrEnum):
    PUBLISHED = "publishedVersion"
    ACCEPTED = "acceptedVersion"
    SUBMITTED = "submittedVersion"
    UNKNOWN = "unknown"


class Venue(Base, TimestampMixin):
    __tablename__ = "venue"

    id: Mapped[uuid.UUID] = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    issn_l: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)
    venue_type: Mapped[str | None] = mapped_column(String(32))
    is_oa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mean_citedness_2y: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        return f"<Venue {self.name!r}>"


class OaLocation(Base):
    """One discovered legal location for a paper. All are kept; one is 'best'."""

    __tablename__ = "oa_location"

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    host_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=HostType.UNKNOWN.value
    )
    version: Mapped[str] = mapped_column(
        String(24), nullable=False, default=OaVersion.UNKNOWN.value
    )
    licence: Mapped[str | None] = mapped_column(String(64))
    source_name: Mapped[str | None] = mapped_column(Text)
    discovered_via: Mapped[str] = mapped_column(String(32), nullable=False)
    is_best: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    paper: Mapped[Any] = relationship(
        "Paper", back_populates="oa_locations", foreign_keys=[paper_id]
    )

    __table_args__ = (
        UniqueConstraint("paper_id", "url", name="uq_oa_location_paper_url"),
    )


class SourceRecord(Base):
    """Immutable raw payload as received. Never edited; enables replay."""

    __tablename__ = "source_record"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper.id", ondelete="SET NULL"), index=True
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_run.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_key", "source_id", name="uq_source_record_source_id"),
        Index("ix_source_record_hash", "source_key", "content_hash"),
    )


class RetractionRecord(Base):
    """A Retraction Watch notice. One paper may have several (correction, EoC, retraction)."""

    __tablename__ = "retraction_record"

    id: Mapped[uuid.UUID] = uuid_pk()
    record_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    original_doi: Mapped[str | None] = mapped_column(String(255), index=True)
    original_pmid: Mapped[str | None] = mapped_column(String(32), index=True)
    notice_doi: Mapped[str | None] = mapped_column(String(255))
    notice_url: Mapped[str | None] = mapped_column(Text)
    nature: Mapped[str] = mapped_column(String(48), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    retraction_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(Text)
    journal: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
