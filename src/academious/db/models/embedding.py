"""Vector embedding storage.

One row per (canonical paper, model_key). An embedding is a property of a
paper, never of a user: a per-user copy of a 768-dimensional vector multiplies
storage by the user count and buys nothing, because the vector does not depend
on who is asking (see docs/embeddings.md).

`model_key` carries the model identity *and* the preprocessing version, so a
change to either writes a distinguishable row instead of silently corrupting the
corpus. Re-embedding is then a matter of populating rows under a new model_key
and switching the read path over, with the old vectors still queryable
throughout.

`input_text_hash` is what makes an embedding run idempotent at the row level: if
the text we would feed the model hashes to what produced the stored vector,
there is no work to do, even when the paper row itself has been updated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from academious.db.base import Base

# SPECTER2 is bert-base shaped: 768-dimensional CLS embeddings. The column type
# fixes this, deliberately. A model with a different width is a schema change and
# should be visible as one rather than hidden behind a nullable width column.
EMBEDDING_DIM = 768


class PaperEmbedding(Base):
    """A dense vector for one paper under one model+preprocessing version."""

    __tablename__ = "paper_embedding"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), primary_key=True
    )
    model_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    embedding: Mapped[list[float]] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=EMBEDDING_DIM)

    # Which text the vector was built from, and the exact bytes' fingerprint.
    input_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    input_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Drives "which papers still need embedding under model_key X", which is
        # a LEFT JOIN anti-join from paper. The primary key is (paper_id,
        # model_key) and cannot serve a model_key-leading probe.
        Index("ix_paper_embedding_model_paper", "model_key", "paper_id"),
    )

    def __repr__(self) -> str:
        return f"<PaperEmbedding {self.paper_id} {self.model_key} {self.input_strategy}>"
