/**
 * Presentation helpers. No business logic: ranking, filtering and relevance all
 * belong to the backend, and nothing here recomputes any of them.
 */

import type { Author, PaperSummary } from "../api/types";

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

/** Human label for the venue line, or null when nothing is known. */
export function formatVenue(paper: Pick<PaperSummary, "venue" | "is_preprint">): string | null {
  if (paper.venue && paper.venue.trim() !== "") return paper.venue;
  if (paper.is_preprint) return "Preprint";
  return null;
}
