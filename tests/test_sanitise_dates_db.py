"""The stored-date repair, against a real database.

`test_dates.py` covers the rule. This covers the thing that runs it over a
corpus: it writes NULLs into a live table, and the failure that matters is not
"missed a bad date" but "cleared a good one" - silently, on every row, with no
way to tell afterwards which dates were real.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from academious.db.models.paper import Paper
from tests.factories import make_paper

pytestmark = pytest.mark.db


def _load_script():
    """Load the script by path. `scripts/` is deliberately not a package."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "sanitise_dates.py"
    spec = importlib.util.spec_from_file_location("sanitise_dates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sanitise_dates = _load_script()


def _corpus(session):
    far_future = make_paper(
        session, "Dated 2050", published_date=date(2050, 2, 21), abstract="Text."
    )
    plausible = make_paper(
        session, "Next year's issue", published_date=date.today(), abstract="Text."
    )
    old = make_paper(session, "Victorian", published_date=date(1817, 3, 1), abstract="Text.")
    undated = make_paper(session, "No date at all", abstract="Text.")
    session.commit()
    return far_future, plausible, old, undated


def test_a_dry_run_writes_nothing(session):
    far_future, *_ = _corpus(session)

    counts = sanitise_dates.sanitise_stored(session, apply=False, batch_size=10)

    assert counts["affected"] == 1
    assert session.get(Paper, far_future.id).published_date == date(2050, 2, 21)


def test_applying_clears_the_date_and_the_year(session):
    far_future, *_ = _corpus(session)
    assert far_future.published_year == 2050

    sanitise_dates.sanitise_stored(session, apply=True, batch_size=10)

    refreshed = session.get(Paper, far_future.id)
    assert refreshed is not None
    assert refreshed.published_date is None
    # The year is derived from the date. Leaving it behind would keep the paper
    # filterable and sortable by a year nothing supports any more.
    assert refreshed.published_year is None


def test_plausible_dates_are_left_alone(session):
    _, plausible, old, undated = _corpus(session)
    expected = plausible.published_date

    sanitise_dates.sanitise_stored(session, apply=True, batch_size=10)

    assert session.get(Paper, plausible.id).published_date == expected
    assert session.get(Paper, old.id).published_date == date(1817, 3, 1)
    assert session.get(Paper, undated.id).published_date is None


def test_a_second_run_finds_nothing_left_to_do(session):
    _corpus(session)

    sanitise_dates.sanitise_stored(session, apply=True, batch_size=10)
    again = sanitise_dates.sanitise_stored(session, apply=True, batch_size=10)

    assert again["affected"] == 0


def test_an_implausible_online_date_is_cleared_without_touching_the_publication_date(session):
    paper = make_paper(session, "Odd online date", published_date=date(2026, 1, 1), abstract="T.")
    paper.first_seen_online = date(2049, 1, 1)
    session.commit()

    sanitise_dates.sanitise_stored(session, apply=True, batch_size=10)

    refreshed = session.get(Paper, paper.id)
    assert refreshed.first_seen_online is None
    assert refreshed.published_date == date(2026, 1, 1)


def test_batching_smaller_than_the_corpus_still_reaches_every_row(session):
    # The paging loop is the part that broke in backfill_fields.py, so it is
    # asserted here rather than assumed: a batch size below the row count must
    # not stop the walk early.
    for index in range(7):
        make_paper(session, f"Dated far ahead {index}", published_date=date(2049, 1, index + 1))
    session.commit()

    counts = sanitise_dates.sanitise_stored(session, apply=True, batch_size=2)

    assert counts["affected"] == 7
