"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from hashlib import blake2b

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from academious.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def advisory_key(name: str) -> int:
    """A stable 64-bit key for a Postgres advisory lock, from a readable name.

    Advisory locks are keyed by integer, so the name has to be hashed - but not
    with the builtin `hash()`, which is salted per interpreter. Two containers
    would derive two different keys for one name and each conclude it held the
    lock alone, which is precisely the failure the lock exists to prevent.
    """
    return int.from_bytes(blake2b(name.encode(), digest_size=8).digest(), "big", signed=True)


@contextmanager
def exclusive_lock(name: str) -> Iterator[bool]:
    """Try to hold a cluster-wide lock for the block; yield whether we got it.

    The caller decides what to do when it did not, because "another pass is
    already running" is a different outcome from a failure and usually wants a
    different exit code.

    **In Postgres rather than on a file.** The maintenance passes this guards
    run as separate `docker compose run` containers, which share a database but
    not a filesystem: `flock` inside one container cannot see a lock held
    inside another, so both would take it and neither would notice.

    **On its own connection, not the caller's session.** A `Session` returns
    its connection to the pool at every commit, and these passes commit per
    batch - so a lock held on the session's connection would be handed away
    mid-pass. The unlock is explicit because closing a pooled connection
    returns it rather than terminating it, and an advisory lock outlives that.
    """
    key = advisory_key(name)
    connection = get_engine().connect()
    acquired = False
    try:
        acquired = bool(connection.scalar(select(func.pg_try_advisory_lock(key))))
        yield acquired
    finally:
        if acquired:
            connection.scalar(select(func.pg_advisory_unlock(key)))
        connection.close()
