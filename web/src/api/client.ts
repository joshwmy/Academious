/**
 * The only place in the application that talks HTTP.
 *
 * Components never call `fetch`. They call these functions, receive typed data
 * or an `ApiError`, and are spared knowing about status codes, query-string
 * construction or `Retry-After` parsing.
 *
 * Two deliberate constraints:
 *
 * **No automatic retries.** The backend protects itself with a 20-search-per-
 * minute budget and a two-slot concurrency gate, and answers 429 and 503 when
 * either is exceeded. A client that retried those on its own would convert
 * backpressure into a retry storm - the exact failure the backend controls
 * exist to prevent. Retrying is the user's decision, offered as a button.
 *
 * **No caching layer.** Explicit fetches make account and feed state changes
 * visible and avoid silent background spending of the user's rate-limit budget.
 */

import { ApiError } from "./errors";
import type {
  AccountFeedResponse,
  AccountUser,
  FieldsResponse,
  PaperDetail,
  PaperListParams,
  PaperPage,
  PaperSummary,
  ProfileDraft,
  ProfileOptions,
  ProfileResponse,
  Refinement,
  RecommendationInteraction,
  SearchParams,
  SearchResponse,
} from "./types";

/** Mirrors the backend's `api_max_query_length`. Client-side is UX, not security. */
export const MAX_QUERY_LENGTH = 512;
/** Mirrors the backend's `api_max_search_results`. */
export const MAX_SEARCH_RESULTS = 50;
/** Mirrors the backend's `api_max_page_size`. */
export const MAX_PAGE_SIZE = 100;

function resolveBaseUrl(): string {
  const configured = import.meta.env["VITE_API_BASE_URL"];
  if (typeof configured === "string" && configured.trim() !== "") {
    return configured.trim().replace(/\/+$/, "");
  }
  // Same-origin fallback: the documented production topology serves the static
  // frontend and proxies /papers and /search from one hostname, so an unset
  // variable is a valid configuration rather than an error.
  return "";
}

export const API_BASE_URL = resolveBaseUrl();

function buildUrl(path: string, params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const query = search.toString();
  return `${API_BASE_URL}${path}${query ? `?${query}` : ""}`;
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (!header) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // A body that is not JSON tells us nothing useful; the status does.
  }
  return null;
}

async function toApiError(response: Response): Promise<ApiError> {
  const retryAfterSeconds = parseRetryAfter(response);
  const detail = await readDetail(response);

  switch (response.status) {
    case 404:
      return new ApiError("not_found", detail ?? "Not found", { status: 404 });
    case 422:
      return new ApiError("invalid_request", detail ?? "Invalid request", { status: 422 });
    case 429:
      return new ApiError("rate_limited", detail ?? "Too many requests", {
        status: 429,
        retryAfterSeconds,
      });
    case 503:
      return new ApiError("capacity", detail ?? "Temporarily unavailable", {
        status: 503,
        retryAfterSeconds,
      });
    default:
      return new ApiError("server", detail ?? `Request failed (${response.status})`, {
        status: response.status,
      });
  }
}

async function request<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      // Same-site opaque session cookies are included for account endpoints.
      // Public endpoints remain usable without them.
      credentials: "include",
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    // An aborted request is the caller's own doing, so it propagates unchanged
    // and callers ignore it rather than rendering an error for it.
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network", "Could not reach the Academious API.");
  }

  if (!response.ok) throw await toApiError(response);

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("malformed", "The API returned a response we could not read.", {
      status: response.status,
    });
  }
}

export function listPapers(
  params: PaperListParams = {},
  signal?: AbortSignal,
): Promise<PaperPage> {
  return request<PaperPage>(buildUrl("/papers", { ...params }), signal);
}

export function listFields(signal?: AbortSignal): Promise<FieldsResponse> {
  return request<FieldsResponse>(buildUrl("/fields"), signal);
}

export function getPaper(id: string, signal?: AbortSignal): Promise<PaperDetail> {
  // Encoded so that a malformed id from a hand-edited URL cannot alter the path.
  return request<PaperDetail>(buildUrl(`/papers/${encodeURIComponent(id)}`), signal);
}

export function searchPapers(
  params: SearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  return request<SearchResponse>(buildUrl("/search", { ...params }), signal);
}

/**
 * JSON POST helper for stateless profile previews.
 */
async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network", "Could not reach the Academious API.");
  }

  if (!response.ok) throw await toApiError(response);

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("malformed", "The API returned a response we could not read.", {
      status: response.status,
    });
  }
}

/** The level vocabulary and per-stage limits, so nothing here is hardcoded. */
export function getProfileOptions(signal?: AbortSignal): Promise<ProfileOptions> {
  return request<ProfileOptions>(buildUrl("/profiles/options"), signal);
}

/** Build a profile from a draft and return the feed it produces. */
export function previewProfile(
  draft: ProfileDraft,
  limit: number,
  signal?: AbortSignal,
): Promise<ProfileResponse> {
  return postJson<ProfileResponse>("/profiles/preview", { draft, limit }, signal);
}

/** Apply corrections to a draft and return the updated profile and preview. */
export function refineProfile(
  draft: ProfileDraft,
  refinements: Refinement[],
  limit: number,
  signal?: AbortSignal,
): Promise<ProfileResponse> {
  return postJson<ProfileResponse>("/profiles/refine", { draft, refinements, limit }, signal);
}

async function mutate<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body === undefined
        ? { Accept: "application/json" }
        : { Accept: "application/json", "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      credentials: "include",
    });
  } catch {
    throw new ApiError("network", "Could not reach the Academious API.");
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getCurrentUser(): Promise<AccountUser> {
  return request<AccountUser>(buildUrl("/users/me"));
}

export function registerAccount(input: {
  email: string;
  password: string;
  display_name: string;
}): Promise<AccountUser> {
  return mutate<AccountUser>("/auth/register", "POST", {
    ...input,
    recommendation_data_consent: true,
  });
}

export async function loginAccount(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  const response = await fetch(`${API_BASE_URL}/auth/session/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
    credentials: "include",
  });
  if (!response.ok) throw await toApiError(response);
}

export function logoutAccount(): Promise<void> {
  return mutate<void>("/auth/session/logout", "POST");
}

export function requestVerification(email: string): Promise<void> {
  return mutate<void>("/auth/request-verify-token", "POST", { email });
}

export function verifyAccount(token: string): Promise<AccountUser> {
  return mutate<AccountUser>("/auth/verify", "POST", { token });
}

export function saveAccountProfile(draft: ProfileDraft): Promise<ProfileDraft> {
  return mutate<ProfileDraft>("/me/profile", "PUT", draft);
}

export function getAccountProfile(): Promise<ProfileDraft> {
  return request<ProfileDraft>(buildUrl("/me/profile"));
}

export function getAccountFeed(limit = 20): Promise<AccountFeedResponse> {
  return mutate<AccountFeedResponse>(`/me/feed?limit=${String(limit)}`, "POST");
}

export function sendInteractions(events: RecommendationInteraction[]): Promise<{
  accepted: number;
  duplicates: number;
}> {
  return mutate("/me/interactions", "POST", { events });
}

export function listSavedPapers(): Promise<PaperSummary[]> {
  return request<PaperSummary[]>(buildUrl("/me/saved-papers"));
}

export function removeSavedPaper(paperId: string): Promise<void> {
  return mutate<void>(`/me/saved-papers/${encodeURIComponent(paperId)}`, "DELETE");
}

export function forgotPassword(email: string): Promise<void> {
  return mutate<void>("/auth/forgot-password", "POST", { email });
}

export function resetPassword(token: string, password: string): Promise<void> {
  return mutate<void>("/auth/reset-password", "POST", { token, password });
}

export function deleteAccount(): Promise<void> {
  return mutate<void>("/me/account", "DELETE");
}
