"""The canonical Paper entity and its identifier/relation satellites."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from academious.db.base import Base, TimestampMixin, uuid_pk
from academious.db.ddl import FEED_DATE_EXPRESSION, SEARCH_TSV_EXPRESSION


class RetractionStatus(StrEnum):
    NONE = "none"
    CORRECTED = "corrected"
    CONCERN = "concern"
    RETRACTED = "retracted"


class FullTextStatus(StrEnum):
    NONE = "none"
    ABSTRACT_ONLY = "abstract_only"
    LINKED = "linked"
    STORED = "stored"


class RelationType(StrEnum):
    PREPRINT_OF = "preprint_of"
    VERSION_OF = "version_of"
    CORRECTS = "corrects"
    RETRACTS = "retracts"


class Paper(Base, TimestampMixin):
    __tablename__ = "paper"

    id: Mapped[uuid.UUID] = uuid_pk()

    canonical_doi: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_norm: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    abstract_source: Mapped[str | None] = mapped_column(String(32))

    # Authors are stored denormalised. Author disambiguation is a research problem
    # in its own right and OpenAlex already solves it upstream; a local Author
    # entity arrives only when followed-author features need one (see ADR 0003).
    authors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    first_author_surname: Mapped[str | None] = mapped_column(String(128), index=True)

    venue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("venue.id"), index=True)

    published_date: Mapped[date | None] = mapped_column(Date, index=True)
    first_seen_online: Mapped[date | None] = mapped_column(Date)
    published_year: Mapped[int | None] = mapped_column(Integer, index=True)

    is_preprint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_peer_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    work_type: Mapped[str | None] = mapped_column(String(48))
    language: Mapped[str | None] = mapped_column(String(16))

    topics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # Normalised subject fields, derived from `topics` by ingest.taxonomy so that
    # one filter reaches papers classified by four disagreeing source
    # vocabularies. Derived rather than authoritative: it is recomputed whenever
    # topics change, and re-derivable for the whole corpus by
    # scripts/backfill_fields.py after a mapping change.
    fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # Lexical retrieval index, maintained by PostgreSQL itself so it can never
    # drift from the row it describes. Field weights and the reason keywords
    # need a helper function are in academious/db/ddl.py.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_TSV_EXPRESSION, persisted=True), nullable=True
    )

    # What the feed orders by, maintained by PostgreSQL: the earlier of the
    # published date and the date the paper first reached us. Generated for the
    # same reason search_tsv is - it cannot drift from its row.
    feed_date: Mapped[date | None] = mapped_column(
        Date, Computed(FEED_DATE_EXPRESSION, persisted=True), nullable=True
    )

    citation_count: Mapped[int | None] = mapped_column(Integer)
    citation_count_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    oa_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    best_oa_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oa_location.id", ondelete="SET NULL", use_alter=True)
    )
    fulltext_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=FullTextStatus.NONE.value
    )
    fulltext_licence: Mapped[str | None] = mapped_column(String(64))

    retraction_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RetractionStatus.NONE.value, index=True
    )
    retraction_notice_url: Mapped[str | None] = mapped_column(Text)
    retraction_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quality_prior: Mapped[float | None] = mapped_column(Float)

    identifiers: Mapped[list[PaperIdentifier]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )
    oa_locations: Mapped[list[Any]] = relationship(
        "OaLocation",
        back_populates="paper",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="OaLocation.paper_id",
    )

    __table_args__ = (
        Index("ix_paper_title_norm_trgm", "title_norm", postgresql_using="gin",
              postgresql_ops={"title_norm": "gin_trgm_ops"}),
        Index("ix_paper_dedup_block", "first_author_surname", "published_year"),
        Index("ix_paper_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_paper_fields", "fields", postgresql_using="gin"),
        Index("ix_paper_feed_date", desc("feed_date").nullslast(), desc("id")),
    )

    def __repr__(self) -> str:
        return f"<Paper {self.id} doi={self.canonical_doi!r} title={self.title[:40]!r}>"


class PaperIdentifier(Base):
    """The merge substrate: (type, value) is globally unique across all papers."""

    __tablename__ = "paper_identifier"

    id_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_key: Mapped[str | None] = mapped_column(String(32))

    paper: Mapped[Paper] = relationship(back_populates="identifiers")

    def __repr__(self) -> str:
        return f"<PaperIdentifier {self.id_type}:{self.value}>"


class PaperRelation(Base):
    """Typed edge between two papers. Preprint links live here, not as merges."""

    __tablename__ = "paper_relation"

    from_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), primary_key=True
    )
    to_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_paper_relation_to", "to_paper_id", "relation_type"),
    )


class PaperMerge(Base):
    """Audit of every merge. Merges are reversible; nothing is hard-deleted."""

    __tablename__ = "paper_merge"

    id: Mapped[uuid.UUID] = uuid_pk()
    winner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), nullable=False, index=True
    )
    loser_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    rule: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("winner_id", "loser_id", name="uq_paper_merge_pair"),)
