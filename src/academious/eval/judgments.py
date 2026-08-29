"""Relevance judgments: the file a human edits, and the code that reads it.

The format is JSONL with one object per (query, paper). It is line-oriented so
that a diff shows exactly which judgments changed, sorted so that regenerating
the pool does not reshuffle the file, and it carries the paper's title and DOI
so a judge can label without a second window open.

The one rule this module enforces above all others: **existing grades are never
overwritten by pool regeneration**. Judging is the expensive input here. A
re-run that silently discarded yesterday's labels because the ranking shifted
would make the whole exercise unrepeatable.

A grade of `null` means "not yet judged" and is distinct from 0, which means
"judged, not relevant". Metrics are computed only over judged rows, and a pool
that is entirely unjudged produces no metrics at all rather than zeros.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from academious.core.clock import utcnow

GRADE_LABELS = {
    0: "not relevant",
    1: "marginal - touches the topic but is not what was asked for",
    2: "relevant",
    3: "highly relevant - a top result any expert would name",
}


@dataclass(slots=True)
class Judgment:
    query_id: str
    paper_id: str
    grade: int | None = None
    title: str = ""
    canonical_doi: str | None = None
    #: Which methods retrieved this paper, so pool bias is visible in the file.
    retrieved_by: list[str] = None  # type: ignore[assignment]
    judge: str | None = None
    judged_at: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.retrieved_by is None:
            self.retrieved_by = []

    @property
    def is_judged(self) -> bool:
        return self.grade is not None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _key(judgment: Judgment) -> tuple[str, str]:
    return (judgment.query_id, judgment.paper_id)


def read(path: Path) -> list[Judgment]:
    """Read a judgments file. A missing file is an empty list, not an error."""
    if not path.exists():
        return []
    judgments: list[Judgment] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: not valid JSON: {exc}") from exc
        try:
            judgments.append(Judgment(**payload))
        except TypeError as exc:
            # Valid JSON, wrong shape - a hand-edited file with a typo in a key.
            # Point at the offending line rather than at this module.
            raise ValueError(f"{path}:{line_number}: not a judgment: {exc}") from exc
    return judgments


def write(path: Path, judgments: Iterable[Judgment]) -> int:
    """Write judgments in a stable order. Returns how many were written."""
    ordered = sorted(judgments, key=lambda j: (j.query_id, j.title.lower(), j.paper_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(judgment.to_json() for judgment in ordered) + "\n", encoding="utf-8"
    )
    return len(ordered)


def merge(existing: Iterable[Judgment], incoming: Iterable[Judgment]) -> list[Judgment]:
    """Add newly pooled papers without disturbing any grade already recorded.

    A paper that has dropped out of the pool keeps its judgment. Judgments are
    facts about a (query, paper) pair; they do not stop being true because a
    ranking changed, and keeping them makes a later re-pool cheaper.
    """
    merged: dict[tuple[str, str], Judgment] = {_key(j): j for j in existing}
    for candidate in incoming:
        key = _key(candidate)
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
            continue
        # Refresh only the provenance and display fields.
        current.retrieved_by = sorted(set(current.retrieved_by) | set(candidate.retrieved_by))
        current.title = candidate.title or current.title
        current.canonical_doi = candidate.canonical_doi or current.canonical_doi
    return list(merged.values())


def grade_map(judgments: Iterable[Judgment]) -> dict[str, dict[uuid.UUID, int]]:
    """Judged rows only, grouped by query id, ready for the metrics module."""
    grades: dict[str, dict[uuid.UUID, int]] = {}
    for judgment in judgments:
        if judgment.grade is None:
            continue
        grades.setdefault(judgment.query_id, {})[uuid.UUID(judgment.paper_id)] = judgment.grade
    return grades


def coverage(judgments: Iterable[Judgment]) -> tuple[int, int]:
    """(judged, total) across every query. The honesty check before reporting."""
    total = 0
    judged = 0
    for judgment in judgments:
        total += 1
        judged += int(judgment.is_judged)
    return judged, total


def stamp(judgment: Judgment, grade: int, judge: str, when: datetime | None = None) -> Judgment:
    if grade not in GRADE_LABELS:
        raise ValueError(f"grade must be one of {sorted(GRADE_LABELS)}, got {grade!r}")
    judgment.grade = grade
    judgment.judge = judge
    judgment.judged_at = (when or utcnow()).isoformat()
    return judgment


def iter_unjudged(judgments: Iterable[Judgment]) -> Iterator[Judgment]:
    return (judgment for judgment in judgments if not judgment.is_judged)


def describe_scale() -> Mapping[int, str]:
    return dict(GRADE_LABELS)
