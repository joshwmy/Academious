/**
 * One paper, as it appears in a feed or a result list.
 *
 * The order is the order a reader decides in: what the work claims, then a
 * glimpse of the claim itself, then who made it, then where it came from and
 * how it is classified. The title dominates deliberately - it is set in the
 * serif the abstracts use, at a size nothing else on the row competes with,
 * because a feed of research is a feed of claims and everything else on the row
 * exists to qualify one.
 *
 * The whole card is not a link. A card-sized anchor wrapping headings and
 * metadata produces one enormous, badly-named target for a screen reader and
 * makes any link inside it illegal. Instead the title is the link and the card
 * carries a `::after` overlay for pointer users, which keeps the accessible
 * name exactly the paper title.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import type { PaperSummary } from "../api/types";
import {
  formatAuthors,
  formatPublishedRelative,
  integrityNotice,
  paperProvenance,
  publishedDateTime,
  topicLabels,
} from "../lib/format";
import { Badge } from "./Badge";
import { Provenance } from "./Provenance";
import "./PaperCard.css";

interface PaperCardProps {
  paper: PaperSummary;
  /** Rendered as an ordinal marker in search results. */
  rank?: number;
  /** Heading level, so the surrounding page keeps a sane outline. */
  headingLevel?: 2 | 3;
  recommendation?: {
    reasons: string[];
    busy?: boolean;
    onFeedback: (action: "more_like_this" | "less_like_this" | "not_interested") => void;
  };
  onBookmarkChange?: (saved: boolean) => void;
  initiallyBookmarked?: boolean;
  onOpen?: () => void;
}

export function PaperCard({
  paper,
  rank,
  headingLevel = 2,
  recommendation,
  onBookmarkChange,
  initiallyBookmarked = false,
  onOpen,
}: PaperCardProps) {
  const Heading = `h${headingLevel}` as "h2" | "h3";
  const authors = formatAuthors(paper.authors);
  const published = formatPublishedRelative(paper);
  const publishedValue = publishedDateTime(paper);
  const provenance = paperProvenance(paper);
  const integrity = integrityNotice(paper.retraction_status);
  const topics = topicLabels(paper.topics);
  const isOpenAccess =
    paper.open_access_status !== "closed" && paper.open_access_status !== "unknown";
  const storageKey = `academious:bookmark:${paper.id}`;
  const [bookmarked, setBookmarked] = useState(() => {
    try {
      return initiallyBookmarked || window.localStorage.getItem(storageKey) === "true";
    } catch {
      return false;
    }
  });

  const toggleBookmark = () => {
    const next = !bookmarked;
    setBookmarked(next);
    try {
      if (next) window.localStorage.setItem(storageKey, "true");
      else window.localStorage.removeItem(storageKey);
    } catch {
      // The visible state still works when storage is unavailable.
    }
    onBookmarkChange?.(next);
  };

  return (
    <article className="paper-card">
      {rank !== undefined ? (
        <div className="paper-card__rank" aria-hidden="true">
          {rank}
        </div>
      ) : null}

      <div className="paper-card__body">
        <button
          type="button"
          className="paper-card__bookmark"
          aria-label={bookmarked ? `Remove ${paper.title} from saved papers` : `Save ${paper.title}`}
          aria-pressed={bookmarked}
          onClick={toggleBookmark}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6.5 3.5h11v17L12 17l-5.5 3.5z" />
          </svg>
        </button>
        {integrity ? (
          <p className="paper-card__integrity">
            <Badge tone={integrity.level}>{integrity.label}</Badge>
          </p>
        ) : null}

        <Heading className="paper-card__title">
          <Link className="paper-card__link" to={`/papers/${paper.id}`} onClick={onOpen}>
            {paper.title}
          </Link>
        </Heading>

        {paper.abstract_preview ? (
          <p className="paper-card__abstract">{paper.abstract_preview}</p>
        ) : null}

        {/* The count sits outside the truncated span so it survives the
            ellipsis. Cutting "and 34 others" off the end of a narrow line
            loses the one part of an author list a reader cannot infer. */}
        <p className="paper-card__authors">
          <span className="paper-card__authors-names">{authors.text}</span>
          {authors.hiddenCount > 0 ? (
            <span className="paper-card__authors-more">&nbsp;and {authors.hiddenCount} others</span>
          ) : null}
        </p>

        <ul className="paper-card__meta">
          {provenance ? (
            <li>
              <Provenance value={provenance} />
            </li>
          ) : null}
          {published ? (
            <li>
              <time dateTime={publishedValue ?? undefined}>{published}</time>
            </li>
          ) : null}
        </ul>

        {topics.length > 0 || isOpenAccess ? (
          <ul className="paper-card__tags">
            {topics.map((topic) => (
              <li key={topic}>
                <Badge>{topic}</Badge>
              </li>
            ))}
            {isOpenAccess ? (
              <li>
                <Badge tone="success">Open access</Badge>
              </li>
            ) : null}
          </ul>
        ) : null}

        {recommendation ? (
          <div className="paper-card__recommendation">
            {recommendation.reasons.length > 0 ? (
              <p className="paper-card__reason">{recommendation.reasons.join(" · ")}</p>
            ) : null}
            <div className="paper-card__feedback" role="group" aria-label="Tune this recommendation">
              <button type="button" disabled={recommendation.busy} onClick={() => recommendation.onFeedback("more_like_this")}>More like this</button>
              <button type="button" disabled={recommendation.busy} onClick={() => recommendation.onFeedback("less_like_this")}>Less like this</button>
              <button type="button" disabled={recommendation.busy} onClick={() => recommendation.onFeedback("not_interested")}>Not interested</button>
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}
