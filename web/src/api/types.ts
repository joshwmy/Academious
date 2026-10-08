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
  /**
   * Normalised subject field slugs, e.g. `["computer-science"]`. Empty when no
   * source classified the paper in a vocabulary the backend maps - a Europe PMC
   * paper carrying only MeSH descriptors has none.
   */
  fields: string[];
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
  field?: string[] | undefined;
}

/** One subject field, as `GET /fields` reports it. */
export interface FieldSummary {
  slug: string;
  label: string;
  paper_count: number;
}

export interface FieldsResponse {
  fields: FieldSummary[];
  /**
   * Papers no field filter can reach. Selecting any field excludes them, which
   * is why the number is shown rather than left to be inferred.
   */
  papers_without_field: number;
}

export interface PaperListParams extends PaperFilterParams {
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface SearchParams extends PaperFilterParams {
  q: string;
  limit?: number | undefined;
}

/**
 * Research profile creation.
 *
 * These mirror `api/schemas_profiles.py` exactly, including the deliberate
 * absence of any score, cosine or weight: a preview item carries a rank, a
 * paper and reasons, and nothing a reader cannot calibrate.
 *
 * The draft is the artifact this client owns. The server normalises it and
 * hands it back; there is no account and nothing is stored, so keeping it is
 * the client's job.
 */

export type Importance = "core" | "interested" | "occasional";
export type Avoidance = "avoid" | "less";
export type Horizon = "long" | "short";
export type FreshnessLevel = "newest_first" | "balanced" | "relevance_first";
export type ExplorationLevel = "focused" | "balanced" | "adventurous";
export type PublicationStage =
  | "include_preprints"
  | "prefer_peer_reviewed"
  | "peer_reviewed_only";

export interface DraftInterest {
  text: string;
  importance: Importance;
  horizon?: Horizon;
  label?: string | null;
}

export interface DraftExamplePaper {
  paper_id: string;
  importance: Importance;
  horizon?: Horizon;
  label?: string | null;
}

export interface DraftNegative {
  text: string;
  strength: Avoidance;
  label?: string | null;
}

export interface DraftNegativePaper {
  paper_id: string;
  strength: Avoidance;
  label?: string | null;
}

export interface DiscoveryChoices {
  freshness: FreshnessLevel;
  exploration: ExplorationLevel;
  publication: PublicationStage;
}

export interface ProfileDraft {
  fields: string[];
  interests: DraftInterest[];
  example_papers: DraftExamplePaper[];
  negatives: DraftNegative[];
  negative_papers: DraftNegativePaper[];
  blocked_topics: string[];
  discovery: DiscoveryChoices;
}

export interface DraftIssue {
  code: string;
  message: string;
  severity: "error" | "warning";
  subject?: string | null;
}

export interface ProfileInterest {
  key: string;
  label: string;
  kind: string;
  polarity: string;
  /** A word - "Core interest" - never a weight. */
  level: string;
  horizon: Horizon;
  provenance: string;
}

export interface Preference {
  label: string;
  value: string;
}

export interface SummarySection {
  heading: string;
  items: string[];
}

export interface ProfileSummary {
  sections: SummarySection[];
  preferences: Preference[];
}

export interface CanonicalProfile {
  schema_version: number;
  model_key: string;
  interests: ProfileInterest[];
  preferences: Preference[];
  blocked_topics: string[];
  peer_reviewed_only: boolean;
}

export interface PreviewItem {
  rank: number;
  paper: PaperSummary;
  matched_interest?: string | null;
  /** Send this back with a refinement so it lands on the interest shown. */
  matched_interest_key?: string | null;
  reasons: string[];
  is_exploration: boolean;
  is_retracted: boolean;
}

export interface ProfileResponse {
  schema_version: number;
  draft: ProfileDraft;
  profile: CanonicalProfile;
  summary: ProfileSummary;
  preview: PreviewItem[];
  issues: DraftIssue[];
  changes: string[];
}

export interface AccountUser {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  recommendation_data_consent: boolean;
  consent_version: string | null;
  consented_at: string | null;
}

export interface AccountFeedResponse {
  feed_session_id: string;
  result: ProfileResponse;
}

export interface RecommendationInteraction {
  event_id: string;
  type:
    | "impression"
    | "open"
    | "abstract_expand"
    | "outbound_click"
    | "save"
    | "follow_from_item"
    | "more_like_this"
    | "less_like_this"
    | "not_interested"
    | "dismiss"
    | "block_topic";
  paper_id: string;
  occurred_at: string;
  position?: number;
  interest_key?: string;
  session_id?: string;
  dwell_ms?: number;
}

export type RefinementAction =
  | "fits"
  | "more_like_this"
  | "less_like_this"
  | "not_interested"
  | "more_from_interest"
  | "less_from_interest"
  | "remove_interest"
  | "block_topic";

export interface Refinement {
  action: RefinementAction;
  paper_id?: string | undefined;
  interest_key?: string | undefined;
  topic_id?: string | undefined;
  label?: string | undefined;
}

export interface LevelOption {
  value: string;
  label: string;
}

export interface ProfileOptions {
  schema_version: number;
  importance: LevelOption[];
  avoidance: LevelOption[];
  freshness: LevelOption[];
  exploration: LevelOption[];
  publication: LevelOption[];
  limits: Record<string, number>;
}
