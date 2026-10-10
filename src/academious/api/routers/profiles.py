"""Research profile creation, preview and refinement. Stateless throughout.

Three endpoints and no storage. A client posts everything the reader has chosen,
the server normalises it, builds a canonical `InterestProfile`, runs the
recommender over the corpus and returns the result. Nothing is written, nothing
is cached against a caller, and there is no identifier by which a second request
could find the first. That is not a limitation waiting to be fixed: it is what
lets profile creation ship before accounts, and when accounts arrive the thing
to store is the draft this endpoint already round-trips.

**Create, preview, correct - never "profile saved".** There is nobody to save it
for, and a profile whose consequences the reader has not seen is a guess. So
`POST /profiles/preview` always returns the feed the profile produces, and
`POST /profiles/refine` returns the feed the correction produced.

**What is never logged.** A research profile is a statement about what someone
is working on, which can be more sensitive than any single search. `/search`
already logs `query_length` rather than the query (SEC-009); this router follows
it exactly - counts, sizes and timings only. No interest text, no labels, no
paper ids, no draft. A profile that reached the log would outlive the request
that was designed to forget it.

**Scores stop here.** `ScoredCandidate` carries the arithmetic and the feed
carries diagnostics; the response carries a rank, a paper and a reason.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.api import repository
from academious.api import schemas_profiles as wire
from academious.api.concurrency import search_gate
from academious.api.dependencies import get_retrieval_service, get_session
from academious.api.limits import limiter, search_limit
from academious.api.routers.papers import _summary
from academious.core.clock import utcnow
from academious.core.logging import get_logger
from academious.db.models import RankerWeight
from academious.onboarding import PROFILE_SCHEMA_VERSION
from academious.onboarding.builder import BuildError, BuildResult, ProfileBuilder
from academious.onboarding.corpus import DatabasePapers
from academious.onboarding.draft import (
    MAX_BLOCKED_TOPICS,
    MAX_BROAD_FIELDS,
    MAX_EXAMPLE_PAPERS,
    MAX_INTEREST_CHARS,
    MAX_NEGATIVE_INTERESTS,
    MAX_TEXT_INTERESTS,
    DiscoveryChoices,
    DraftIssue,
    ExamplePaper,
    NegativeInterest,
    NegativePaper,
    ProfileDraft,
    TextInterest,
)
from academious.onboarding.levels import (
    AVOIDANCE_LABEL,
    EXPLORATION_LABEL,
    FRESHNESS_LABEL,
    IMPORTANCE_LABEL,
    PUBLICATION_LABEL,
    avoidance_for_weight,
    importance_for_weight,
)
from academious.onboarding.refine import Refinement, apply_all
from academious.onboarding.summary import ProfileSummary, summarise
from academious.personalise.account_sources import (
    AccountFacts,
    CollaborativeSource,
    SequentialSource,
)
from academious.personalise.candidates import CandidateBudget, CandidateSource
from academious.personalise.feed import FeedConfig, FeedResult, build_feed
from academious.personalise.pgvector import (
    AdjacentInterestSource,
    DatabaseFacts,
    ExactFieldSource,
    InterestScan,
    SemanticInterestSource,
)
from academious.personalise.profile import MAX_INTERESTS, InterestKind, Polarity
from academious.personalise.ranking import DeterministicRanker, Weights, weights_for
from academious.personalise.rerank import DiversityPolicy
from academious.retrieval.service import RetrievalService

router = APIRouter(prefix="/profiles", tags=["profiles"])
log = get_logger(__name__)

UNPROCESSABLE = 422

#: Candidates considered per preview. The pipeline default, restated here
#: because a preview is a feed request and should cost what one costs.
PREVIEW_BUDGET = 400


@router.get(
    "/options",
    summary="The vocabulary the profile builder accepts",
    response_model=wire.OptionsResponse,
    description=(
        "Every choice a reader can make, with the label to show for it, plus the limits a "
        "form should enforce. Served by the server so a client never hardcodes a level name "
        "or a maximum that could change."
    ),
)
@limiter.limit(search_limit)
def options(request: Request, response: Response) -> wire.OptionsResponse:
    return wire.OptionsResponse(
        importance=_options(IMPORTANCE_LABEL),
        avoidance=_options(AVOIDANCE_LABEL),
        freshness=_options(FRESHNESS_LABEL),
        exploration=_options(EXPLORATION_LABEL),
        publication=_options(PUBLICATION_LABEL),
        limits={
            "broad_areas": MAX_BROAD_FIELDS,
            "interests": MAX_TEXT_INTERESTS,
            "example_papers": MAX_EXAMPLE_PAPERS,
            "negatives": MAX_NEGATIVE_INTERESTS,
            "blocked_topics": MAX_BLOCKED_TOPICS,
            "total_interests": MAX_INTERESTS,
            "interest_characters": MAX_INTEREST_CHARS,
        },
    )


@router.post(
    "/preview",
    summary="Build a research profile and see the feed it produces",
    response_model=wire.ProfileResponse,
    responses={
        422: {"model": wire.IssueOut, "description": "The draft cannot become a profile"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "At capacity"},
    },
    description=(
        "Normalises the draft, builds the canonical profile and returns the recommendations "
        "that profile produces. Nothing is stored: the returned draft is the client's to keep "
        "and to send back. Warnings that did not prevent the build - a merged duplicate, an "
        "example paper with no embedding yet - are reported in `issues`."
    ),
)
@limiter.limit(search_limit)
def preview(
    request: Request,
    response: Response,
    body: wire.PreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> wire.ProfileResponse:
    return _respond(session, service, _draft_from(body.draft), limit=body.limit)


@router.post(
    "/refine",
    summary="Correct a profile from its preview, and see the result",
    response_model=wire.ProfileResponse,
    responses={
        422: {"model": wire.IssueOut, "description": "The corrected draft cannot be built"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "At capacity"},
    },
    description=(
        "Applies corrections to the draft in the order given and returns the updated draft, "
        "profile, summary and preview. Corrections are deterministic and inspectable: each "
        "one adds or changes something visible in the returned draft, and `changes` says what."
    ),
)
@limiter.limit(search_limit)
def refine(
    request: Request,
    response: Response,
    body: wire.RefineRequest,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> wire.ProfileResponse:
    corrected = apply_all(
        _draft_from(body.draft),
        [
            Refinement(
                action=item.action,
                paper_id=item.paper_id,
                interest_key=item.interest_key,
                topic_id=item.topic_id,
                label=item.label,
            )
            for item in body.refinements
        ],
    )
    return _respond(
        session,
        service,
        corrected.draft,
        limit=body.limit,
        changes=corrected.changes,
        extra_issues=corrected.issues,
    )


# --- the one path both endpoints take -----------------------------------------


def _respond(
    session: Session,
    service: RetrievalService,
    draft: ProfileDraft,
    *,
    limit: int,
    changes: tuple[str, ...] = (),
    extra_issues: tuple[DraftIssue, ...] = (),
) -> wire.ProfileResponse:
    started = time.perf_counter()
    builder = ProfileBuilder(
        encode=lambda texts: list(service.backend.encode_queries(list(texts)).vectors),
        papers=DatabasePapers(session, service.model_key),
        model_key=service.model_key,
        now=utcnow(),
    )
    try:
        built = builder.build(draft)
    except BuildError as error:
        # Every reason at once. A reader who typed one interest too short and
        # picked one field that does not exist should not have to submit twice
        # to discover the second problem.
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail="; ".join(issue.message for issue in error.issues),
        ) from error

    with search_gate.acquire():
        feed = _feed(session, service, built, limit=limit)

    items = _items(session, feed)
    summary = summarise(built.profile)
    log.info(
        "api.profile_preview",
        # Counts and sizes only. The interests themselves, their labels and the
        # chosen paper ids are absent on purpose - see the module docstring.
        interests=len(built.profile.interests),
        positive=len(built.profile.positive),
        negative=len(built.profile.negative),
        example_papers=sum(1 for i in built.profile.interests if i.kind is InterestKind.PAPER),
        candidates=feed.diagnostics.candidates_considered,
        blocked=feed.diagnostics.filtered_by_block,
        returned=len(items),
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )

    return wire.ProfileResponse(
        draft=_draft_to(built.draft),
        profile=_profile_out(built, summary, service.model_key),
        summary=_summary_out(summary),
        preview=items,
        issues=[_issue(issue) for issue in (*built.issues, *extra_issues)],
        changes=list(changes),
    )


def _feed(
    session: Session,
    service: RetrievalService,
    built: BuildResult,
    *,
    limit: int,
    user_id: uuid.UUID | None = None,
) -> FeedResult:
    today = utcnow().date()
    preferences = built.profile.preferences
    # One pass over the embeddings serves both the semantic and the adjacent
    # source; see InterestScan for what two passes cost.
    scan = InterestScan(
        session=session, model_key=service.model_key, limit=PREVIEW_BUDGET, today=today
    )
    sources: list[CandidateSource] = [
        SemanticInterestSource(
            session=session, model_key=service.model_key, today=today, scan=scan
        ),
        ExactFieldSource(session=session, today=today),
    ]
    if user_id is not None:
        sources.extend(
            [
                SequentialSource(session=session, user_id=user_id),
                CollaborativeSource(session=session, user_id=user_id),
            ]
        )
    # Last, so it spends what the earlier sources left rather than competing
    # with established and behavioural signals for the budget.
    sources.append(
        AdjacentInterestSource(session=session, model_key=service.model_key, today=today, scan=scan)
    )
    base_facts = DatabaseFacts(session, service.model_key)
    facts = (
        AccountFacts(base=base_facts, session=session, user_id=user_id, now=utcnow())
        if user_id is not None
        else base_facts
    )
    base_weights = weights_for(preferences)
    learned = (
        {
            row.feature_name: min(
                2.0, max(0.0, base_weights.values[row.feature_name] + row.weight)
            )
            for row in session.scalars(
                select(RankerWeight).where(RankerWeight.user_id == user_id)
            ).all()
            if row.feature_name in base_weights.values
        }
        if user_id is not None
        else {}
    )
    ranker_weights = Weights({**base_weights.values, **learned}) if learned else base_weights
    return build_feed(
        built.encoded,
        sources,
        facts,
        today=today,
        config=FeedConfig(
            limit=limit,
            budget=CandidateBudget(total=PREVIEW_BUDGET, exploration_share=preferences.exploration),
            diversity=DiversityPolicy(exploration_share=preferences.exploration),
        ),
        # The reader's appetite for new work, translated where weights are
        # understood rather than here.
        ranker=DeterministicRanker(weights=ranker_weights),
    )


def _items(session: Session, feed: FeedResult) -> list[wire.PreviewItemOut]:
    summaries = repository.summaries_for_ids(session, feed.paper_ids())
    items: list[wire.PreviewItemOut] = []
    for item in feed.items:
        row = summaries.get(item.paper_id)
        if row is None:
            # Deleted between ranking and projection. Dropped rather than shown
            # as a placeholder, exactly as `/search` does.
            continue
        items.append(
            wire.PreviewItemOut(
                rank=len(items) + 1,
                paper=_summary(row),
                matched_interest=item.matched_interest,
                matched_interest_key=item.scored.matched_interest_key,
                reasons=list(item.reasons),
                is_exploration=item.is_exploration,
                is_retracted=item.is_retracted,
            )
        )
    return items


# --- projections --------------------------------------------------------------


def _draft_from(body: wire.DraftIn) -> ProfileDraft:
    return ProfileDraft(
        fields=tuple(body.fields),
        interests=tuple(
            TextInterest(
                text=item.text,
                importance=item.importance,
                horizon=item.horizon,
                label=item.label,
            )
            for item in body.interests
        ),
        example_papers=tuple(
            ExamplePaper(
                paper_id=item.paper_id,
                importance=item.importance,
                horizon=item.horizon,
                label=item.label,
            )
            for item in body.example_papers
        ),
        negatives=tuple(
            NegativeInterest(text=item.text, strength=item.strength, label=item.label)
            for item in body.negatives
        ),
        negative_papers=tuple(
            NegativePaper(paper_id=item.paper_id, strength=item.strength, label=item.label)
            for item in body.negative_papers
        ),
        blocked_topics=tuple(body.blocked_topics),
        discovery=DiscoveryChoices(
            freshness=body.discovery.freshness,
            exploration=body.discovery.exploration,
            publication=body.discovery.publication,
        ),
    )


def _draft_to(draft: ProfileDraft) -> wire.DraftIn:
    return wire.DraftIn(
        fields=list(draft.fields),
        interests=[
            wire.InterestIn(
                text=item.text,
                importance=item.importance,
                horizon=item.horizon,
                label=item.label,
            )
            for item in draft.interests
        ],
        example_papers=[
            wire.ExamplePaperIn(
                paper_id=item.paper_id,
                importance=item.importance,
                horizon=item.horizon,
                label=item.label,
            )
            for item in draft.example_papers
        ],
        negatives=[
            wire.NegativeIn(text=item.text, strength=item.strength, label=item.label)
            for item in draft.negatives
        ],
        negative_papers=[
            wire.NegativePaperIn(paper_id=item.paper_id, strength=item.strength, label=item.label)
            for item in draft.negative_papers
        ],
        blocked_topics=list(draft.blocked_topics),
        discovery=wire.DiscoveryIn(
            freshness=draft.discovery.freshness,
            exploration=draft.discovery.exploration,
            publication=draft.discovery.publication,
        ),
    )


def _profile_out(built: BuildResult, summary: ProfileSummary, model_key: str) -> wire.ProfileOut:
    return wire.ProfileOut(
        schema_version=PROFILE_SCHEMA_VERSION,
        model_key=model_key,
        interests=[
            wire.ProfileInterestOut(
                key=interest.key,
                label=interest.label,
                kind=interest.kind.value,
                polarity=interest.polarity.value,
                # A word, never the weight. The weight is the ranker's unit and
                # would be a number no reader can calibrate.
                level=(
                    IMPORTANCE_LABEL[importance_for_weight(interest.weight)]
                    if interest.polarity is Polarity.POSITIVE
                    else AVOIDANCE_LABEL[avoidance_for_weight(interest.weight)]
                ),
                horizon=interest.horizon,
                provenance=interest.provenance,
            )
            for interest in built.profile.interests
        ],
        preferences=[
            wire.PreferenceOut(label=label, value=value) for label, value in summary.preferences
        ],
        blocked_topics=sorted(built.profile.blocked_topics),
        peer_reviewed_only=built.profile.require_peer_reviewed,
    )


def _summary_out(summary: ProfileSummary) -> wire.SummaryOut:
    return wire.SummaryOut(
        sections=[
            wire.SectionOut(heading=section.heading, items=list(section.items))
            for section in summary.sections()
        ],
        preferences=[
            wire.PreferenceOut(label=label, value=value) for label, value in summary.preferences
        ],
    )


def _issue(issue: DraftIssue) -> wire.IssueOut:
    return wire.IssueOut(
        code=issue.code,
        message=issue.message,
        severity=issue.severity,
        subject=issue.subject,
    )


def _options(labels: Mapping[Any, str]) -> list[wire.LevelOption]:
    return [wire.LevelOption(value=str(level), label=label) for level, label in labels.items()]
