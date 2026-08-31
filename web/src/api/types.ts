/**
 * The public API contract, mirrored in TypeScript.
 *
 * These types are a transcription of the backend response schemas in
 * `src/academious/api/schemas.py`, which is the source of truth. They exist so
 * that a field rename in the API becomes a compile error here rather than
 * `undefined` in a paragraph.
 *
 * Note what is deliberately absent: there is no `score` on a search hit, and no
 * `method`, `model_key` or retrieval parameter anywhere. The backend does not
 * expose them and this client does not invent them.
 */

export interface Author {
  name: string;
  position: number | null;
  orcid: string | null;
  affiliations: string[];
}

export interface Topic {
  id: string | null;
  label: string | null;
  scheme: string | null;
}

export interface OpenAccess {
  status: string;
  is_open: boolean;
  url: string | null;
  pdf_url: string | null;
  licence: string | null;
}

/** Retraction states the backend can report. */
export type RetractionStatus = "none" | "corrected" | "concern" | "retracted";

export interface PaperSummary {
  id: string;
  title: string;
  abstract_preview: string | null;
  authors: Author[];
  published_date: string | null;
  published_year: number | null;
  venue: string | null;
  doi: string | null;
  is_preprint: boolean;
  is_peer_reviewed: boolean;
  open_access_status: string;
  retraction_status: string;
  topics: Topic[];
  citation_count: number | null;
}

export interface PaperDetail extends PaperSummary {
  abstract: string | null;
  language: string | null;
  work_type: string | null;
  /** External identifiers keyed by type, e.g. `{ doi: "10.…", arxiv: "2408.…" }`. */
  identifiers: Record<string, string>;
  open_access: OpenAccess | null;
  retraction_notice_url: string | null;
}

export interface PageInfo {
  limit: number;
  offset: number;
  total: number;
  returned: number;
  has_more: boolean;
}

export interface PaperPage {
  page: PageInfo;
  results: PaperSummary[];
}

export interface SearchHit {
  /** 1-based position in the ranking. The ordering is the relevance signal. */
  rank: number;
  paper: PaperSummary;
}

export interface SearchResponse {
  /** The query as searched, after the backend's whitespace normalisation. */
  query: string;
  count: number;
  limit: number;
  results: SearchHit[];
}

/** Filters `GET /papers` accepts. Mirrors `retrieval/filters.py`. */
export type PreprintPolicy = "any" | "only_preprints" | "exclude_preprints";

/**
 * `| undefined` on each optional field is deliberate: the client drops
 * undefined values when building the query string, so a caller may pass one
 * explicitly (`{ offset: maybeOffset }`) without special-casing it.
 */
/**
 * Metadata filters, in the backend's own spelling.
 *
 * `/papers` and `/search` accept the same four, and both apply them in SQL
 * before paging or ranking. One interface rather than two copies, so the day a
 * fifth filter arrives it cannot reach one endpoint and not the other.
 */
export interface PaperFilterParams {
  source?: string[] | undefined;
  preprints?: PreprintPolicy | undefined;
  peer_reviewed?: boolean | undefined;
  open_access?: boolean | undefined;
}

export interface PaperListParams extends PaperFilterParams {
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface SearchParams extends PaperFilterParams {
  q: string;
  limit?: number | undefined;
}
