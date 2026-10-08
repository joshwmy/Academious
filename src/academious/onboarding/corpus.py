"""Resolving chosen papers against the corpus, in one query.

The only part of profile building that touches PostgreSQL. It is a separate
module so `builder.py` can stay a pure function of its inputs: the builder takes
a callable, a test passes a dictionary, and production passes this. Nothing in
`builder.py` imports SQLAlchemy, which is what makes the whole of profile
construction testable without a database.

One statement for every chosen paper, with the embedding left-joined. A loop of
per-paper lookups would be eight round trips for eight example papers, and the
eight are known up front.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.db.models.embedding import PaperEmbedding
from academious.db.models.paper import Paper
from academious.onboarding.builder import PaperReference


@dataclass(slots=True)
class DatabasePapers:
    """A `PaperVectors` backed by the corpus.

    `model_key` is carried rather than defaulted, so a profile can never be
    built from vectors of one model against a corpus embedded under another -
    the guard `RetrievalService` and `DatabaseFacts` both make, for the same
    reason.
    """

    session: Session
    model_key: str

    def __call__(self, paper_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, PaperReference]:
        if not paper_ids:
            return {}
        rows = self.session.execute(
            select(Paper.id, Paper.title, PaperEmbedding.embedding)
            .outerjoin(
                PaperEmbedding,
                (PaperEmbedding.paper_id == Paper.id)
                & (PaperEmbedding.model_key == self.model_key),
            )
            # A left join, not an inner one: a paper waiting on the embedding
            # backlog has to come back, so the reader is told *this paper is not
            # embedded yet* rather than *no such paper*. Those are different
            # problems and only one of them is theirs.
            .where(Paper.id.in_(list(paper_ids)))
        ).all()

        return {
            row[0]: PaperReference(
                paper_id=row[0],
                title=row[1],
                vector=np.asarray(row[2], dtype=np.float32) if row[2] is not None else None,
            )
            for row in rows
        }
