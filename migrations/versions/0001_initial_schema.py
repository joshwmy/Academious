"""Initial Phase 1 schema: papers, identifiers, relations, OA, ops.

Revision ID: 0001
Revises:
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram similarity backs the fuzzy deduplication path.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "venue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("openalex_id", sa.String(32)),
        sa.Column("issn_l", sa.String(16)),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text()),
        sa.Column("venue_type", sa.String(32)),
        sa.Column("is_oa", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mean_citedness_2y", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_venue"),
        sa.UniqueConstraint("openalex_id", name="uq_venue_openalex_id"),
    )
    op.create_index("ix_venue_issn_l", "venue", ["issn_l"])

    op.create_table(
        "paper",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_doi", sa.String(255)),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_norm", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text()),
        sa.Column("abstract_source", sa.String(32)),
        sa.Column("authors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("first_author_surname", sa.String(128)),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True)),
        sa.Column("published_date", sa.Date()),
        sa.Column("first_seen_online", sa.Date()),
        sa.Column("published_year", sa.Integer()),
        sa.Column("is_preprint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_peer_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("work_type", sa.String(48)),
        sa.Column("language", sa.String(16)),
        sa.Column("topics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("citation_count", sa.Integer()),
        sa.Column("citation_count_at", sa.DateTime(timezone=True)),
        sa.Column("oa_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("best_oa_location_id", postgresql.UUID(as_uuid=True)),
        sa.Column("fulltext_status", sa.String(24), nullable=False, server_default="none"),
        sa.Column("fulltext_licence", sa.String(64)),
        sa.Column("retraction_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("retraction_notice_url", sa.Text()),
        sa.Column("retraction_checked_at", sa.DateTime(timezone=True)),
        sa.Column("quality_prior", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper"),
        sa.ForeignKeyConstraint(["venue_id"], ["venue.id"], name="fk_paper_venue_id_venue"),
        sa.UniqueConstraint("canonical_doi", name="uq_paper_canonical_doi"),
    )
    op.create_index("ix_paper_canonical_doi", "paper", ["canonical_doi"])
    op.create_index("ix_paper_published_date", "paper", ["published_date"])
    op.create_index("ix_paper_published_year", "paper", ["published_year"])
    op.create_index("ix_paper_retraction_status", "paper", ["retraction_status"])
    op.create_index("ix_paper_first_author_surname", "paper", ["first_author_surname"])
    op.create_index("ix_paper_venue_id", "paper", ["venue_id"])
    op.create_index("ix_paper_dedup_block", "paper", ["first_author_surname", "published_year"])
    op.create_index(
        "ix_paper_title_norm_trgm",
        "paper",
        ["title_norm"],
        postgresql_using="gin",
        postgresql_ops={"title_norm": "gin_trgm_ops"},
    )

    op.create_table(
        "paper_identifier",
        sa.Column("id_type", sa.String(16), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(32)),
        sa.PrimaryKeyConstraint("id_type", "value", name="pk_paper_identifier"),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["paper.id"], name="fk_paper_identifier_paper_id_paper",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_paper_identifier_paper_id", "paper_identifier", ["paper_id"])

    op.create_table(
        "paper_relation",
        sa.Column("from_paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(24), nullable=False),
        sa.Column("source_key", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "from_paper_id", "to_paper_id", "relation_type", name="pk_paper_relation"
        ),
        sa.ForeignKeyConstraint(
            ["from_paper_id"], ["paper.id"], name="fk_paper_relation_from_paper_id_paper",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_paper_id"], ["paper.id"], name="fk_paper_relation_to_paper_id_paper",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_paper_relation_to", "paper_relation", ["to_paper_id", "relation_type"])

    op.create_table(
        "paper_merge",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("winner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loser_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule", sa.String(48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_merge"),
        sa.ForeignKeyConstraint(
            ["winner_id"], ["paper.id"], name="fk_paper_merge_winner_id_paper", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("winner_id", "loser_id", name="uq_paper_merge_pair"),
    )
    op.create_index("ix_paper_merge_winner_id", "paper_merge", ["winner_id"])
    op.create_index("ix_paper_merge_loser_id", "paper_merge", ["loser_id"])

    op.create_table(
        "oa_location",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("pdf_url", sa.Text()),
        sa.Column("host_type", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("version", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("licence", sa.String(64)),
        sa.Column("source_name", sa.Text()),
        sa.Column("discovered_via", sa.String(32), nullable=False),
        sa.Column("is_best", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_oa_location"),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["paper.id"], name="fk_oa_location_paper_id_paper", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("paper_id", "url", name="uq_oa_location_paper_url"),
    )
    op.create_index("ix_oa_location_paper_id", "oa_location", ["paper_id"])
    op.create_foreign_key(
        "fk_paper_best_oa_location_id_oa_location",
        "paper",
        "oa_location",
        ["best_oa_location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ingestion_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cursor_start", sa.Text()),
        sa.Column("cursor_end", sa.Text()),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("papers_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("papers_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("papers_merged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relations_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oa_locations_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_run"),
    )
    op.create_index("ix_ingestion_run_source_key", "ingestion_run", ["source_key"])
    op.create_index(
        "ix_ingestion_run_source_started", "ingestion_run", ["source_key", "started_at"]
    )

    op.create_table(
        "source_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True)),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source_record"),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["paper.id"], name="fk_source_record_paper_id_paper",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_run.id"],
            name="fk_source_record_ingestion_run_id_ingestion_run", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("source_key", "source_id", name="uq_source_record_source_id"),
    )
    op.create_index("ix_source_record_source_key", "source_record", ["source_key"])
    op.create_index("ix_source_record_paper_id", "source_record", ["paper_id"])
    op.create_index("ix_source_record_hash", "source_record", ["source_key", "content_hash"])

    op.create_table(
        "retraction_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_id", sa.String(32), nullable=False),
        sa.Column("original_doi", sa.String(255)),
        sa.Column("original_pmid", sa.String(32)),
        sa.Column("notice_doi", sa.String(255)),
        sa.Column("notice_url", sa.Text()),
        sa.Column("nature", sa.String(48), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("retraction_date", sa.Date()),
        sa.Column("title", sa.Text()),
        sa.Column("journal", sa.Text()),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_retraction_record"),
        sa.UniqueConstraint("record_id", name="uq_retraction_record_record_id"),
    )
    op.create_index("ix_retraction_record_original_doi", "retraction_record", ["original_doi"])
    op.create_index("ix_retraction_record_original_pmid", "retraction_record", ["original_pmid"])

    op.create_table(
        "source_cursor",
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("cursor", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_key", name="pk_source_cursor"),
    )

    op.create_table(
        "job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("dedup_key", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job"),
        sa.UniqueConstraint("dedup_key", name="uq_job_dedup_key"),
    )
    op.create_index("ix_job_claim", "job", ["status", "priority", "run_after"])


def downgrade() -> None:
    op.drop_table("job")
    op.drop_table("source_cursor")
    op.drop_table("retraction_record")
    op.drop_table("source_record")
    op.drop_table("ingestion_run")
    op.drop_constraint("fk_paper_best_oa_location_id_oa_location", "paper", type_="foreignkey")
    op.drop_table("oa_location")
    op.drop_table("paper_merge")
    op.drop_table("paper_relation")
    op.drop_table("paper_identifier")
    op.drop_table("paper")
    op.drop_table("venue")
