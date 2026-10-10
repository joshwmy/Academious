"""The shared interest scan returns exactly what the two scans it replaces did.

`InterestScan` exists for speed: one pass over the embedding window instead of
two. It is only an optimisation if nothing a reader sees changes, so this pins
the semantic list and the adjacent band, row for row and in order, against the
queries `SemanticInterestSource` and `AdjacentInterestSource` run on their own.

The corpus is built so the band is populated: each paper's vector is a known
mixture of one interest and noise, which spreads cosines across 0..1 rather
than leaving them all near zero as random 768-d vectors would.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from academious.db.models.embedding import PaperEmbedding
from academious.personalise.pgvector import (
    AdjacentInterestSource,
    InterestScan,
    SemanticInterestSource,
)
from academious.personalise.profile import (
    EncodedProfile,
    Interest,
    InterestKind,
    InterestProfile,
)
from tests.factories import make_paper

pytestmark = pytest.mark.db

MODEL_KEY = "scan-test@v1"
DIMENSIONS = 768
TODAY = date(2026, 9, 1)


def _unit(vector: np.ndarray) -> np.ndarray:
    return (vector / np.linalg.norm(vector)).astype(np.float32)


@pytest.fixture
def interests() -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(7)
    return tuple(_unit(rng.standard_normal(DIMENSIONS)) for _ in range(3))


@pytest.fixture
def corpus(session, interests):
    """60 papers in the window, 10 outside it, cosines spread across 0..1."""
    rng = np.random.default_rng(11)
    now = datetime.now(UTC)
    for index in range(70):
        published = TODAY - timedelta(days=5 if index < 60 else 200)
        paper = make_paper(session, f"Scan test paper {index}", published_date=published)
        target = interests[index % len(interests)]
        mix = (index % 20) / 19.0
        vector = _unit(mix * target + (1.0 - mix) * _unit(rng.standard_normal(DIMENSIONS)))
        session.add(
            PaperEmbedding(
                paper_id=paper.id,
                model_key=MODEL_KEY,
                embedding=vector,
                dim=DIMENSIONS,
                input_strategy="title_abstract",
                input_text_hash=hashlib.sha256(str(index).encode()).hexdigest(),
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()


def _profile(interests) -> EncodedProfile:
    profile = InterestProfile(
        interests=tuple(
            Interest(
                key=f"i{index}",
                kind=InterestKind.STATED,
                label=f"Interest {index}",
                text=f"a described research interest number {index}",
                vector=vector,
            )
            for index, vector in enumerate(interests)
        )
    )
    return EncodedProfile(profile=profile, model_key=MODEL_KEY)


def _ids(candidates) -> list:
    return [candidate.paper_id for candidate in candidates]


def _strengths(candidates) -> list[float]:
    return [round(reason.strength, 5) for c in candidates for reason in c.reasons]


@pytest.mark.parametrize("budget", [5, 25, 200])
def test_semantic_from_scan_matches_its_own_query(session, corpus, interests, budget):
    profile = _profile(interests)
    alone = SemanticInterestSource(session=session, model_key=MODEL_KEY, today=TODAY)
    shared = SemanticInterestSource(
        session=session,
        model_key=MODEL_KEY,
        today=TODAY,
        scan=InterestScan(session=session, model_key=MODEL_KEY, limit=200, today=TODAY),
    )

    expected = list(alone.generate(profile, budget=budget))
    actual = list(shared.generate(profile, budget=budget))

    assert expected, "the corpus should produce semantic candidates"
    assert _ids(actual) == _ids(expected)
    assert _strengths(actual) == _strengths(expected)


@pytest.mark.parametrize("budget", [5, 25, 200])
def test_adjacent_from_scan_matches_its_own_query(session, corpus, interests, budget):
    profile = _profile(interests)
    alone = AdjacentInterestSource(session=session, model_key=MODEL_KEY, today=TODAY)
    shared = AdjacentInterestSource(
        session=session,
        model_key=MODEL_KEY,
        today=TODAY,
        scan=InterestScan(session=session, model_key=MODEL_KEY, limit=200, today=TODAY),
    )

    expected = list(alone.generate(profile, budget=budget))
    actual = list(shared.generate(profile, budget=budget))

    assert expected, "the corpus should put some papers inside the adjacency band"
    assert _ids(actual) == _ids(expected)
    assert _strengths(actual) == _strengths(expected)


def test_both_sources_share_one_query(session, corpus, interests):
    """The point of the scan: the second source reads the first one's result."""
    profile = _profile(interests)
    scan = InterestScan(session=session, model_key=MODEL_KEY, limit=50, today=TODAY)
    statements: list[str] = []

    from sqlalchemy import event

    def record(conn, cursor, statement, *args):
        if "paper_embedding" in statement:
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        list(
            SemanticInterestSource(
                session=session, model_key=MODEL_KEY, today=TODAY, scan=scan
            ).generate(profile, budget=30)
        )
        list(
            AdjacentInterestSource(
                session=session, model_key=MODEL_KEY, today=TODAY, scan=scan
            ).generate(profile, budget=20)
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(statements) == 1
    assert "MATERIALIZED" in statements[0]


def test_a_larger_budget_than_the_scan_holds_fetches_again(session, corpus, interests):
    profile = _profile(interests)
    scan = InterestScan(session=session, model_key=MODEL_KEY, limit=3, today=TODAY)

    assert len(scan.top(profile, budget=3)) == 3
    assert len(scan.top(profile, budget=40)) == 40


def test_the_window_excludes_old_papers(session, corpus, interests):
    profile = _profile(interests)
    scan = InterestScan(session=session, model_key=MODEL_KEY, limit=500, today=TODAY)

    assert len(scan.top(profile, budget=500)) == 60
