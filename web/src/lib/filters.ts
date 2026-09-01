/**
 * Filter state for the feed and for search, and the two translations it needs.
 *
 * `GET /papers` and `GET /search` accept the same four filters and apply them
 * the same way - in SQL, before paging or ranking. One module serves both, so
 * the two surfaces cannot drift into meaning different things by the same name.
 * It exists as a separate unit because the interesting parts are not visual:
 *
 * **The URL is the state.** Filters live in the query string exactly as the
 * offset and the search query do, so a filtered feed is a page you can link to,
 * bookmark and return to with the back button. Nothing essential is held only in
 * component state.
 *
 * **A hand-edited URL must not become a 422.** Anything the query string carries
 * is untrusted input: an unknown source key or a misspelled policy is dropped
 * here rather than forwarded to the backend, which validates enums strictly and
 * would answer with an error page for what is really a typo. Dropping is the
 * conservative reading - a filter we cannot honour is a filter we do not claim
 * to have applied.
 *
 * **Only differences from the default are written.** An unfiltered feed has a
 * clean URL, and two URLs meaning the same thing produce the same request:
 * sources are ordered canonically rather than by their order in the query
 * string.
 */

import type { PaperFilterParams, PreprintPolicy } from "../api/types";

/**
 * The sources the backend knows, in canonical order. Mirrors
 * `CONNECTOR_FACTORIES` in `src/academious/sources/registry.py`; there is no
 * endpoint that enumerates them, so this is a transcription like the response
 * types are. bioRxiv and medRxiv share one connector and one source key.
 */
export const SOURCES = [
  { key: "arxiv", label: "arXiv" },
  { key: "biorxiv", label: "bioRxiv / medRxiv" },
  { key: "europepmc", label: "Europe PMC" },
  { key: "openalex", label: "OpenAlex" },
] as const;

export type SourceKey = (typeof SOURCES)[number]["key"];

const SOURCE_KEYS: readonly SourceKey[] = SOURCES.map((source) => source.key);

export const PREPRINT_POLICIES = [
  { value: "any", label: "Any" },
  { value: "only_preprints", label: "Only preprints" },
  { value: "exclude_preprints", label: "Exclude preprints" },
] as const;

const PREPRINT_VALUES: readonly PreprintPolicy[] = PREPRINT_POLICIES.map((policy) => policy.value);

export interface PaperFilters {
  sources: SourceKey[];
  preprints: PreprintPolicy;
  peerReviewed: boolean;
  openAccess: boolean;
}

/** Every field at "no constraint", matching the backend's own defaults. */
export const NO_FILTERS: PaperFilters = {
  sources: [],
  preprints: "any",
  peerReviewed: false,
  openAccess: false,
};

function isSourceKey(value: string): value is SourceKey {
  return (SOURCE_KEYS as readonly string[]).includes(value);
}

function isPreprintPolicy(value: string | null): value is PreprintPolicy {
  return value !== null && (PREPRINT_VALUES as readonly string[]).includes(value);
}

/** Reads filters out of a query string, discarding anything unrecognised. */
export function parseFilters(params: URLSearchParams): PaperFilters {
  const requested = new Set(params.getAll("source").filter(isSourceKey));
  const preprints = params.get("preprints");

  return {
    // Iterating the registry rather than the URL both de-duplicates and fixes
    // the order, so ?source=a&source=b and ?source=b&source=a are one request.
    sources: SOURCE_KEYS.filter((key) => requested.has(key)),
    preprints: isPreprintPolicy(preprints) ? preprints : "any",
    // Only the literal "true" is true. `peer_reviewed=false` and any other
    // value both mean "not filtered", which is what a reader would expect.
    peerReviewed: params.get("peer_reviewed") === "true",
    openAccess: params.get("open_access") === "true",
  };
}

/** Writes filters into a query string, omitting every default. */
export function filtersToSearchParams(filters: PaperFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const source of filters.sources) params.append("source", source);
  if (filters.preprints !== "any") params.set("preprints", filters.preprints);
  if (filters.peerReviewed) params.set("peer_reviewed", "true");
  if (filters.openAccess) params.set("open_access", "true");
  return params;
}

/**
 * Translates to the API client's parameter names. Defaults are omitted rather
 * than sent explicitly: the client drops undefined values, so an unfiltered
 * request is byte-identical to the one the feed made before filters existed.
 */
export function filtersToParams(filters: PaperFilters): PaperFilterParams {
  return {
    ...(filters.sources.length > 0 ? { source: [...filters.sources] } : {}),
    ...(filters.preprints !== "any" ? { preprints: filters.preprints } : {}),
    ...(filters.peerReviewed ? { peer_reviewed: true } : {}),
    ...(filters.openAccess ? { open_access: true } : {}),
  };
}

/** How many constraints are in force. Each selected source counts as one. */
export function countActiveFilters(filters: PaperFilters): number {
  return (
    filters.sources.length +
    (filters.preprints === "any" ? 0 : 1) +
    (filters.peerReviewed ? 1 : 0) +
    (filters.openAccess ? 1 : 0)
  );
}

export function hasActiveFilters(filters: PaperFilters): boolean {
  return countActiveFilters(filters) > 0;
}
