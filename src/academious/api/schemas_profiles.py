"""The wire contract for research-profile creation.

Separate from `schemas.py` because it is a different kind of contract. That file
holds *response* projections over corpus rows and exists to stop operational
columns reaching a reader. This one is a two-way contract with a client that
holds state: the draft a client posts is the draft the server returns, and it is
the artifact a client keeps between requests and could persist locally.

**These models are the profile's JSON schema.** There is no second serialiser in
`onboarding/`; a copy would drift. `PROFILE_SCHEMA_VERSION` travels on every
response so a draft stored today stays recognisable later.

**Nothing here carries a number the ranker uses.** No weights, no cosine, no
feature values, no score - not even in the preview, where the temptation is
strongest. A reader deciding whether their profile is right needs the paper and
the reason; a relevance score would be a number they cannot calibrate, attached
to a ranking whose units are diagnostics. `ScoredCandidate.contributions` exists
for developers and stops at this boundary.

Importance and avoidance arrive as words - *core*, *interested*, *avoid* - and
`onboarding/levels.py` is the only thing that knows what they are worth.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from academious.api.schemas import PaperSummary
from academious.onboarding import PROFILE_SCHEMA_VERSION
from academious.onboarding.draft import MAX_INTEREST_CHARS, Severity
from academious.onboarding.levels import (
    Avoidance,
    ExplorationLevel,
    FreshnessLevel,
    Importance,
    PublicationStage,
)
from academious.onboarding.refine import RefinementAction
from academious.personalise.profile import Horizon

#: Hard ceiling on any list in a posted draft. Deliberately looser than the
#: per-stage limits in `onboarding/draft.py`: a list of fifteen interests should
#: come back with a sentence about the limit of twelve, while a list of ten
#: thousand should be refused by the parser before any Python loop sees it.
#: The two are doing different jobs - one is a message, one is a bound.
MAX_LIST_ITEMS = 64

#: Preview size. The lower bound is not 1 because a feed of one item cannot show
#: a reader whether their profile is balanced, which is the preview's purpose.
MIN_PREVIEW = 5
MAX_PREVIEW = 30
DEFAULT_PREVIEW = 20

#: Refinements applied in one request. A handful is a person reacting to a
#: preview; hundreds is something else.
MAX_REFINEMENTS = 20


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- what the reader chose (request, and echoed back normalised) --------------


class InterestIn(_Strict):
    text: str = Field(
        min_length=1,
        max_length=MAX_INTEREST_CHARS,
        description="A research interest in your own words",
    )
    importance: Importance = Importance.INTERESTED
    horizon: Horizon = Field(
        default=Horizon.LONG,
        description=(
            "'long' for a standing interest, 'short' for something you are exploring now. "
            "Onboarding produces long; refining a preview produces short"
        ),
    )
    label: str | None = Field(default=None, max_length=MAX_INTEREST_CHARS)


class ExamplePaperIn(_Strict):
    paper_id: uuid.UUID = Field(description="An Academious paper id, found through /search")
    importance: Importance = Importance.INTERESTED
    horizon: Horizon = Horizon.LONG
    label: str | None = Field(default=None, max_length=500)


class NegativeIn(_Strict):
    text: str = Field(min_length=1, max_length=MAX_INTEREST_CHARS)
    strength: Avoidance = Avoidance.AVOID
    label: str | None = Field(default=None, max_length=MAX_INTEREST_CHARS)


class NegativePaperIn(_Strict):
    paper_id: uuid.UUID
    strength: Avoidance = Avoidance.AVOID
    label: str | None = Field(default=None, max_length=500)


class DiscoveryIn(_Strict):
    freshness: FreshnessLevel = FreshnessLevel.BALANCED
    exploration: ExplorationLevel = ExplorationLevel.BALANCED
    publication: PublicationStage = PublicationStage.INCLUDE_PREPRINTS


class DraftIn(_Strict):
    """Everything a reader chose. The client holds this between requests."""

    fields: list[str] = Field(
        default_factory=list,
        max_length=MAX_LIST_ITEMS,
        description="Broad areas, as field slugs from GET /fields",
    )
    interests: list[InterestIn] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    example_papers: list[ExamplePaperIn] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    negatives: list[NegativeIn] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    negative_papers: list[NegativePaperIn] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    blocked_topics: list[str] = Field(
        default_factory=list,
        max_length=MAX_LIST_ITEMS,
        description="Canonical topic ids to exclude outright",
    )
    discovery: DiscoveryIn = Field(default_factory=DiscoveryIn)


class RefinementIn(_Strict):
    action: RefinementAction
    paper_id: uuid.UUID | None = None
    interest_key: str | None = Field(
        default=None,
        max_length=128,
        description="The `matched_interest_key` the preview reported for this item",
    )
    topic_id: str | None = Field(default=None, max_length=128)
    label: str | None = Field(default=None, max_length=500)


class PreviewRequest(_Strict):
    draft: DraftIn
    limit: int = Field(default=DEFAULT_PREVIEW, ge=MIN_PREVIEW, le=MAX_PREVIEW)


class RefineRequest(_Strict):
    draft: DraftIn
    refinements: list[RefinementIn] = Field(min_length=1, max_length=MAX_REFINEMENTS)
    limit: int = Field(default=DEFAULT_PREVIEW, ge=MIN_PREVIEW, le=MAX_PREVIEW)


# --- what the server says back ------------------------------------------------


class IssueOut(_Strict):
    code: str = Field(description="Stable identifier a client can branch on")
    message: str = Field(description="What to tell the reader")
    severity: Severity
    subject: str | None = Field(
        default=None, description="The interest or paper this is about, if one"
    )


class ProfileInterestOut(_Strict):
    """One interest as the recommender received it, described in words."""

    key: str = Field(description="Stable identity; send it back to refine this interest")
    label: str
    kind: str = Field(description="stated, paper, topic, field, author or venue")
    polarity: str = Field(description="positive or negative")
    level: str = Field(description="How much it matters, in words - never a weight")
    horizon: Horizon
    provenance: str = Field(description="Where this interest came from")


class PreferenceOut(_Strict):
    label: str
    value: str


class SectionOut(_Strict):
    heading: str
    items: list[str]


class SummaryOut(_Strict):
    """The profile as a person would describe it."""

    sections: list[SectionOut]
    preferences: list[PreferenceOut]


class ProfileOut(_Strict):
    """The canonical profile, minus the vectors it is scored with.

    Vectors are omitted on purpose rather than forgotten: 768 floats per
    interest would dominate the payload, they are derived deterministically from
    the text and paper ids that *are* here, and a client has no use for them.
    Re-posting the draft reproduces them exactly.
    """

    schema_version: int = PROFILE_SCHEMA_VERSION
    model_key: str = Field(description="The embedding model this profile was built against")
    interests: list[ProfileInterestOut]
    preferences: list[PreferenceOut]
    blocked_topics: list[str]
    peer_reviewed_only: bool


class PreviewItemOut(_Strict):
    """One previewed recommendation. No score, by design."""

    rank: int
    paper: PaperSummary
    matched_interest: str | None = Field(
        default=None, description="The interest that earned this position"
    )
    matched_interest_key: str | None = Field(
        default=None, description="Send this back with a refinement to aim it correctly"
    )
    reasons: list[str] = Field(description="Why this paper, for this reader")
    is_exploration: bool = False
    is_retracted: bool = False


class ProfileResponse(_Strict):
    """Everything one round trip of the profile builder produces."""

    schema_version: int = PROFILE_SCHEMA_VERSION
    #: The draft as it was used - deduplicated, trimmed, unknown values removed.
    #: A client should replace its own copy with this.
    draft: DraftIn
    profile: ProfileOut
    summary: SummaryOut
    preview: list[PreviewItemOut]
    issues: list[IssueOut] = Field(default_factory=list)
    changes: list[str] = Field(
        default_factory=list, description="What a refinement did, in the reader's terms"
    )


class LevelOption(_Strict):
    value: str
    label: str


class OptionsResponse(_Strict):
    """The vocabulary the profile builder accepts, so a client hardcodes nothing."""

    schema_version: int = PROFILE_SCHEMA_VERSION
    importance: list[LevelOption]
    avoidance: list[LevelOption]
    freshness: list[LevelOption]
    exploration: list[LevelOption]
    publication: list[LevelOption]
    limits: dict[str, int] = Field(
        description="Per-stage maximums, so a form can stop a reader before the server does"
    )
