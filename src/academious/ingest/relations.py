"""Typed relationships between papers, principally preprint -> published.

A preprint and its published version are two distinct records with two distinct
DOIs and, in practice, two different titles. They must never be merged. They are
linked instead, so the feed can show one row (the published version) while
retaining the preprint's identity and posting date.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core import ids as idutil
from academious.core.clock import utcnow
from academious.core.ids import IdType
from academious.core.logging import get_logger
from academious.db.models.paper import Paper, PaperIdentifier, PaperRelation, RelationType

log = get_logger(__name__)


def find_by_doi(session: Session, doi: str | None) -> Paper | None:
    normalised = idutil.normalise_doi(doi)
    if not normalised:
        return None
    identifier = session.execute(
        select(PaperIdentifier).where(
            PaperIdentifier.id_type == IdType.DOI.value,
            PaperIdentifier.value == normalised,
        )
    ).scalars().first()
    return session.get(Paper, identifier.paper_id) if identifier else None


def relation_exists(
    session: Session, from_id: object, to_id: object, relation_type: str
) -> bool:
    return session.get(PaperRelation, (from_id, to_id, relation_type)) is not None


def link_preprint_to_published(
    session: Session, preprint_doi: str | None, published_doi: str | None, *, source_key: str
) -> bool:
    """Create a preprint_of edge when both papers are present. Idempotent."""
    preprint = find_by_doi(session, preprint_doi)
    published = find_by_doi(session, published_doi)
    if preprint is None or published is None or preprint.id == published.id:
        return False
    if relation_exists(session, preprint.id, published.id, RelationType.PREPRINT_OF.value):
        return False

    session.add(
        PaperRelation(
            from_paper_id=preprint.id,
            to_paper_id=published.id,
            relation_type=RelationType.PREPRINT_OF.value,
            source_key=source_key,
            created_at=utcnow(),
        )
    )
    # The published version is the canonical one for display purposes.
    if not published.is_peer_reviewed:
        published.is_peer_reviewed = True
    published.is_preprint = False
    log.info(
        "relation.preprint_linked",
        preprint=str(preprint.id),
        published=str(published.id),
        source=source_key,
    )
    return True
