"""Ad-hoc search from the command line.

There is no user interface in Phase 2, so this is how retrieval is actually
looked at. It prints the raw method-native score and the retraction status,
because the point of inspecting results by hand is to see what the ranker did,
not a tidied-up version of it.
"""

from __future__ import annotations

from datetime import date

from academious.db.session import session_scope
from academious.retrieval.filters import PreprintPolicy, RetractionPolicy, SearchFilters
from academious.retrieval.service import RetrievalService
from academious.retrieval.types import RetrievalResult
from academious.workers import embed as embed_worker


def build_filters(
    *,
    published_from: date | None = None,
    published_to: date | None = None,
    sources: tuple[str, ...] = (),
    fields: tuple[str, ...] = (),
    preprints: str = "any",
    peer_reviewed_only: bool = False,
    open_access_only: bool = False,
    include_retracted: bool = False,
    only_flagged: bool = False,
) -> SearchFilters:
    if only_flagged:
        retraction = RetractionPolicy.ONLY_FLAGGED
    elif include_retracted:
        retraction = RetractionPolicy.INCLUDE_ALL
    else:
        retraction = RetractionPolicy.EXCLUDE_RETRACTED

    return SearchFilters(
        published_from=published_from,
        published_to=published_to,
        sources=sources,
        fields=fields,
        preprints=PreprintPolicy(preprints),
        peer_reviewed_only=peer_reviewed_only,
        open_access_only=open_access_only,
        retraction=retraction,
    )


def run(
    query: str,
    *,
    method: str = "hybrid",
    limit: int = 20,
    profile_key: str | None = None,
    search_filters: SearchFilters | None = None,
) -> RetrievalResult:
    profile = embed_worker.resolve_profile(profile_key)
    backend = embed_worker.build(profile)
    service = RetrievalService(backend=backend, model_key=profile.key)

    with session_scope() as session:
        result = service.search_by_interest(
            session,
            query,
            limit=limit,
            method=method,
            search_filters=search_filters,
        )

    print(render(result))
    return result


def render(result: RetrievalResult) -> str:
    lines = [
        f"query : {result.query}",
        f"method: {result.method}  ({result.elapsed_ms:.1f} ms, "
        f"{result.candidates_considered} candidates)",
        "",
    ]
    if not result.hits:
        lines.append("  no results")
        return "\n".join(lines)

    for hit in result.hits:
        flags = []
        if hit.is_preprint:
            flags.append("preprint")
        if hit.retraction_status != "none":
            flags.append(hit.retraction_status.upper())
        if hit.oa_status not in ("unknown", "closed"):
            flags.append(f"oa:{hit.oa_status}")
        suffix = ("  [" + ", ".join(flags) + "]") if flags else ""
        published = hit.published_date.isoformat() if hit.published_date else "----------"
        lines.append(f"{hit.rank:3}. {hit.score:8.4f}  {published}  {hit.title[:64]}{suffix}")
        if hit.components:
            parts = ", ".join(
                f"{name}={value:.4f}" for name, value in sorted(hit.components.items())
            )
            lines.append(f"       via {parts}")
    lines.append("")
    lines.append(f"scores are raw {result.hits[0].score_kind}, not calibrated relevance")
    return "\n".join(lines)
