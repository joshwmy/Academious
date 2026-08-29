"""Interactive relevance labelling.

Walks the unjudged rows of a pool file and asks for a grade. The file is written
after **every** answer, not at the end, because judging is slow human work and
losing an hour of it to a closed terminal would be unforgivable. Quitting,
Ctrl-C and Ctrl-D all leave the file complete and consistent.

    python -m academious.workers label --judge joshua

Hand-editing the JSONL is equally valid and always was; this exists because
several hundred judgments are tedious to enter that way, not because the format
needs a tool.
"""

from __future__ import annotations

from pathlib import Path

from academious.core.logging import get_logger
from academious.eval import judgments as judgments_module
from academious.eval.queries import BY_ID

log = get_logger(__name__)

PROMPT = "grade [0-3], (s)kip, (q)uit > "


def _describe(judgment: judgments_module.Judgment, position: int, total: int) -> str:
    query = BY_ID.get(judgment.query_id)
    query_text = query.text if query else judgment.query_id
    lines = [
        "",
        "-" * 78,
        f"[{position}/{total}]  query: {query_text}",
    ]
    if query is not None:
        lines.append(f"          intent: {query.intent}")
    lines.append("")
    lines.append(f"  {judgment.title}")
    if judgment.canonical_doi:
        lines.append(f"  doi: {judgment.canonical_doi}")
    lines.append(f"  retrieved by: {', '.join(judgment.retrieved_by) or 'unknown'}")
    lines.append("")
    return "\n".join(lines)


def run(judgments_path: Path, *, judge: str, query_id: str | None = None) -> int:
    """Prompt for grades until the pool is judged or the user stops. Returns count."""
    pool = judgments_module.read(judgments_path)
    if not pool:
        print(f"No pool at {judgments_path}. Run `evaluate` first to build one.")
        return 0

    pending = [
        judgment
        for judgment in judgments_module.iter_unjudged(pool)
        if query_id is None or judgment.query_id == query_id
    ]
    if not pending:
        judged, total = judgments_module.coverage(pool)
        print(f"Nothing left to judge ({judged} of {total} already graded).")
        return 0

    print(f"{len(pending)} papers to judge. The file is saved after every answer.")
    for grade, meaning in sorted(judgments_module.describe_scale().items()):
        print(f"  {grade} = {meaning}")

    graded = 0
    for position, judgment in enumerate(pending, start=1):
        print(_describe(judgment, position, len(pending)))
        while True:
            try:
                answer = input(PROMPT).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                answer = "q"
            if answer in {"q", "quit"}:
                print(f"Stopped. {graded} judgments recorded in {judgments_path}.")
                return graded
            if answer in {"s", "skip", ""}:
                break
            if answer in {"0", "1", "2", "3"}:
                judgments_module.stamp(judgment, int(answer), judge)
                judgments_module.write(judgments_path, pool)
                graded += 1
                break
            print("  expected 0, 1, 2, 3, s to skip, or q to quit")

    judged, total = judgments_module.coverage(pool)
    print(f"\nDone. {graded} judgments this session; {judged} of {total} pooled papers graded.")
    print("Re-run `evaluate` to see the metrics.")
    return graded
