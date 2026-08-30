/**
 * The feed: recent papers, newest first, exactly as `GET /papers` orders them.
 *
 * `offset` lives in the URL rather than in component state so that a page of
 * results is a place you can link to and return to with the back button.
 */

import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { listPapers } from "../api/client";
import { PaperCard } from "../components/PaperCard";
import { Pagination } from "../components/Pagination";
import { EmptyState, ErrorState, LoadingRegion, PaperListSkeleton } from "../components/States";
import { useRequest } from "../hooks/useRequest";
import "./Page.css";

/** Comfortably above the fold on a laptop, well within the backend's max of 100. */
const PAGE_SIZE = 20;

function parseOffset(raw: string | null): number {
  const value = Number.parseInt(raw ?? "0", 10);
  if (!Number.isFinite(value) || value < 0) return 0;
  // Snap to a page boundary so hand-edited URLs cannot desynchronise paging.
  return Math.floor(value / PAGE_SIZE) * PAGE_SIZE;
}

export function FeedPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = parseOffset(searchParams.get("offset"));

  const run = useCallback(
    (signal: AbortSignal) => listPapers({ limit: PAGE_SIZE, offset }, signal),
    [offset],
  );
  const { state, retry } = useRequest(run);

  const navigate = (nextOffset: number) => {
    setSearchParams(nextOffset === 0 ? {} : { offset: String(nextOffset) });
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">Recent papers</h1>
        <p className="page__lead">
          The most recently published work in the Academious corpus.
        </p>
      </header>

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
          <EmptyState title="No papers yet">
            <p>
              The corpus has not been populated. Once ingestion has run, recent papers appear
              here.
            </p>
          </EmptyState>
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
