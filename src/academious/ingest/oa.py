"""Open-access locations.

Every discovered legal location is kept; one is flagged best. Nothing here
fetches or stores a document - Phase 1 records where a legal copy lives and
under what licence, and that is all (see docs/open-access.md).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.db.models.paper import Paper
from academious.db.models.support import OaLocation
from academious.sources.base import CandidateLocation

VERSION_RANK = {"publishedVersion": 3, "acceptedVersion": 2, "submittedVersion": 1, "unknown": 0}
HOST_RANK = {"publisher": 3, "repository": 2, "preprint": 1, "unknown": 0}
# Licences that permit storing and processing the full text, best first.
LICENCE_RANK = {"cc0": 4, "cc-by": 3, "cc-by-sa": 2, "cc-by-nc": 1}


def location_score(location: OaLocation) -> tuple[int, int, int]:
    return (
        VERSION_RANK.get(location.version, 0),
        HOST_RANK.get(location.host_type, 0),
        LICENCE_RANK.get((location.licence or "").lower(), 0),
    )


def apply_locations(
    session: Session, paper: Paper, locations: list[CandidateLocation], *, discovered_via: str
) -> int:
    """Upsert locations for a paper and re-elect the best. Returns rows created."""
    if not locations:
        return 0

    existing = {location.url: location for location in paper.oa_locations}
    created = 0
    now = utcnow()

    for candidate in locations:
        current = existing.get(candidate.url)
        if current is None:
            current = OaLocation(
                paper_id=paper.id,
                url=candidate.url,
                pdf_url=candidate.pdf_url,
                host_type=candidate.host_type,
                version=candidate.version,
                licence=candidate.licence,
                source_name=candidate.source_name,
                discovered_via=discovered_via,
                verified_at=now,
            )
            session.add(current)
            paper.oa_locations.append(current)
            existing[candidate.url] = current
            created += 1
        else:
            current.pdf_url = current.pdf_url or candidate.pdf_url
            current.licence = current.licence or candidate.licence
            current.verified_at = now

    # Primary keys are assigned at flush, and electing a best location records
    # that key on the paper, so the flush has to happen first.
    session.flush()
    elect_best(paper)
    return created


def elect_best(paper: Paper) -> OaLocation | None:
    """Choose the best location by version, then host, then licence."""
    if not paper.oa_locations:
        paper.best_oa_location_id = None
        return None

    best = max(paper.oa_locations, key=location_score)
    for location in paper.oa_locations:
        location.is_best = location is best
    paper.best_oa_location_id = best.id
    if best.licence and not paper.fulltext_licence:
        paper.fulltext_licence = best.licence
    return best
