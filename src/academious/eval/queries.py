"""The Phase 2 benchmark query set.

Twelve research-interest descriptions, six per launch domain. They are phrased
the way a researcher describes what they work on, not the way a paper titles
itself - which is the whole point, because the gap between those two phrasings
is what semantic retrieval is supposed to close and lexical search is expected
to struggle with.

The set is deliberately small. Every query in it has to be judged by a human,
and twelve queries at a pool depth of twenty is already several hundred
judgments. A larger set that nobody labels measures nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Domain(StrEnum):
    BIOMEDICAL = "biomedical"
    COMPUTING = "computing"


@dataclass(frozen=True, slots=True)
class BenchmarkQuery:
    id: str
    text: str
    domain: Domain
    #: Why this query is in the set - what it is meant to expose.
    intent: str


BIOMEDICAL: tuple[BenchmarkQuery, ...] = (
    BenchmarkQuery(
        "bio-01",
        "cancer genomics machine learning",
        Domain.BIOMEDICAL,
        "cross-disciplinary: method vocabulary from computing, subject from oncology",
    ),
    BenchmarkQuery(
        "bio-02",
        "transcriptomic biomarkers in breast cancer",
        Domain.BIOMEDICAL,
        "narrow and specific; tests precision rather than coverage",
    ),
    BenchmarkQuery(
        "bio-03",
        "Alzheimer's disease genetics",
        Domain.BIOMEDICAL,
        "short, high-volume topic; tests ranking when thousands of papers match",
    ),
    BenchmarkQuery(
        "bio-04",
        "deep learning medical imaging",
        Domain.BIOMEDICAL,
        "method-led query over a clinical corpus",
    ),
    BenchmarkQuery(
        "bio-05",
        "public health diabetes risk prediction",
        Domain.BIOMEDICAL,
        "three concepts that rarely co-occur in one title; lexical search should suffer",
    ),
    BenchmarkQuery(
        "bio-06",
        "computational drug discovery",
        Domain.BIOMEDICAL,
        "field-level query whose literature uses many different surface terms",
    ),
)

COMPUTING: tuple[BenchmarkQuery, ...] = (
    BenchmarkQuery(
        "cs-01",
        "large language model code generation",
        Domain.COMPUTING,
        "fast-moving topic; tests whether recent preprints surface",
    ),
    BenchmarkQuery(
        "cs-02",
        "retrieval augmented generation",
        Domain.COMPUTING,
        "an established term of art; lexical search should do well, a useful control",
    ),
    BenchmarkQuery(
        "cs-03",
        "reinforcement learning robotics",
        Domain.COMPUTING,
        "two broad fields whose intersection is the actual interest",
    ),
    BenchmarkQuery(
        "cs-04",
        "efficient transformer inference",
        Domain.COMPUTING,
        "systems framing; 'efficient' is a weak lexical signal and a strong semantic one",
    ),
    BenchmarkQuery(
        "cs-05",
        "graph neural networks",
        Domain.COMPUTING,
        "an exact architecture name; near-perfect lexical match expected",
    ),
    BenchmarkQuery(
        "cs-06",
        "AI safety evaluation",
        Domain.COMPUTING,
        "young field with unsettled vocabulary; the hardest case for lexical search",
    ),
)

ALL_QUERIES: tuple[BenchmarkQuery, ...] = BIOMEDICAL + COMPUTING

BY_ID = {query.id: query for query in ALL_QUERIES}


def get(query_id: str) -> BenchmarkQuery:
    try:
        return BY_ID[query_id]
    except KeyError:
        raise KeyError(f"unknown benchmark query {query_id!r}") from None
