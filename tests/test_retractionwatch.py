"""Retraction Watch parsing and severity resolution."""

from __future__ import annotations

from tests.conftest import load_text

from academious.db.models.paper import RetractionStatus
from academious.sources.retractionwatch.client import SEVERITY, parse_csv, parse_notice_date


def notices():
    return list(parse_csv(load_text("retractionwatch", "sample.csv")))


def test_parses_real_export_rows():
    parsed = notices()
    assert parsed
    assert all(notice.record_id for notice in parsed)


def test_one_doi_can_carry_several_notices():
    """Verified against the live dataset: the Lancet paper has three."""
    lancet = [n for n in notices() if n.original_doi == "10.1016/s0140-6736(20)31180-6"]
    assert len(lancet) >= 3
    assert {n.nature for n in lancet} >= {"Retraction", "Expression of concern", "Correction"}


def test_severity_ordering_picks_retraction_over_concern_and_correction():
    lancet = [n for n in notices() if n.original_doi == "10.1016/s0140-6736(20)31180-6"]
    worst = max(lancet, key=lambda n: SEVERITY[n.status])
    assert worst.status == RetractionStatus.RETRACTED.value


def test_us_date_format_is_parsed():
    assert parse_notice_date("6/5/2020 0:00").isoformat() == "2020-06-05"
    assert parse_notice_date("12/31/2019").isoformat() == "2019-12-31"
    assert parse_notice_date("") is None
    assert parse_notice_date("not a date") is None


def test_rows_without_identifiers_are_skipped():
    header = "Record ID,OriginalPaperDOI,OriginalPaperPubMedID,RetractionNature\n"
    assert list(parse_csv(header + "1,,,Retraction\n")) == []


def test_status_mapping_covers_every_nature_we_have_seen():
    for notice in notices():
        assert notice.status in {s.value for s in RetractionStatus}
