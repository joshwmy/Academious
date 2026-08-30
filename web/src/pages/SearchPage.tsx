/**
 * Search results for `?q=`.
 *
 * The query lives in the URL and nowhere else, which makes a result page
 * shareable and makes the back button work without any state restoration logic.
 *
 * Results render in the order the backend returned them and are never re-sorted
 * here. The ranking is the product; a client-side sort would silently replace a
 * measured ordering with an arbitrary one.
 */

import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { MAX_QUERY_LENGTH, searchPapers } from "../api/client";
import { PaperCard } from "../components/PaperCard";
import { EmptyState, ErrorState, LoadingRegion, PaperListSkeleton } from "../components/States";
import { useRequest } from "../hooks/useRequest";
import "./Page.css";

const RESULT_LIMIT = 20;

export function SearchPage() {
  const [searchParams] = useSearchParams();
  const rawQuery = searchParams.get("q") ?? "";
  const query = rawQuery.trim();
  const isSearchable = query !== "" && query.length <= MAX_QUERY_LENGTH;

  const run = useCallback(
    (signal: AbortSignal) => searchPapers({ q: query, limit: RESULT_LIMIT }, signal),
    [query],
  );
  const { state, retry } = useRequest(run, isSearchable);

  if (!isSearchable) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">Search</h1>
        </header>
        <EmptyState title={query === "" ? "Enter a search" : "That query is too long"}>
          <p>
            {query === ""
              ? "Describe what you are looking for in the search box above — a topic, a method, or a research interest in your own words."
              : `Queries are limited to ${MAX_QUERY_LENGTH} characters.`}
          </p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">
          Results for <span className="page__query">{query}</span>
        </h1>
        {/* The count is a lead only when there is something to count; the
            empty state below says the rest, and saying it twice is noise. */}
        {state.status === "success" && state.data.count > 0 ? (
          <p className="page__lead">
            {state.data.count} {state.data.count === 1 ? "paper" : "papers"}, most relevant
            first.
          </p>
        ) : null}
      </header>

      {state.status === "loading" ? (
        <LoadingRegion label={`Searching for ${query}`}>
          <PaperListSkeleton count={4} />
        </LoadingRegion>
      ) : null}

      {state.status === "error" ? (
        <ErrorState error={state.error} onRetry={retry} context="search" />
      ) : null}

      {state.status === "success" ? (
        state.data.results.length === 0 ? (
          <EmptyState title="No matching papers">
            <p>
              Nothing in the Academious corpus matched that search. Academious indexes recent
              work from arXiv and bioRxiv/medRxiv, not the whole of published science, so a
              paper you expect may simply not be in it yet.
            </p>
            <p>Try broader wording, or describe the topic rather than naming an exact title.</p>
          </EmptyState>
        ) : (
          // An ordered list, because the order carries meaning.
          <ol className="paper-list" aria-label="Search results">
            {state.data.results.map((hit) => (
              <li key={hit.paper.id}>
                <PaperCard paper={hit.paper} rank={hit.rank} />
              </li>
            ))}
          </ol>
        )
      ) : null}
    </div>
  );
}
