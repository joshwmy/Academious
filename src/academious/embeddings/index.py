"""Optional ANN index management for the embedding column.

No migration creates this index. That is the point: Phase 2 measures what exact
search costs before paying for approximation, and an index that ships by default
would make that measurement impossible to take.

Exact search reads every vector for the model_key and is therefore correct by
construction - recall is 1.0, and a filter can never cost a result. HNSW trades
that away: it returns approximate neighbours, and a selective filter applied
alongside the index can silently drop relevant papers because the graph traversal
never visits them. The trade is worth making once sequential scan stops fitting
the latency budget, and not before. docs/performance.md has the numbers that say
where that point is.

Building the index is a one-off operational step:

    python -c "from academious.embeddings import index; index.create_hnsw()"
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from academious.core.logging import get_logger
from academious.db.session import session_scope

log = get_logger(__name__)

INDEX_NAME = "ix_paper_embedding_hnsw"

#: HNSW build parameters. m is edges per node, ef_construction is the candidate
#: list size while building. These are pgvector defaults; they are named here so
#: that a change is a visible decision rather than an implicit one.
DEFAULT_M = 16
DEFAULT_EF_CONSTRUCTION = 64

#: Vectors are stored L2-normalised, so cosine and inner product rank
#: identically. The opclass must still match the operator the query uses
#: (`<=>`), or PostgreSQL will ignore the index without saying so.
OPCLASS = "halfvec_cosine_ops"


@dataclass(frozen=True, slots=True)
class IndexState:
    exists: bool
    definition: str | None = None
    size_bytes: int | None = None


def create_hnsw(
    session: Session | None = None,
    *,
    m: int = DEFAULT_M,
    ef_construction: int = DEFAULT_EF_CONSTRUCTION,
    concurrently: bool = False,
) -> None:
    """Build the HNSW index over paper_embedding.embedding.

    `concurrently` avoids locking writes, at the cost of a longer build and the
    risk of leaving an invalid index behind if it fails. It cannot run inside a
    transaction block, so it opens its own autocommit connection.
    """
    statement = (
        f"CREATE INDEX {'CONCURRENTLY ' if concurrently else ''}IF NOT EXISTS {INDEX_NAME} "
        f"ON paper_embedding USING hnsw (embedding {OPCLASS}) "
        f"WITH (m = {m}, ef_construction = {ef_construction})"
    )
    log.info("embeddings.index_build_started", m=m, ef_construction=ef_construction)

    if concurrently:
        from academious.db.session import get_engine

        engine = get_engine().execution_options(isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            connection.execute(text(statement))
    elif session is not None:
        session.execute(text(statement))
    else:
        with session_scope() as owned:
            owned.execute(text(statement))

    log.info("embeddings.index_built", name=INDEX_NAME)


def drop_hnsw(session: Session | None = None) -> None:
    statement = f"DROP INDEX IF EXISTS {INDEX_NAME}"
    if session is not None:
        session.execute(text(statement))
    else:
        with session_scope() as owned:
            owned.execute(text(statement))
    log.info("embeddings.index_dropped", name=INDEX_NAME)


def state(session: Session) -> IndexState:
    row = session.execute(
        text(
            "SELECT indexdef, pg_relation_size(indexname::regclass) AS bytes "
            "FROM pg_indexes WHERE indexname = :name"
        ),
        {"name": INDEX_NAME},
    ).first()
    if row is None:
        return IndexState(exists=False)
    return IndexState(exists=True, definition=row.indexdef, size_bytes=int(row.bytes))


def set_search_ef(session: Session, ef_search: int) -> None:
    """Set hnsw.ef_search for this session.

    Higher values visit more of the graph: better recall, more time. This is the
    only knob that trades the two at query time, so it belongs next to the
    measurement that calibrates it rather than buried in configuration.
    """
    session.execute(text(f"SET hnsw.ef_search = {int(ef_search)}"))
