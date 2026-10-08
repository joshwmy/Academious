"""Draft in, canonical `InterestProfile` out. The translation, in one place.

Everything this module does is decided elsewhere and performed here: `draft.py`
says what the reader chose, `levels.py` says what each choice is worth, and this
turns the pair into interests the recommender already knows how to consume. It
introduces no new recommender concept, which is the test of whether the split
was drawn in the right place.

**Every interest keeps its provenance and a stable key.** The key is derived
from the reader's own words rather than allocated, so refining a draft twice
produces the same keys twice - which is what lets a refinement strengthen an
existing interest instead of appending a near-duplicate, and what lets a feed
attribute an item to something the reader can still recognise.

**Text is encoded once per distinct string, in one call.** A reader who lists
five interests pays for one batch, not five, and a draft that repeats a phrase
across the positive/negative boundary pays for it once. That matters at the API
boundary because encoding is the only part of profile building that costs real
time.

**Example papers reuse the embedding the corpus already holds.** Encoding a
title as free text would produce a worse vector than the paper's own - the
document adapter saw the abstract, the query adapter would not - and would throw
away the provenance that lets an explanation say *similar to a paper you chose*.
A paper with no embedding is reported and dropped rather than silently replaced
by its title.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from academious.ingest import taxonomy
from academious.onboarding.draft import (
    DraftIssue,
    ProfileDraft,
    Severity,
    canonical,
    errors,
    validate,
)
from academious.onboarding.levels import (
    AVOIDANCE_WEIGHT,
    IMPORTANCE_WEIGHT,
    Provenance,
    preferences_for,
    requires_peer_review,
)
from academious.personalise.profile import (
    EncodedProfile,
    Interest,
    InterestKind,
    InterestProfile,
    Polarity,
    ProfileError,
)

#: Longest generated interest key. Keys are readable on purpose - they appear in
#: diagnostics, in feedback events and in a client's own state - so they are
#: derived from the reader's words, and trimmed so one long interest cannot
#: produce an unwieldy identifier.
MAX_KEY_CHARS = 64


class BuildError(ValueError):
    """A draft that cannot become a profile. Carries every reason, not the first."""

    def __init__(self, issues: Sequence[DraftIssue]) -> None:
        super().__init__("; ".join(issue.message for issue in issues))
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class PaperReference:
    """What profile building needs to know about a chosen paper."""

    paper_id: uuid.UUID
    title: str | None = None
    vector: np.ndarray | None = None


#: Resolves chosen papers to their titles and stored embeddings. A callable so
#: the builder runs against a dictionary in a test and against PostgreSQL in
#: production by the same code path - the choice `feed.FactsProvider` makes, for
#: the same reason.
PaperVectors = Callable[[Sequence[uuid.UUID]], Mapping[uuid.UUID, PaperReference]]

#: Encodes research-interest text. Wraps `EmbeddingBackend.encode_queries`
#: rather than `encode_documents`: an interest is a short description of what
#: someone wants, which is what SPECTER2's ad-hoc query adapter is for
#: (ADR 0006), and it is the adapter `/search` already uses - so an interest and
#: a search for the same words land in the same place.
TextEncoder = Callable[[Sequence[str]], Sequence[np.ndarray]]


@dataclass(frozen=True, slots=True)
class BuildResult:
    """A built profile, and everything that had to be said about building it."""

    draft: ProfileDraft
    profile: InterestProfile
    encoded: EncodedProfile
    issues: tuple[DraftIssue, ...] = ()

    @property
    def warnings(self) -> tuple[DraftIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)


@dataclass(frozen=True, slots=True)
class ProfileBuilder:
    """Turns drafts into profiles under one embedding model.

    `model_key` travels with the builder for the same reason it travels with
    `RetrievalService`: a profile encoded under one model says nothing about a
    corpus embedded under another, and the mismatch produces plausible nonsense
    rather than an error.
    """

    encode: TextEncoder
    papers: PaperVectors
    model_key: str
    #: Stamped on every interest, so a profile carries when it was stated. Not
    #: `datetime.now` by default: a builder whose output depends on the clock
    #: cannot be tested for determinism.
    now: datetime | None = None

    def build(self, draft: ProfileDraft) -> BuildResult:
        """Validate, encode and assemble. Raises `BuildError` on any error issue."""
        cleaned, issues = validate(draft)
        problems = errors(issues)
        if problems:
            raise BuildError(problems)

        collected = list(issues)
        interests: list[Interest] = []
        interests.extend(_field_interests(cleaned))
        interests.extend(self._text_interests(cleaned))
        interests.extend(self._paper_interests(cleaned, collected))

        if not any(interest.polarity is Polarity.POSITIVE for interest in interests):
            # Reachable only by losing every example paper to a missing
            # embedding, which validation cannot foresee because it does not
            # touch the corpus. Refused with the reason rather than with a
            # ProfileError about an empty profile.
            raise BuildError(
                (
                    *collected,
                    DraftIssue(
                        code="no_usable_positive_interest",
                        message=(
                            "None of the chosen papers can be matched against, so the "
                            "profile has nothing positive left. Add an interest in words."
                        ),
                    ),
                )
            )

        profile = InterestProfile(
            interests=tuple(interests),
            preferences=preferences_for(
                freshness=cleaned.discovery.freshness,
                exploration=cleaned.discovery.exploration,
                publication=cleaned.discovery.publication,
            ),
            blocked_topics=frozenset(cleaned.blocked_topics),
            require_peer_reviewed=requires_peer_review(cleaned.discovery.publication),
        )
        try:
            encoded = EncodedProfile(profile=profile, model_key=self.model_key)
        except ProfileError as error:  # pragma: no cover - defensive
            raise BuildError(
                (DraftIssue(code="unbuildable_profile", message=str(error)),)
            ) from error

        return BuildResult(draft=cleaned, profile=profile, encoded=encoded, issues=tuple(collected))

    # -- stages ---------------------------------------------------------------

    def _text_interests(self, draft: ProfileDraft) -> list[Interest]:
        """Positive and negative free text, encoded together in one call."""
        texts = [interest.text for interest in draft.interests]
        texts += [negative.text for negative in draft.negatives]
        if not texts:
            return []

        # One vector per distinct string. Interests sharing a canonical form
        # were already merged within their polarity, but a positive and a
        # negative can still be worded identically, and encoding that twice
        # would pay twice for one answer.
        distinct = list(dict.fromkeys(texts))
        vectors = list(self.encode(distinct))
        if len(vectors) != len(distinct):
            raise BuildError(
                (
                    DraftIssue(
                        code="encoder_returned_wrong_count",
                        message=(
                            f"The embedding backend returned {len(vectors)} vectors for "
                            f"{len(distinct)} interests."
                        ),
                    ),
                )
            )
        by_text = dict(zip(distinct, vectors, strict=True))

        built: list[Interest] = [
            Interest(
                key=_key("i", interest.text),
                kind=InterestKind.STATED,
                label=interest.display,
                text=interest.text,
                vector=np.asarray(by_text[interest.text], dtype=np.float32),
                weight=IMPORTANCE_WEIGHT[interest.importance],
                horizon=interest.horizon,
                provenance=str(Provenance.EXPLICIT_TEXT),
                created_at=self.now,
            )
            for interest in draft.interests
        ]
        built.extend(
            Interest(
                key=_key("n", negative.text),
                kind=InterestKind.STATED,
                label=negative.display,
                text=negative.text,
                vector=np.asarray(by_text[negative.text], dtype=np.float32),
                weight=AVOIDANCE_WEIGHT[negative.strength],
                polarity=Polarity.NEGATIVE,
                provenance=str(Provenance.EXPLICIT_TEXT),
                created_at=self.now,
            )
            for negative in draft.negatives
        )
        return built

    def _paper_interests(self, draft: ProfileDraft, issues: list[DraftIssue]) -> list[Interest]:
        chosen = [paper.paper_id for paper in draft.example_papers]
        chosen += [paper.paper_id for paper in draft.negative_papers]
        if not chosen:
            return []

        found = self.papers(chosen)
        built: list[Interest] = []

        for paper in draft.example_papers:
            reference = _usable(paper.paper_id, found, issues)
            if reference is None:
                continue
            built.append(
                Interest(
                    key=_paper_key("p", paper.paper_id),
                    kind=InterestKind.PAPER,
                    label=paper.label or reference.title or "a paper you chose",
                    vector=np.asarray(reference.vector, dtype=np.float32),
                    weight=IMPORTANCE_WEIGHT[paper.importance],
                    horizon=paper.horizon,
                    provenance=f"{Provenance.EXAMPLE_PAPER}:{paper.paper_id}",
                    created_at=self.now,
                )
            )

        for unwanted in draft.negative_papers:
            reference = _usable(unwanted.paper_id, found, issues)
            if reference is None:
                continue
            built.append(
                Interest(
                    key=_paper_key("np", unwanted.paper_id),
                    kind=InterestKind.PAPER,
                    label=unwanted.label or reference.title or "a paper you set aside",
                    vector=np.asarray(reference.vector, dtype=np.float32),
                    weight=AVOIDANCE_WEIGHT[unwanted.strength],
                    polarity=Polarity.NEGATIVE,
                    provenance=f"{Provenance.EXAMPLE_PAPER}:{unwanted.paper_id}",
                    created_at=self.now,
                )
            )
        return built


def _field_interests(draft: ProfileDraft) -> list[Interest]:
    """Broad areas, as exact-match interests over the canonical vocabulary.

    Weight 1.0 for all of them: a broad area carries no importance level (see
    `ProfileDraft.fields`), and inventing a spread between areas the reader
    ranked equally would be inventing a preference.
    """
    return [
        Interest(
            key=_key("f", slug),
            kind=InterestKind.FIELD,
            label=taxonomy.BY_SLUG[slug].label,
            value=slug,
            provenance=str(Provenance.SELECTED_FIELD),
        )
        for slug in draft.fields
    ]


def _usable(
    paper_id: uuid.UUID,
    found: Mapping[uuid.UUID, PaperReference],
    issues: list[DraftIssue],
) -> PaperReference | None:
    """The reference for one chosen paper, or a reported reason there is none.

    Two different failures, told apart because a reader can act on one of them:
    a paper that is not in the corpus was chosen wrongly, while a paper waiting
    on the embedding backlog will work later and is worth keeping in the draft.
    """
    reference = found.get(paper_id)
    if reference is None:
        issues.append(
            DraftIssue(
                code="unknown_example_paper",
                message="That paper is not in the corpus, so it cannot be used as an example.",
                severity=Severity.WARNING,
                subject=str(paper_id),
            )
        )
        return None
    if reference.vector is None:
        issues.append(
            DraftIssue(
                code="example_paper_not_embedded",
                message=(
                    f"{reference.title or 'That paper'} has not been embedded yet, so it "
                    "cannot steer recommendations. It has been left out of the profile."
                ),
                severity=Severity.WARNING,
                subject=str(paper_id),
            )
        )
        return None
    return reference


def interest_key(text: str) -> str:
    """The key a stated interest with this text will carry.

    Public because refinement has to work the other way round: a preview names
    the interest that earned an item, and the correction has to find the draft
    entry behind it. Deriving the key in both directions from the same function
    is what keeps that lookup from becoming a second, divergent convention.
    """
    return _key("i", text)


def negative_interest_key(text: str) -> str:
    return _key("n", text)


def field_key(slug: str) -> str:
    return _key("f", slug)


def example_paper_key(paper_id: uuid.UUID) -> str:
    return _paper_key("p", paper_id)


def negative_paper_key(paper_id: uuid.UUID) -> str:
    return _paper_key("np", paper_id)


def _key(prefix: str, text: str) -> str:
    """A stable, readable key from the reader's own words.

    Derived rather than allocated, so building the same draft twice - which
    happens on every refinement round trip - produces the same keys, and a
    refinement can find the interest it means to change.
    """
    slug = canonical(text).replace(" ", "-")[: MAX_KEY_CHARS - len(prefix) - 1]
    return f"{prefix}-{slug}" if slug else f"{prefix}-{len(text)}"


def _paper_key(prefix: str, paper_id: uuid.UUID) -> str:
    return f"{prefix}-{paper_id.hex[:12]}"
