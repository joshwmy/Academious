"""Computing and persisting paper embeddings.

Three properties are load-bearing and each is implemented explicitly rather than
hoped for:

**Idempotent.** Work is decided by comparing `input_text_hash` against the text
the builder produces now. Re-running over an already-embedded corpus performs no
model inference at all.

**Resumable.** Pending work is a query, not a checkpoint. Whatever was committed
before a crash stays committed, and the next run recomputes the remainder from
the database's own state. There is no cursor to corrupt.

**Isolated from ingestion.** Embeddings live in their own table, written in
their own transactions. A model that fails to load, an out-of-memory kill or a
poison record costs the corpus nothing: papers remain ingested, searchable
lexically, and simply unembedded until the next run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.core.logging import get_logger
from academious.db.models.embedding import EMBEDDING_DIM, PaperEmbedding
from academious.db.models.paper import Paper
from academious.embeddings.backend import EmbeddingBackend
from academious.embeddings.registry import EmbeddingProfile
from academious.embeddings.text import EmbeddingInput, build_embedding_input

log = get_logger(__name__)

DEFAULT_BATCH_SIZE = 32

#: Ceiling on how many pending ids one pass will pull into memory. At 16 bytes
#: per UUID this is a trivial allocation, and it bounds the work a single run
#: commits to, so an interrupted backfill is never far from a clean stopping
#: point.
MAX_PENDING_SCAN = 10_000


@dataclass(slots=True)
class EmbeddingStats:
    considered: int = 0
    embedded: int = 0
    skipped_unchanged: int = 0
    skipped_empty: int = 0
    failed: int = 0
    truncated: int = 0
    strategy_counts: dict[str, int] = field(default_factory=dict)

    def merge(self, other: EmbeddingStats) -> None:
        self.considered += other.considered
        self.embedded += other.embedded
        self.skipped_unchanged += other.skipped_unchanged
        self.skipped_empty += other.skipped_empty
        self.failed += other.failed
        self.truncated += other.truncated
        for key, value in other.strategy_counts.items():
            self.strategy_counts[key] = self.strategy_counts.get(key, 0) + value

    def as_dict(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "embedded": self.embedded,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_empty": self.skipped_empty,
            "failed": self.failed,
            "truncated": self.truncated,
            "strategies": dict(self.strategy_counts),
        }


def _pending_select(model_key: str) -> Select[tuple[uuid.UUID]]:
    """Papers with no embedding for this key, or one older than the paper row.

    The `updated_at` comparison is a cheap prefilter, not the decision: a paper
    can be updated in ways that do not change its embedding text (a citation
    count, an OA location). Those rows arrive here, fail the hash check, and are
    dismissed without inference - but their embedding timestamp is bumped so
    they do not queue again on the next pass.
    """
    embedding = PaperEmbedding
    return (
        select(Paper.id)
        .outerjoin(
            embedding,
            (embedding.paper_id == Paper.id) & (embedding.model_key == model_key),
        )
        .where((embedding.paper_id.is_(None)) | (Paper.updated_at > embedding.updated_at))
        .order_by(Paper.created_at.desc(), Paper.id)
    )


def count_pending(session: Session, model_key: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(_pending_select(model_key).subquery())
        ).scalar_one()
    )


def select_pending_paper_ids(session: Session, model_key: str, *, limit: int) -> list[uuid.UUID]:
    return list(session.execute(_pending_select(model_key).limit(limit)).scalars().all())


def iter_pending_batches(
    session: Session, model_key: str, *, batch_size: int, max_papers: int | None = None
) -> Iterator[list[uuid.UUID]]:
    """Chunk one bounded snapshot of pending paper ids into batches.

    The snapshot is taken once and then sliced in Python, rather than re-querying
    between batches. Re-querying is wrong here: queueing a paper does not remove
    it from the pending set - only a committed embedding does - so a consumer
    that only enqueues would be handed the same first batch forever.

    The snapshot is capped at MAX_PENDING_SCAN so that a first run against a
    large corpus does not try to materialise every id at once. Draining a big
    backlog therefore takes several runs, which is the intended shape: each run
    is bounded, resumable and safe to interrupt.
    """
    limit = min(max_papers, MAX_PENDING_SCAN) if max_papers is not None else MAX_PENDING_SCAN
    pending = select_pending_paper_ids(session, model_key, limit=limit)
    for start in range(0, len(pending), batch_size):
        yield pending[start : start + batch_size]


def _existing_rows(
    session: Session, model_key: str, paper_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PaperEmbedding]:
    rows = (
        session.execute(
            select(PaperEmbedding).where(
                PaperEmbedding.model_key == model_key,
                PaperEmbedding.paper_id.in_(paper_ids),
            )
        )
        .scalars()
        .all()
    )
    return {row.paper_id: row for row in rows}


def embed_papers(
    session: Session,
    paper_ids: Sequence[uuid.UUID],
    *,
    profile: EmbeddingProfile,
    backend: EmbeddingBackend,
) -> EmbeddingStats:
    """Embed exactly these papers under this profile. Flushes; does not commit.

    The caller owns the transaction boundary, because how much work a crash may
    lose is the caller's decision, not this function's.
    """
    stats = EmbeddingStats()
    if not paper_ids:
        return stats

    if backend.dimension != EMBEDDING_DIM:
        raise ValueError(
            f"backend {backend.model_id!r} produces {backend.dimension}-d vectors but "
            f"paper_embedding.embedding is halfvec({EMBEDDING_DIM})"
        )

    papers = session.execute(select(Paper).where(Paper.id.in_(paper_ids))).scalars().all()
    existing = _existing_rows(session, profile.key, paper_ids)
    now = utcnow()

    to_encode: list[tuple[Paper, EmbeddingInput]] = []
    for paper in papers:
        stats.considered += 1
        built = build_embedding_input(paper.title, paper.abstract, mode=profile.input_mode)
        if built.is_empty:
            stats.skipped_empty += 1
            log.warning("embeddings.empty_input", paper_id=str(paper.id))
            continue
        current = existing.get(paper.id)
        if current is not None and current.input_text_hash == built.text_hash:
            # Nothing to recompute. Touch the row so the paper stops appearing in
            # the pending set on every subsequent pass.
            current.updated_at = now
            stats.skipped_unchanged += 1
            continue
        to_encode.append((paper, built))

    if not to_encode:
        session.flush()
        return stats

    batch = backend.encode_documents([built.text for _, built in to_encode])

    payload = []
    for index, (paper, built) in enumerate(to_encode):
        payload.append(
            {
                "paper_id": paper.id,
                "model_key": profile.key,
                "embedding": batch.vectors[index],
                "dim": backend.dimension,
                "input_strategy": built.strategy.value,
                "input_text_hash": built.text_hash,
                "token_count": batch.token_counts[index],
                "truncated": batch.truncated[index],
                "created_at": now,
                "updated_at": now,
            }
        )
        stats.embedded += 1
        stats.truncated += int(batch.truncated[index])
        key = built.strategy.value
        stats.strategy_counts[key] = stats.strategy_counts.get(key, 0) + 1

    statement = insert(PaperEmbedding).values(payload)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["paper_id", "model_key"],
            set_={
                "embedding": statement.excluded.embedding,
                "dim": statement.excluded.dim,
                "input_strategy": statement.excluded.input_strategy,
                "input_text_hash": statement.excluded.input_text_hash,
                "token_count": statement.excluded.token_count,
                "truncated": statement.excluded.truncated,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )
    session.flush()
    # The identity map still holds the pre-upsert rows; they are stale now.
    for row in existing.values():
        session.expire(row)
    return stats
