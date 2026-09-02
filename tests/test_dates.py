"""The publication-date plausibility horizon.

These tests fix the boundary in place. The rule exists because the feed orders
by `published_date DESC`, which turns a fabricated date into a permanent front
page - so the interesting cases are not "is 2050 wrong" but the two edges: a
legitimately postdated issue must survive, and a date a year and a day out must
not.
"""

from __future__ import annotations

from datetime import date

import pytest

from academious.ingest.dates import FUTURE_HORIZON_DAYS, is_plausible, sanitise
from academious.sources.base import PaperCandidate

TODAY = date(2026, 9, 3)


def candidate(**kwargs) -> PaperCandidate:
    return PaperCandidate(source_key="openalex", source_id="W1", title="A paper", **kwargs)


def test_the_horizon_is_a_year():
    assert FUTURE_HORIZON_DAYS == 365


@pytest.mark.parametrize(
    "value",
    [
        None,
        date(1817, 1, 1),  # the Edinburgh medical journal is genuinely this old
        date(2026, 9, 3),
        date(2026, 12, 1),  # a December issue, published in September
        date(2027, 3, 1),  # next year's issue, ordinary postdating
        date(2027, 9, 3),  # exactly the horizon
    ],
)
def test_plausible_dates_are_kept(value):
    assert is_plausible(value, today=TODAY)


@pytest.mark.parametrize(
    "value",
    [
        date(2027, 9, 4),  # one day past the horizon
        date(2028, 1, 1),
        date(2050, 2, 21),  # the worst one in the live corpus
    ],
)
def test_dates_past_the_horizon_are_not_believed(value):
    assert not is_plausible(value, today=TODAY)


def test_sanitise_returns_the_candidate_unchanged_when_nothing_is_wrong():
    original = candidate(published_date=date(2026, 12, 1), first_seen_online=date(2026, 8, 1))

    assert sanitise(original, today=TODAY) is original


def test_an_implausible_publication_date_becomes_unknown():
    # Cleared rather than clamped: a made-up date moved to the horizon is still
    # a made-up date, and it would rank above every real paper published today.
    cleaned = sanitise(candidate(published_date=date(2050, 2, 21)), today=TODAY)

    assert cleaned.published_date is None


def test_the_online_date_is_judged_separately():
    cleaned = sanitise(
        candidate(published_date=date(2026, 10, 1), first_seen_online=date(2049, 1, 1)),
        today=TODAY,
    )

    assert cleaned.published_date == date(2026, 10, 1)
    assert cleaned.first_seen_online is None


def test_nothing_else_about_the_candidate_is_touched():
    original = candidate(
        published_date=date(2050, 2, 21),
        abstract="An abstract.",
        topics=[{"scheme": "openalex", "field": "Medicine"}],
    )

    cleaned = sanitise(original, today=TODAY)

    assert cleaned.title == original.title
    assert cleaned.abstract == original.abstract
    assert cleaned.topics == original.topics
    assert cleaned.source_key == original.source_key
