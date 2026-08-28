"""Retraction Watch, via Crossref.

Crossref acquired the Retraction Watch database in 2023 and publishes it openly
under CC-BY 4.0, which permits commercial use with attribution. The whole dataset
is a single CSV (~66 MB, ~72,000 rows as of Phase 1), so it is downloaded and
diffed rather than queried per paper.

One DOI may have several notices - a correction, then an expression of concern,
then a retraction - so status is resolved by severity, never by last-write-wins.
Verified against the live dataset.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

from academious.core import ids as idutil
from academious.core.config import Settings, get_settings
from academious.core.http import SourceHttpClient
from academious.core.logging import get_logger
from academious.core.text import clean_display_text
from academious.db.models.paper import RetractionStatus

log = get_logger(__name__)

SOURCE_KEY = "retractionwatch"

# Higher wins when a paper has several notices.
SEVERITY: dict[str, int] = {
    RetractionStatus.NONE.value: 0,
    RetractionStatus.CORRECTED.value: 1,
    RetractionStatus.CONCERN.value: 2,
    RetractionStatus.RETRACTED.value: 3,
}

NATURE_TO_STATUS: dict[str, str] = {
    "retraction": RetractionStatus.RETRACTED.value,
    "expression of concern": RetractionStatus.CONCERN.value,
    "correction": RetractionStatus.CORRECTED.value,
    "reinstatement": RetractionStatus.NONE.value,
}


@dataclass(frozen=True, slots=True)
class RetractionNotice:
    record_id: str
    original_doi: str | None
    original_pmid: str | None
    notice_doi: str | None
    notice_url: str | None
    nature: str
    reason: str | None
    retraction_date: date | None
    title: str | None
    journal: str | None

    @property
    def status(self) -> str:
        return NATURE_TO_STATUS.get(self.nature.strip().lower(), RetractionStatus.CONCERN.value)


def parse_notice_date(value: str | None) -> date | None:
    """Retraction Watch uses US 'M/D/YYYY H:MM' with no zero padding."""
    if not value or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_csv(text: str) -> Iterator[RetractionNotice]:
    """Parse the dataset. Rows without any usable identifier are skipped."""
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        record_id = (row.get("Record ID") or "").strip()
        doi = idutil.normalise_doi(row.get("OriginalPaperDOI"))
        pmid = idutil.normalise_pmid(row.get("OriginalPaperPubMedID"))
        if not record_id or (not doi and not pmid):
            continue
        urls = (row.get("URLS") or "").strip()
        yield RetractionNotice(
            record_id=record_id,
            original_doi=doi,
            original_pmid=pmid,
            notice_doi=idutil.normalise_doi(row.get("RetractionDOI")),
            notice_url=urls.split(";")[0].strip() or None if urls else None,
            nature=(row.get("RetractionNature") or "").strip() or "Unknown",
            reason=clean_display_text(row.get("Reason")),
            retraction_date=parse_notice_date(row.get("RetractionDate")),
            title=clean_display_text(row.get("Title")),
            journal=clean_display_text(row.get("Journal")),
        )


class RetractionWatchClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http: SourceHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http = http or SourceHttpClient(SOURCE_KEY, settings=self._settings)

    def close(self) -> None:
        self._http.close()

    def fetch(self) -> Iterator[RetractionNotice]:
        """Download and parse the full dataset."""
        url = self._settings.retractionwatch_url
        text = self._http.get_text(url, params={"mailto": self._settings.contact_email})
        log.info("retractionwatch.downloaded", bytes=len(text))
        yield from parse_csv(text)
