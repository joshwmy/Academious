"""Account boundary invariants that do not need a database."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academious.auth import UserCreate


def test_registration_requires_explicit_recommendation_data_consent() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            email="reader@example.org",
            password="a sufficiently long password",
            display_name="Reader",
            recommendation_data_consent=False,
        )


def test_registration_accepts_explicit_consent() -> None:
    user = UserCreate(
        email="reader@example.org",
        password="a sufficiently long password",
        display_name="Reader",
        recommendation_data_consent=True,
    )

    assert user.recommendation_data_consent is True
