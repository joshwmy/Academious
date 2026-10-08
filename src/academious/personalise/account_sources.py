"""Account-history candidate sources and reader-specific fact enrichment."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from academious.db.models import Paper, RecommendationEvent
from academious.personalise.candidates import Candidate, CandidateOrigin, CandidateReason
from academious.personalise.features import PaperFacts
from academious.personalise.profile import EncodedProfile

POSITIVE_EVENTS = ("open", "abstract_expand", "outbound_click", "save", "more_like_this")


@dataclass(slots=True)
class CollaborativeSource:
    session: Session
    user_id: uuid.UUID
    name: str = "collaborative"

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        del profile
        anchors = (
            select(RecommendationEvent.paper_id)
            .where(
                RecommendationEvent.user_id == self.user_id,
                RecommendationEvent.event_type.in_(POSITIVE_EVENTS),
            )
            .distinct()
        )
        peers = (
            select(RecommendationEvent.user_id)
            .where(
                RecommendationEvent.user_id != self.user_id,
                RecommendationEvent.paper_id.in_(anchors),
                RecommendationEvent.event_type.in_(POSITIVE_EVENTS),
            )
            .distinct()
        )
        support = func.count(func.distinct(RecommendationEvent.user_id))
        rows = self.session.execute(
            select(RecommendationEvent.paper_id, support.label("support"))
            .where(
                RecommendationEvent.user_id.in_(peers),
                RecommendationEvent.paper_id.not_in(anchors),
                RecommendationEvent.event_type.in_(POSITIVE_EVENTS),
            )
            .group_by(RecommendationEvent.paper_id)
            # Do not let one person's history become an observable
            # recommendation signal for another reader.
            .having(support >= 3)
            .order_by(desc("support"), RecommendationEvent.paper_id)
            .limit(budget)
        ).all()
        return [
            Candidate(
                paper_id=paper_id,
                reasons=(
                    CandidateReason(
                        origin=CandidateOrigin.COLLABORATIVE,
                        detail="readers with overlapping interests saved this",
                        strength=min(1.0, float(support) / 5.0),
                    ),
                ),
            )
            for paper_id, support in rows
        ]


@dataclass(slots=True)
class SequentialSource:
    session: Session
    user_id: uuid.UUID
    name: str = "sequential"

    def generate(self, profile: EncodedProfile, *, budget: int) -> Iterable[Candidate]:
        del profile
        recent_ids = self.session.scalars(
            select(RecommendationEvent.paper_id)
            .where(
                RecommendationEvent.user_id == self.user_id,
                RecommendationEvent.event_type.in_(POSITIVE_EVENTS),
            )
            .order_by(RecommendationEvent.occurred_at.desc())
            .limit(12)
        ).all()
        if not recent_ids:
            return []
        recent_fields: set[str] = set()
        for fields in self.session.scalars(select(Paper.fields).where(Paper.id.in_(recent_ids))):
            recent_fields.update(fields or ())
        if not recent_fields:
            return []
        rows = self.session.execute(
            select(Paper.id, Paper.fields)
            .where(Paper.id.not_in(recent_ids), Paper.fields.overlap(sorted(recent_fields)))
            .order_by(Paper.feed_date.desc().nullslast(), Paper.id.desc())
            .limit(budget)
        ).all()
        return [
            Candidate(
                paper_id=paper_id,
                reasons=(
                    CandidateReason(
                        origin=CandidateOrigin.SEQUENTIAL,
                        detail="continues what you have been reading recently",
                        strength=len(set(fields or ()) & recent_fields) / len(recent_fields),
                    ),
                ),
            )
            for paper_id, fields in rows
        ]


@dataclass(slots=True)
class AccountFacts:
    base: object
    session: Session
    user_id: uuid.UUID
    now: datetime

    def __call__(self, paper_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, PaperFacts]:
        facts = dict(self.base(paper_ids))  # type: ignore[operator]
        rows = self.session.execute(
            select(
                RecommendationEvent.paper_id,
                func.max(RecommendationEvent.occurred_at),
            )
            .where(
                RecommendationEvent.user_id == self.user_id,
                RecommendationEvent.event_type == "impression",
                RecommendationEvent.paper_id.in_(paper_ids),
            )
            .group_by(RecommendationEvent.paper_id)
        ).all()
        for paper_id, shown_at in rows:
            current = facts.get(paper_id)
            if current is not None and shown_at is not None:
                age = max(0.0, (self.now - shown_at) / timedelta(days=1))
                facts[paper_id] = replace(current, seen_days_ago=age)
        return facts
