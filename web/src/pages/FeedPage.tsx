import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  getAccountFeed,
  getAccountProfile,
  listPapers,
  previewProfile,
  refineProfile,
  removeSavedPaper,
  saveAccountProfile,
  sendInteractions,
} from "../api/client";
import { ApiError } from "../api/errors";
import type { PreviewItem, ProfileDraft, ProfileResponse, RefinementAction } from "../api/types";
import { FilterPanel } from "../components/FilterPanel";
import { useAuth } from "../auth/AuthContext";
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
import {
  loadProfileDraft,
  recordInteractions,
  saveProfileDraft,
} from "../lib/profileStorage";
import "./Page.css";

export const PAGE_SIZE = 20;

/**
 * Router state a page can hand the feed: a preview it has just fetched for the
 * same draft, so first-run setup does not pay for the same ranking twice.
 */
export interface FeedHandoff {
  preview?: ProfileResponse;
}

export function FeedPage() {
  const { user } = useAuth();
  const [savedDraft] = useState(loadProfileDraft);
  const handoff = (useLocation().state as FeedHandoff | null)?.preview ?? null;
  return savedDraft || user?.is_verified ? (
    <PersonalisedFeed initialDraft={savedDraft} initialResult={handoff} account={Boolean(user?.is_verified)} />
  ) : <LatestFeed />;
}

function PersonalisedFeed({
  initialDraft,
  initialResult,
  account,
}: {
  initialDraft: ProfileDraft | null;
  initialResult: ProfileResponse | null;
  account: boolean;
}) {
  const [draft, setDraft] = useState(initialDraft);
  const [result, setResult] = useState<ProfileResponse | null>(null);
  const [feedSessionId, setFeedSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyPaper, setBusyPaper] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const accept = useCallback((response: ProfileResponse, sessionId?: string) => {
    setDraft(response.draft);
    saveProfileDraft(response.draft);
    setResult(response);
    const occurredAt = new Date().toISOString();
    recordInteractions(
      response.preview.map((item) => ({
        type: "impression",
        paper_id: item.paper.id,
        position: item.rank,
        occurred_at: occurredAt,
      })),
    );
    if (account && sessionId) {
      setFeedSessionId(sessionId);
      void sendInteractions(response.preview.map((item) => ({
        event_id: crypto.randomUUID(),
        type: "impression",
        paper_id: item.paper.id,
        position: item.rank,
        ...(item.matched_interest_key ? { interest_key: item.matched_interest_key } : {}),
        session_id: sessionId,
        occurred_at: occurredAt,
      }))).catch(() => undefined);
    }
  }, [account]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        if (account) {
          const response = await getAccountFeed(PAGE_SIZE);
          accept(response.result, response.feed_session_id);
        } else if (draft) {
          accept(await previewProfile(draft, PAGE_SIZE, signal));
        }
      } catch (cause: unknown) {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(describe(cause));
      } finally {
        setLoading(false);
      }
    },
    [accept, account, draft],
  );

  useEffect(() => {
    const controller = new AbortController();
    const initial = async () => {
      if (!account) {
        if (initialResult) accept(initialResult);
        else if (initialDraft) accept(await previewProfile(initialDraft, PAGE_SIZE, controller.signal));
        return;
      }
      try {
        const stored = await getAccountProfile();
        setDraft(stored);
        saveProfileDraft(stored);
      } catch (cause: unknown) {
        if (!(cause instanceof ApiError && cause.status === 404 && initialDraft)) throw cause;
        await saveAccountProfile(initialDraft);
      }
      const response = await getAccountFeed(PAGE_SIZE);
      accept(response.result, response.feed_session_id);
    };
    void initial()
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(describe(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accept, account, initialDraft, initialResult]);

  const feedback = async (
    item: PreviewItem,
    action: Extract<RefinementAction, "more_like_this" | "less_like_this" | "not_interested">,
  ) => {
    setBusyPaper(item.paper.id);
    setError(null);
    setMessage(null);
    recordInteractions([
      { type: action, paper_id: item.paper.id, occurred_at: new Date().toISOString() },
    ]);
    try {
      if (!draft) return;
      const response = await refineProfile(
        draft,
        [{
          action,
          paper_id: item.paper.id,
          interest_key: item.matched_interest_key ?? undefined,
          label: item.paper.title,
        }],
        PAGE_SIZE,
      );
      if (account) {
        await saveAccountProfile(response.draft);
        await sendInteractions([{
          event_id: crypto.randomUUID(),
          type: action,
          paper_id: item.paper.id,
          ...(item.matched_interest_key ? { interest_key: item.matched_interest_key } : {}),
          ...(feedSessionId ? { session_id: feedSessionId } : {}),
          occurred_at: new Date().toISOString(),
        }]);
        const refreshed = await getAccountFeed(PAGE_SIZE);
        accept(refreshed.result, refreshed.feed_session_id);
      } else {
        accept(response);
      }
      setMessage(response.changes.join(" ") || "Your recommendations have been updated.");
    } catch (cause: unknown) {
      setError(describe(cause));
    } finally {
      setBusyPaper(null);
    }
  };

  return (
    <div className="page">
      <header className="page__header page__header--with-action">
        <div>
          <h1 className="page__title">Recommended for you</h1>
          <p className="page__lead">Research tailored to your interests.</p>
        </div>
        <Link className="button button--quiet" to="/profile">Edit interests</Link>
      </header>

      {message ? <p className="feed-notice" role="status">{message}</p> : null}
      {error ? (
        <section className="state-panel state-panel--error" role="alert">
          <h2 className="state-panel__title">We could not update your feed</h2>
          <p className="state-panel__body">{error}</p>
          <button type="button" className="button" onClick={() => void load()}>Try again</button>
        </section>
      ) : null}

      {loading && !result ? (
        <LoadingRegion label="Building your recommendations"><PaperListSkeleton /></LoadingRegion>
      ) : null}

      {result && result.preview.length === 0 ? (
        <EmptyState title="No recommendations yet">
          <p>Try adding a more specific interest or including preprints in your profile.</p>
          <p><Link className="button" to="/profile">Edit my interests</Link></p>
        </EmptyState>
      ) : null}

      {result && result.preview.length > 0 ? (
        <ul className="paper-list" aria-label="Recommended papers">
          {result.preview.map((item) => (
            <li key={item.paper.id}>
              <PaperCard
                paper={item.paper}
                onOpen={() => {
                  if (!account) return;
                  void sendInteractions([{
                    event_id: crypto.randomUUID(),
                    type: "open",
                    paper_id: item.paper.id,
                    position: item.rank,
                    ...(item.matched_interest_key ? { interest_key: item.matched_interest_key } : {}),
                    ...(feedSessionId ? { session_id: feedSessionId } : {}),
                    occurred_at: new Date().toISOString(),
                  }]).catch(() => undefined);
                }}
                onBookmarkChange={(saved) => {
                  if (!account) return;
                  if (saved) {
                    void sendInteractions([{
                      event_id: crypto.randomUUID(),
                      type: "save",
                      paper_id: item.paper.id,
                      ...(item.matched_interest_key ? { interest_key: item.matched_interest_key } : {}),
                      ...(feedSessionId ? { session_id: feedSessionId } : {}),
                      occurred_at: new Date().toISOString(),
                    }]).catch(() => setError("We could not save that paper."));
                  } else {
                    void removeSavedPaper(item.paper.id).catch(() => setError("We could not remove that paper."));
                  }
                }}
                recommendation={{
                  reasons: item.reasons,
                  busy: busyPaper !== null,
                  onFeedback: (action) => void feedback(item, action),
                }}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function LatestFeed() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = parseOffset(searchParams.get("offset"));
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
    setSearchParams(toQuery(next, 0));
    window.scrollTo({ top: 0 });
  };
  const filtered = hasActiveFilters(filters);

  return (
    <div className="page">
      <header className="page__header page__header--with-action">
        <div>
          <h1 className="page__title">Latest research</h1>
          <p className="page__lead">Build a research profile to turn this into your personal feed.</p>
        </div>
        <Link className="button" to={user ? "/welcome" : "/signup"}>{user ? "Choose my interests" : "Personalise my feed"}</Link>
      </header>
      <FilterPanel filters={filters} onChange={changeFilters} />
      {state.status === "loading" ? <LoadingRegion label="Loading recent papers"><PaperListSkeleton /></LoadingRegion> : null}
      {state.status === "error" ? <ErrorState error={state.error} onRetry={retry} context="feed" /> : null}
      {state.status === "success" ? (
        state.data.results.length === 0 ? (
          filtered ? (
            <EmptyState title="No papers match these filters">
              <p>Nothing in the corpus satisfies every filter you have set.</p>
              <p><button type="button" className="button" onClick={() => changeFilters(NO_FILTERS)}>Clear filters</button></p>
            </EmptyState>
          ) : (
            <EmptyState title="No papers yet"><p>Once ingestion has run, recent papers appear here.</p></EmptyState>
          )
        ) : (
          <>
            <ul className="paper-list" aria-label="Latest papers">
              {state.data.results.map((paper) => <li key={paper.id}><PaperCard paper={paper} /></li>)}
            </ul>
            <Pagination offset={state.data.page.offset} limit={state.data.page.limit} total={state.data.page.total} returned={state.data.page.returned} hasMore={state.data.page.has_more} onNavigate={navigate} />
          </>
        )
      ) : null}
    </div>
  );
}

function parseOffset(raw: string | null): number {
  const value = Number.parseInt(raw ?? "0", 10);
  if (!Number.isFinite(value) || value < 0) return 0;
  return Math.floor(value / PAGE_SIZE) * PAGE_SIZE;
}

function toQuery(filters: PaperFilters, offset: number): URLSearchParams {
  const params = filtersToSearchParams(filters);
  if (offset > 0) params.set("offset", String(offset));
  return params;
}

function describe(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message;
  return "Something went wrong building your recommendations.";
}
