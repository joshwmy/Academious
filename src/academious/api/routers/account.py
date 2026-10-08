"""Verified-account state for the recommendation feedback loop."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from academious.api import repository
from academious.api import schemas as public
from academious.api import schemas_profiles as wire
from academious.api.dependencies import get_retrieval_service, get_session
from academious.api.routers.papers import _summary
from academious.api.routers.profiles import (
    _draft_from,
    _draft_to,
    _feed,
    _issue,
    _items,
    _profile_out,
    _summary_out,
)
from academious.auth import current_active_user, current_verified_user
from academious.core.clock import utcnow
from academious.core.config import get_settings
from academious.db.models import (
    Paper,
    RankerWeight,
    RecommendationEvent,
    SavedPaper,
    User,
    UserResearchProfile,
)
from academious.onboarding import PROFILE_SCHEMA_VERSION
from academious.onboarding.builder import BuildError, ProfileBuilder
from academious.onboarding.corpus import DatabasePapers
from academious.onboarding.summary import summarise
from academious.personalise.features import FEATURE_SPECS
from academious.personalise.feedback import STRONG_NEGATIVE, STRONG_POSITIVE, EventType
from academious.retrieval.service import RetrievalService

router = APIRouter(prefix="/me", tags=["account"])
MAX_EVENT_BATCH = 100
LEARNING_RATE = 0.02


class EventIn(BaseModel):
    event_id: uuid.UUID
    type: Literal[
        "impression",
        "open",
        "abstract_expand",
        "outbound_click",
        "save",
        "follow_from_item",
        "more_like_this",
        "less_like_this",
        "not_interested",
        "dismiss",
        "block_topic",
    ]
    paper_id: uuid.UUID
    occurred_at: datetime
    position: int | None = Field(default=None, ge=1)
    interest_key: str | None = Field(default=None, max_length=512)
    session_id: str | None = Field(default=None, max_length=64)
    dwell_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class EventBatchIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=MAX_EVENT_BATCH)


class EventBatchOut(BaseModel):
    accepted: int
    duplicates: int


class AccountFeedOut(BaseModel):
    feed_session_id: str
    result: wire.ProfileResponse


@router.get("/profile", response_model=wire.DraftIn)
def get_profile(
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> wire.DraftIn:
    stored = session.get(UserResearchProfile, user.id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No research profile has been saved.")
    return wire.DraftIn.model_validate(stored.draft)


@router.put("/profile", response_model=wire.DraftIn)
def put_profile(
    body: wire.DraftIn,
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> wire.DraftIn:
    normalised = _draft_to(_draft_from(body))
    stored = session.get(UserResearchProfile, user.id)
    values = normalised.model_dump(mode="json")
    if stored is None:
        session.add(
            UserResearchProfile(
                user_id=user.id,
                schema_version=PROFILE_SCHEMA_VERSION,
                draft=values,
            )
        )
    else:
        stored.schema_version = PROFILE_SCHEMA_VERSION
        stored.draft = values
    return normalised


@router.post("/feed", response_model=AccountFeedOut)
def feed(
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AccountFeedOut:
    stored = session.get(UserResearchProfile, user.id)
    if stored is None:
        raise HTTPException(status_code=409, detail="Create a research profile first.")
    draft = _draft_from(wire.DraftIn.model_validate(stored.draft))
    builder = ProfileBuilder(
        encode=lambda texts: list(service.backend.encode_queries(list(texts)).vectors),
        papers=DatabasePapers(session, service.model_key),
        model_key=service.model_key,
        now=utcnow(),
    )
    try:
        built = builder.build(draft)
    except BuildError as error:
        raise HTTPException(
            status_code=422, detail="; ".join(issue.message for issue in error.issues)
        ) from error
    ranked = _feed(session, service, built, limit=limit, user_id=user.id)
    feed_session_id = uuid.uuid4().hex
    now = utcnow()
    for position, item in enumerate(ranked.items, start=1):
        session.add(
            RecommendationEvent(
                user_id=user.id,
                paper_id=item.paper_id,
                event_type="issued",
                occurred_at=now,
                received_at=now,
                position=position,
                interest_key=item.scored.matched_interest_key,
                session_id=feed_session_id,
                consent_version=(
                    user.consent_version or get_settings().recommendation_consent_version
                ),
                feature_snapshot=dict(item.scored.features.values),
            )
        )
    summary = summarise(built.profile)
    return AccountFeedOut(
        feed_session_id=feed_session_id,
        result=wire.ProfileResponse(
            draft=_draft_to(built.draft),
            profile=_profile_out(built, summary, service.model_key),
            summary=_summary_out(summary),
            preview=_items(session, ranked),
            issues=[_issue(issue) for issue in built.issues],
            changes=[],
        ),
    )


@router.post("/interactions", response_model=EventBatchOut)
def interactions(
    body: EventBatchIn,
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> EventBatchOut:
    now = utcnow()
    paper_ids = {item.paper_id for item in body.events}
    known_ids = set(session.scalars(select(Paper.id).where(Paper.id.in_(paper_ids))).all())
    if missing := paper_ids - known_ids:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {next(iter(missing))}")
    accepted = duplicates = 0
    for item in body.events:
        occurred_at = item.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        if occurred_at > now + timedelta(minutes=5) or occurred_at < now - timedelta(days=365):
            raise HTTPException(
                status_code=422,
                detail="Interaction timestamp is outside the accepted window.",
            )
        event_type = "not_relevant" if item.type == "not_interested" else item.type
        snapshot = _issued_snapshot(session, user.id, item.paper_id, item.session_id)
        inserted = session.execute(
            pg_insert(RecommendationEvent)
            .values(
                id=item.event_id,
                user_id=user.id,
                paper_id=item.paper_id,
                event_type=event_type,
                occurred_at=occurred_at,
                received_at=now,
                position=item.position,
                interest_key=item.interest_key,
                session_id=item.session_id,
                dwell_ms=item.dwell_ms,
                consent_version=(
                    user.consent_version or get_settings().recommendation_consent_version
                ),
                feature_snapshot=snapshot,
            )
            .on_conflict_do_nothing(index_elements=[RecommendationEvent.id])
            .returning(RecommendationEvent.id)
        ).scalar_one_or_none()
        if inserted is None:
            duplicates += 1
            continue
        _learn(session, user.id, event_type, snapshot, now)
        if event_type == "save":
            session.execute(
                pg_insert(SavedPaper)
                .values(user_id=user.id, paper_id=item.paper_id, created_at=now)
                .on_conflict_do_nothing(
                    index_elements=[SavedPaper.user_id, SavedPaper.paper_id]
                )
            )
        accepted += 1
    return EventBatchOut(accepted=accepted, duplicates=duplicates)


@router.get("/saved-papers", response_model=list[public.PaperSummary])
def saved_papers(
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[public.PaperSummary]:
    ids = session.scalars(
        select(SavedPaper.paper_id)
        .where(SavedPaper.user_id == user.id)
        .order_by(SavedPaper.created_at.desc())
    ).all()
    summaries = repository.summaries_for_ids(session, ids)
    return [_summary(summaries[paper_id]) for paper_id in ids if paper_id in summaries]


@router.delete("/saved-papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_paper(
    paper_id: uuid.UUID,
    user: Annotated[User, Depends(current_verified_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    saved = session.get(SavedPaper, (user.id, paper_id))
    if saved is not None:
        session.delete(saved)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user: Annotated[User, Depends(current_active_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Delete identity and all reader-owned state through database cascades."""
    session.delete(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _issued_snapshot(
    session: Session, user_id: uuid.UUID, paper_id: uuid.UUID, session_id: str | None
) -> dict[str, float] | None:
    if session_id is None:
        return None
    return session.scalar(
        select(RecommendationEvent.feature_snapshot)
        .where(
            RecommendationEvent.user_id == user_id,
            RecommendationEvent.paper_id == paper_id,
            RecommendationEvent.session_id == session_id,
            RecommendationEvent.event_type == "issued",
        )
        .order_by(RecommendationEvent.occurred_at.desc())
        .limit(1)
    )


def _learn(
    session: Session,
    user_id: uuid.UUID,
    raw_event_type: str,
    snapshot: dict[str, float] | None,
    now: datetime,
) -> None:
    if snapshot is None:
        return
    event_type = EventType(raw_event_type)
    if event_type not in STRONG_POSITIVE and event_type not in STRONG_NEGATIVE:
        return
    direction = 1.0 if event_type in STRONG_POSITIVE else -1.0
    for name, value in snapshot.items():
        if name not in FEATURE_SPECS or not 0.0 <= value <= 1.0:
            continue
        signed_value = FEATURE_SPECS[name].direction * value
        delta = LEARNING_RATE * direction * signed_value
        session.execute(
            pg_insert(RankerWeight)
            .values(
                user_id=user_id,
                feature_name=name,
                weight=delta,
                observations=1,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[RankerWeight.user_id, RankerWeight.feature_name],
                set_={
                    "weight": func.least(
                        1.0, func.greatest(-1.0, RankerWeight.weight + delta)
                    ),
                    "observations": RankerWeight.observations + 1,
                    "updated_at": now,
                },
            )
        )
