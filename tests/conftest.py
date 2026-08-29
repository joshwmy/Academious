"""Shared test fixtures.

Two tiers of test live here:

* Pure tests - normalisation, rate limiting, HTTP behaviour, field precedence.
  No database, no network, runnable anywhere.
* Database tests - marked `db`. They need PostgreSQL with pg_trgm (the fuzzy
  dedup path is SQL) and pgvector (embedding storage and distance operators).
  They are skipped, not failed, when no database is configured, so `pytest`
  is always green on a bare checkout.

Nothing in this suite touches the internet. Every external payload is a recorded
fixture captured from the real API during Phase 0.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT_TEST_DB = "postgresql+psycopg://academious:academious@localhost:5432/academious_test"


def load_json(*parts: str) -> dict:
    return json.loads((FIXTURES.joinpath(*parts)).read_text(encoding="utf-8"))


def load_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def database_url() -> str | None:
    """The test database URL, or None when database tests should be skipped."""
    url = os.environ.get("ACADEMIOUS_TEST_DATABASE_URL", DEFAULT_TEST_DB)
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    try:
        engine = create_engine(
            admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        )
        with engine.connect() as connection:
            database_name = url.rsplit("/", 1)[1]
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database_name}
            ).first()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        engine.dispose()
    except Exception:
        return None
    return url


@pytest.fixture(scope="session")
def engine(database_url: str | None):
    if database_url is None:
        pytest.skip("no PostgreSQL available; set ACADEMIOUS_TEST_DATABASE_URL")

    os.environ["ACADEMIOUS_DATABASE_URL"] = database_url
    from academious.core.config import get_settings

    get_settings.cache_clear()

    engine = create_engine(database_url)
    from academious.db.ddl import bootstrap_sql

    with engine.begin() as connection:
        for statement in bootstrap_sql():
            connection.execute(text(statement))

    from academious.db.models import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """A clean session per test. Every table is truncated between tests."""
    from academious.db.models import Base

    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with engine.begin() as connection:
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    db = maker()
    try:
        yield db
        db.commit()
    finally:
        db.close()
