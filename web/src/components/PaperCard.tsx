/**
 * One paper, as it appears in a feed or a result list.
 *
 * The whole card is not a link. A card-sized anchor wrapping headings and
 * metadata produces one enormous, badly-named target for a screen reader and
 * makes any link inside it illegal. Instead the title is the link and the card
 * carries a `::after` overlay for pointer users, which keeps the accessible
 * name exactly the paper title.
 */

import { Link } from "react-router-dom";
import type { PaperSummary } from "../api/types";
import { formatAuthors, formatPublished, formatVenue, integrityNotice, publishedDateTime } from "../lib/format";
import { Badge } from "./Badge";
import "./PaperCard.css";

interface PaperCardProps {
  paper: PaperSummary;
  /** Rendered as an ordinal marker in search results. */
  rank?: number;
  /** Heading level, so the surrounding page keeps a sane outline. */
  headingLevel?: 2 | 3;
}

export function PaperCard({ paper, rank, headingLevel = 2 }: PaperCardProps) {
  const Heading = `h${headingLevel}` as "h2" | "h3";
  const authors = formatAuthors(paper.authors);
  const published = formatPublished(paper);
  const publishedValue = publishedDateTime(paper);
  const venue = formatVenue(paper);
  const integrity = integrityNotice(paper.retraction_status);

  return (
    <article className="paper-card">
      {rank !== undefined ? (
        <div className="paper-card__rank" aria-hidden="true">
          {rank}
        </div>
      ) : null}

      <div className="paper-card__body">
        {integrity ? (
          <p className={`paper-card__integrity paper-card__integrity--${integrity.level}`}>
            <Badge tone={integrity.level}>{integrity.label}</Badge>
          </p>
        ) : null}

        <Heading className="paper-card__title">
          <Link className="paper-card__link" to={`/papers/${paper.id}`}>
            {paper.title}
          </Link>
        </Heading>

        <p className="paper-card__authors">
          {authors.text}
          {authors.hiddenCount > 0 ? (
            <span className="paper-card__authors-more"> and {authors.hiddenCount} others</span>
          ) : null}
        </p>

        {paper.abstract_preview ? (
          <p className="paper-card__abstract">{paper.abstract_preview}</p>
        ) : null}

        <ul className="paper-card__meta">
          {published ? (
            <li>
              <time dateTime={publishedValue ?? undefined}>{published}</time>
            </li>
          ) : null}
          {venue ? <li className="paper-card__venue">{venue}</li> : null}
          {paper.is_preprint && venue !== "Preprint" ? <li>Preprint</li> : null}
          {paper.open_access_status && paper.open_access_status !== "closed" &&
          paper.open_access_status !== "unknown" ? (
            <li>
              <Badge tone="success">Open access</Badge>
            </li>
          ) : null}
        </ul>
      </div>
    </article>
  );
}
