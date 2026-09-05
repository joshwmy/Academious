"""Benchmark profiles: readers to evaluate a feed against.

**A profile is not a query, which is why this file exists.** `queries.py` holds
twelve research-interest strings, each answered in isolation. A reader is
several interests at once, with weights, dislikes and preferences, and the
questions a feed has to answer - did the second interest get representation, did
the dislike suppress anything, is the list varied - cannot be asked of a single
query at all. Scoring a feed with the query benchmark would measure the wrong
thing while looking rigorous.

**Six profiles, deliberately.** Each one is human judging work at pool depth,
and `evaluation.md` is explicit that a benchmark nobody labels measures nothing.
Six covers the shapes that behave differently: a narrow specialist, a broad
generalist, an interdisciplinary reader whose interests genuinely overlap, one
with a strong dislike, one with a short-term focus over a long-term background,
and one who stated no free text at all.

**Ground truth is not in this file.** These define *who is asking*. What counts
as a good answer comes from a person judging pooled results, exactly as for
retrieval. Any number produced before that judging exists describes the feed
rather than measuring its quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from academious.personalise.profile import (
    Horizon,
    Interest,
    InterestKind,
    InterestProfile,
    Polarity,
    Preferences,
)


class ProfileShape(StrEnum):
    """What each profile is built to expose.

    Recorded so a surprising result can be checked against what the profile was
    for, the way `BenchmarkQuery.intent` is used for retrieval.
    """

    SPECIALIST = "specialist"
    GENERALIST = "generalist"
    INTERDISCIPLINARY = "interdisciplinary"
    OPINIONATED = "opinionated"
    DRIFTING = "drifting"
    NO_FREE_TEXT = "no_free_text"


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    """One reader, and what evaluating against them is meant to reveal."""

    id: str
    shape: ProfileShape
    #: What this profile probes, in a sentence.
    intent: str
    profile: InterestProfile
    #: Interests expected to earn representation in a good feed. Not ground
    #: truth about papers - a statement about balance, checkable without anyone
    #: judging a single paper.
    expect_represented: tuple[str, ...] = ()
    notes: str = ""


def _stated(key: str, label: str, text: str, **overrides: Any) -> Interest:
    return Interest(key=key, kind=InterestKind.STATED, label=label, text=text, **overrides)


def _topic(key: str, label: str, value: str) -> Interest:
    return Interest(key=key, kind=InterestKind.TOPIC, label=label, value=value)


def _field(key: str, label: str, value: str) -> Interest:
    return Interest(key=key, kind=InterestKind.FIELD, label=label, value=value)


PROFILES: tuple[BenchmarkProfile, ...] = (
    BenchmarkProfile(
        id="rec-01",
        shape=ProfileShape.SPECIALIST,
        intent="One narrow interest. The feed should be deep rather than broad, "
        "and diversity must not force in weaker off-topic work.",
        profile=InterestProfile(
            interests=(
                _stated(
                    "rag",
                    "retrieval-augmented generation",
                    "retrieval augmented generation for large language models, "
                    "including retrievers, rerankers and grounding",
                ),
            )
        ),
        expect_represented=("rag",),
    ),
    BenchmarkProfile(
        id="rec-02",
        shape=ProfileShape.GENERALIST,
        intent="Three unrelated interests of equal weight. The averaged-vector "
        "failure mode produces a feed relevant to none of them.",
        profile=InterestProfile(
            interests=(
                _stated(
                    "sys",
                    "AI systems",
                    "efficient inference, serving and systems engineering for "
                    "machine learning models",
                ),
                _stated(
                    "onc",
                    "cancer genomics",
                    "tumour evolution, somatic mutation and cancer genomics",
                ),
                _stated(
                    "clim",
                    "climate policy",
                    "carbon pricing, emissions policy and climate economics",
                ),
            )
        ),
        expect_represented=("sys", "onc", "clim"),
        notes="The profile that fails loudest if interests are ever averaged.",
    ),
    BenchmarkProfile(
        id="rec-03",
        shape=ProfileShape.INTERDISCIPLINARY,
        intent="Two interests that genuinely overlap. Attribution should be "
        "stable rather than flickering between them for near-identical papers.",
        profile=InterestProfile(
            interests=(
                _stated(
                    "mlbio",
                    "machine learning for biology",
                    "deep learning applied to genomics, protein structure and "
                    "biological sequence data",
                ),
                _stated(
                    "bioinf",
                    "computational biology methods",
                    "algorithms and statistical methods for biological sequence "
                    "analysis",
                ),
            )
        ),
        expect_represented=("mlbio", "bioinf"),
    ),
    BenchmarkProfile(
        id="rec-04",
        shape=ProfileShape.OPINIONATED,
        intent="A strong interest and an explicit dislike inside one broad area. "
        "Tests that a negative suppresses without emptying the feed.",
        profile=InterestProfile(
            interests=(
                _stated(
                    "llm",
                    "language model evaluation",
                    "benchmarking, evaluation and safety assessment of large "
                    "language models",
                ),
                _stated(
                    "imggen",
                    "image generation",
                    "diffusion models and generative image synthesis",
                    polarity=Polarity.NEGATIVE,
                ),
            )
        ),
        expect_represented=("llm",),
        notes="The dislike is adjacent to the interest, which is the hard case: "
        "a dislike about something the reader never sees is untested.",
    ),
    BenchmarkProfile(
        id="rec-05",
        shape=ProfileShape.DRIFTING,
        intent="A long-term background with a short-term focus. This week's "
        "reading should show without the year's interest disappearing.",
        profile=InterestProfile(
            interests=(
                _stated(
                    "dist",
                    "distributed systems",
                    "consensus, replication and fault tolerance in distributed systems",
                ),
                _stated(
                    "vec",
                    "vector databases",
                    "approximate nearest neighbour search and vector database indexing",
                    horizon=Horizon.SHORT,
                    weight=1.5,
                ),
            ),
            preferences=Preferences(recency_of_interest=0.65),
        ),
        expect_represented=("dist", "vec"),
    ),
    BenchmarkProfile(
        id="rec-06",
        shape=ProfileShape.NO_FREE_TEXT,
        intent="A reader who only ticked boxes at signup. The cold-start floor: "
        "if this produces nothing, onboarding cannot be a topic picker.",
        profile=InterestProfile(
            interests=(
                _field("f-cs", "Computer science", "computer-science"),
                _topic("t-ml", "Machine learning", "T11689"),
            )
        ),
        expect_represented=("f-cs", "t-ml"),
        notes="Exercises ExactMatchSource alone - the semantic source has "
        "nothing to encode.",
    ),
)

_BY_ID = {profile.id: profile for profile in PROFILES}


def get(profile_id: str) -> BenchmarkProfile:
    if profile_id not in _BY_ID:
        raise KeyError(f"unknown benchmark profile {profile_id!r}")
    return _BY_ID[profile_id]


def by_shape(shape: ProfileShape) -> tuple[BenchmarkProfile, ...]:
    return tuple(profile for profile in PROFILES if profile.shape is shape)
