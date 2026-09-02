/**
 * The feed: recent papers, newest first, exactly as `GET /papers` orders them.
 *
 * The offset and the filters both live in the URL rather than in component
 * state, so a page of results - filtered or not - is a place you can link to and
 * return to with the back button. See `lib/filters.ts` for why the query string
 * is the only place either is held.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { listPapers } from "../api/client";
import { FilterPanel } from "../components/FilterPanel";
import { PaperCard } from "../components/PaperCard";
import { Pagination } from "../components/Pagination";
import { EmptyState, ErrorState, LoadingRegion, PaperListSkeleton } from "../components/States";
import { useRequest } from "../hooks/useRequest";
import {
  NO_FILTERS,
  filtersToParams,
  filtersToSearchParams,
  hasActiveFilters,
  parseFilters,
  type PaperFilters,
} from "../lib/filters";
import "./Page.css";

/** Comfortably above the fold on a laptop, well within the backend's max of 100. */
const PAGE_SIZE = 20;

function parseOffset(raw: string | null): number {
  const value = Number.parseInt(raw ?? "0", 10);
  if (!Number.isFinite(value) || value < 0) return 0;
  // Snap to a page boundary so hand-edited URLs cannot desynchronise paging.
  return Math.floor(value / PAGE_SIZE) * PAGE_SIZE;
}

function toQuery(filters: PaperFilters, offset: number): URLSearchParams {
  const params = filtersToSearchParams(filters);
  if (offset > 0) params.set("offset", String(offset));
  return params;
}

export function FeedPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = parseOffset(searchParams.get("offset"));

  // Memoised on the query *string*, not on the params object: `useRequest`
  // treats the identity of `run` as the identity of the request, so a filter
  // object rebuilt on every render would refetch on every render.
  const query = searchParams.toString();
  const filters = useMemo(() => parseFilters(new URLSearchParams(query)), [query]);

  const run = useCallback(
    (signal: AbortSignal) =>
      listPapers({ limit: PAGE_SIZE, offset, ...filtersToParams(filters) }, signal),
    [offset, filters],
  );
  const { state, retry } = useRequest(run);

  const navigate = (nextOffset: number) => {
    setSearchParams(toQuery(filters, nextOffset));
    window.scrollTo({ top: 0 });
  };

  const changeFilters = (next: PaperFilters) => {
    // Back to the first page. Page three of an unfiltered feed is not page
    // three of a filtered one, and there may be no page three at all - keeping
    // the offset would show an empty page for results that do exist.
    setSearchParams(toQuery(next, 0));
    window.scrollTo({ top: 0 });
  };

  const filtered = hasActiveFilters(filters);

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">New research</h1>
        {/* The lead is built from the response, not written into the markup: it
            says how much literature is actually here, which is a fact about the
            corpus rather than a description of the page. */}
        <p className="page__lead">
          {state.status === "success" && state.data.page.total > 0 ? (
            <>
              <span className="page__count">{state.data.page.total.toLocaleString()}</span> papers
              from arXiv, bioRxiv/medRxiv and Europe PMC, newest first.
            </>
          ) : (
            <>Recent work from arXiv, bioRxiv/medRxiv and Europe PMC, newest first.</>
          )}
        </p>
      </header>

      <FilterPanel filters={filters} onChange={changeFilters} />

      {state.status === "loading" ? (
        <LoadingRegion label="Loading recent papers">
          <PaperListSkeleton />
        </LoadingRegion>
      ) : null}

      {state.status === "error" ? (
        <ErrorState error={state.error} onRetry={retry} context="feed" />
      ) : null}

      {state.status === "success" ? (
        state.data.results.length === 0 ? (
          // Two different situations that look identical if you only count
          // rows: nothing has been ingested, or the filters excluded it all.
          filtered ? (
            <EmptyState title="No papers match these filters">
              <p>
                Nothing in the corpus satisfies every filter you have set. Try removing one, or
                clear them all and start again.
              </p>
              <p>
                <button
                  type="button"
                  className="button"
                  onClick={() => changeFilters(NO_FILTERS)}
                >
                  Clear filters
                </button>
              </p>
            </EmptyState>
          ) : (
            <EmptyState title="No papers yet">
              <p>
                The corpus has not been populated. Once ingestion has run, recent papers appear
                here.
              </p>
            </EmptyState>
          )
        ) : (
          <>
            <ul className="paper-list" aria-label="Recent papers">
              {state.data.results.map((paper) => (
                <li key={paper.id}>
                  <PaperCard paper={paper} />
                </li>
              ))}
            </ul>
            <Pagination
              offset={state.data.page.offset}
              limit={state.data.page.limit}
              total={state.data.page.total}
              returned={state.data.page.returned}
              hasMore={state.data.page.has_more}
              onNavigate={navigate}
            />
          </>
        )
      ) : null}
    </div>
  );
}
