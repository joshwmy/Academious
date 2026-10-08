"""Durable reader state and safe recommendation-learning behaviour."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from academious.api.dependencies import get_session
from academious.api.main import app
from academious.auth import current_active_user, current_verified_user
from academious.db.models import RankerWeight, RecommendationEvent, SavedPaper, User
from tests.factories import make_paper

pytestmark = pytest.mark.db


@pytest.fixture
def user(session) -> User:
    row = User(
        email="reader@example.org",
        hashed_password="not-used-by-this-endpoint-test",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        display_name="Reader",
        recommendation_data_consent=True,
        consent_version="2026-10-08",
        consented_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def client(session, user):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[current_verified_user] = lambda: user
    app.dependency_overrides[current_active_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _draft() -> dict:
    return {
        "fields": ["computer-science"],
        "interests": [],
        "example_papers": [],
        "negatives": [],
        "negative_papers": [],
        "blocked_topics": [],
        "discovery": {
            "freshness": "balanced",
            "exploration": "balanced",
            "publication": "include_preprints",
        },
    }


def test_profile_round_trips_as_reader_owned_state(client) -> None:
    saved = client.put("/me/profile", json=_draft())
    loaded = client.get("/me/profile")

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json() == saved.json()


def test_explicit_event_is_idempotent_saves_and_tunes_only_that_reader(
    client, session, user
) -> None:
    paper = make_paper(session, "A useful paper")
    now = datetime.now(UTC)
    feed_session = uuid.uuid4().hex
    session.add(
        RecommendationEvent(
            user_id=user.id,
            paper_id=paper.id,
            event_type="issued",
            occurred_at=now,
            received_at=now,
            position=1,
            session_id=feed_session,
            consent_version="2026-10-08",
            feature_snapshot={"semantic_affinity": 1.0},
        )
    )
    event_id = str(uuid.uuid4())
    payload = {
        "events": [
            {
                "event_id": event_id,
                "type": "save",
                "paper_id": str(paper.id),
                "occurred_at": now.isoformat(),
                "position": 1,
                "session_id": feed_session,
            }
        ]
    }

    first = client.post("/me/interactions", json=payload)
    again = client.post("/me/interactions", json=payload)

    assert first.json() == {"accepted": 1, "duplicates": 0}
    assert again.json() == {"accepted": 0, "duplicates": 1}
    assert session.get(SavedPaper, (user.id, paper.id)) is not None
    weight = session.get(RankerWeight, (user.id, "semantic_affinity"))
    assert weight is not None and weight.observations == 1


def test_unknown_papers_are_rejected_before_the_foreign_key_fails(client) -> None:
    response = client.post(
        "/me/interactions",
        json={
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "type": "save",
                    "paper_id": str(uuid.uuid4()),
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            ]
        },
    )

    assert response.status_code == 404
