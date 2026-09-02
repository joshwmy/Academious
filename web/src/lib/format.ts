/**
 * Presentation helpers. No business logic: ranking, filtering and relevance all
 * belong to the backend, and nothing here recomputes any of them.
 */

import type { Author, PaperSummary, Topic } from "../api/types";

/** How many authors a card shows before collapsing to "and N others". */
const AUTHORS_SHOWN = 6;

export function formatAuthors(
  authors: Author[],
  limit: number = AUTHORS_SHOWN,
): { text: string; hiddenCount: number } {
  const names = authors.map((author) => author.name).filter((name) => name.trim() !== "");
  if (names.length === 0) return { text: "Unknown authors", hiddenCount: 0 };
  if (names.length <= limit) return { text: names.join(", "), hiddenCount: 0 };
  return {
    text: names.slice(0, limit).join(", "),
    hiddenCount: names.length - limit,
  };
}

/**
 * A readable date, falling back to the year when only that is known.
 * Returns null when the record carries no date at all, so callers can omit the
 * element rather than render "Unknown".
 */
export function formatPublished(paper: Pick<PaperSummary, "published_date" | "published_year">) {
  if (paper.published_date) {
    const parsed = new Date(`${paper.published_date}T00:00:00Z`);
    if (!Number.isNaN(parsed.getTime())) {
      return new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }).format(parsed);
    }
  }
  if (paper.published_year) return String(paper.published_year);
  return null;
}

/** The machine-readable value for a `<time datetime>` attribute. */
export function publishedDateTime(
  paper: Pick<PaperSummary, "published_date" | "published_year">,
): string | null {
  if (paper.published_date) return paper.published_date;
  if (paper.published_year) return String(paper.published_year);
  return null;
}

export interface IntegrityNotice {
  level: "danger" | "warning";
  label: string;
  description: string;
}

/**
 * How a paper's integrity status should be surfaced, or null when there is
 * nothing to say. A retracted paper must never render as ordinary metadata.
 */
export function integrityNotice(status: string): IntegrityNotice | null {
  switch (status) {
    case "retracted":
      return {
        level: "danger",
        label: "Retracted",
        description:
          "This paper has been retracted. Its findings have been withdrawn from the " +
          "scientific record and should not be relied on.",
      };
    case "concern":
      return {
        level: "warning",
        label: "Expression of concern",
        description:
          "An expression of concern has been published about this paper. Its findings " +
          "are disputed or under investigation.",
      };
    case "corrected":
      return {
        level: "warning",
        label: "Corrected",
        description:
          "A correction has been published for this paper. Read it alongside the " +
          "original.",
      };
    default:
      return null;
  }
}

/**
 * Where a record came from, and what kind of record it is.
 *
 * `venue` carries a repository name for preprints ("arXiv", "bioRxiv") and a
 * journal name for published work, so one field answers both questions once the
 * preprint flag says which reading applies. This is the closest thing the
 * summary payload has to provenance: the source keys a paper was harvested
 * under live on `source_record` and are filterable but never returned, so the
 * card cannot claim more than the venue knows.
 *
 * The distinction is worth surfacing rather than printing as one more grey
 * metadata item. A preprint and a peer-reviewed paper are different kinds of
 * claim, and in a feed that is the judgement a reader makes before any other.
 */
export interface Provenance {
  /** `repository` for preprint servers, `journal` for published venues. */
  kind: "repository" | "journal";
  label: string;
}

export function paperProvenance(
  paper: Pick<PaperSummary, "venue" | "is_preprint">,
): Provenance | null {
  const venue = paper.venue?.trim();
  if (paper.is_preprint) {
    // A preprint with no named server is still a preprint, and saying so is
    // more use than saying nothing.
    return { kind: "repository", label: venue || "Preprint" };
  }
  if (venue) return { kind: "journal", label: venue };
  return null;
}

/**
 * The labelled topics worth showing, capped.
 *
 * Topics arrive from the upstream classifier and are uneven: some carry only an
 * identifier, some repeat, and a paper can be tagged with a dozen. A card shows
 * a few labelled ones or none - a row of eight chips stops being a signal and
 * becomes texture, and an unlabelled identifier tells a reader nothing at all.
 */
export function topicLabels(topics: Topic[], limit = 3): string[] {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const topic of topics) {
    const label = topic.label?.trim();
    if (!label) continue;
    const key = label.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    labels.push(label);
    if (labels.length === limit) break;
  }
  return labels;
}
