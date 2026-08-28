"""Apply Retraction Watch notices to papers.

A paper can carry several notices over time - a correction, then an expression
of concern, then a retraction. Status is resolved by severity across all notices
for that paper, never by whichever row was processed last.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.core.ids import IdType
from academious.core.logging import get_logger
from academious.db.models.paper import Paper, PaperIdentifier, RetractionStatus
from academious.db.models.support import RetractionRecord
from academious.sources.retractionwatch.client import SEVERITY, RetractionNotice

log = get_logger(__name__)


def import_notices(session: Session, notices: Iterable[RetractionNotice]) -> tuple[int, int]:
    """Upsert notices. Returns (created, updated)."""
    created = updated = 0
    now = utcnow()
    for notice in notices:
        existing = session.execute(
            select(RetractionRecord).where(RetractionRecord.record_id == notice.record_id)
        ).scalars().first()
        if existing is None:
            session.add(
                RetractionRecord(
                    record_id=notice.record_id,
                    original_doi=notice.original_doi,
                    original_pmid=notice.original_pmid,
                    notice_doi=notice.notice_doi,
                    notice_url=notice.notice_url,
                    nature=notice.nature,
                    reason=notice.reason,
                    retraction_date=notice.retraction_date,
                    title=notice.title,
                    journal=notice.journal,
                    imported_at=now,
                )
            )
            created += 1
        else:
            existing.nature = notice.nature
            existing.reason = notice.reason
            existing.notice_url = notice.notice_url
            existing.imported_at = now
            updated += 1
    return created, updated


def _papers_for_notice(session: Session, notice: RetractionRecord) -> list[Paper]:
    clauses = []
    if notice.original_doi:
        clauses.append((IdType.DOI.value, notice.original_doi))
    if notice.original_pmid:
        clauses.append((IdType.PMID.value, notice.original_pmid))
    if not clauses:
        return []

    papers: dict[object, Paper] = {}
    for id_type, value in clauses:
        rows = session.execute(
            select(PaperIdentifier).where(
                PaperIdentifier.id_type == id_type, PaperIdentifier.value == value
            )
        ).scalars().all()
        for row in rows:
            paper = session.get(Paper, row.paper_id)
            if paper is not None:
                papers[paper.id] = paper
    return list(papers.values())


def apply_to_papers(session: Session) -> int:
    """Recompute retraction_status for every paper that has a notice.

    Returns the number of papers whose status changed.
    """
    notices = session.execute(select(RetractionRecord)).scalars().all()
    by_paper: dict[object, tuple[Paper, str, RetractionRecord]] = {}

    for notice in notices:
        status = _status_for(notice.nature)
        for paper in _papers_for_notice(session, notice):
            current = by_paper.get(paper.id)
            if current is None or SEVERITY.get(status, 0) > SEVERITY.get(current[1], 0):
                by_paper[paper.id] = (paper, status, notice)

    changed = 0
    now = utcnow()
    for paper, status, notice in by_paper.values():
        paper.retraction_checked_at = now
        if paper.retraction_status != status:
            paper.retraction_status = status
            paper.retraction_notice_url = notice.notice_url
            changed += 1
            log.info(
                "retraction.applied",
                paper=str(paper.id),
                status=status,
                doi=paper.canonical_doi,
            )
    return changed


def _status_for(nature: str) -> str:
    from academious.sources.retractionwatch.client import NATURE_TO_STATUS

    return NATURE_TO_STATUS.get(nature.strip().lower(), RetractionStatus.CONCERN.value)
