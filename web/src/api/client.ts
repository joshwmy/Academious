/**
 * The only place in the application that talks HTTP.
 *
 * Components never call `fetch`. They call these functions, receive typed data
 * or an `ApiError`, and are spared knowing about status codes, query-string
 * construction or `Retry-After` parsing.
 *
 * Two deliberate omissions:
 *
 * **No automatic retries.** The backend protects itself with a 20-search-per-
 * minute budget and a two-slot concurrency gate, and answers 429 and 503 when
 * either is exceeded. A client that retried those on its own would convert
 * backpressure into a retry storm - the exact failure the backend controls
 * exist to prevent. Retrying is the user's decision, offered as a button.
 *
 * **No caching layer.** Three read endpoints, explicit-submit search and no
 * mutations do not need one, and a library that refetches in the background
 * would silently spend the user's rate-limit budget. See docs/frontend.md.
 */

import { ApiError } from "./errors";
import type {
  FieldsResponse,
  PaperDetail,
  PaperListParams,
  PaperPage,
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
      // No cookies are sent: the API is unauthenticated, and credentialed CORS
      // against a read API is how a confused-deputy bug arrives later.
      credentials: "omit",
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
