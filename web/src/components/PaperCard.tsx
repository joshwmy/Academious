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

import { Link } from "react-router-dom";
import type { PaperSummary } from "../api/types";
import {
  formatAuthors,
  formatPublished,
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
}

export function PaperCard({ paper, rank, headingLevel = 2 }: PaperCardProps) {
  const Heading = `h${headingLevel}` as "h2" | "h3";
  const authors = formatAuthors(paper.authors);
  const published = formatPublished(paper);
  const publishedValue = publishedDateTime(paper);
  const provenance = paperProvenance(paper);
  const integrity = integrityNotice(paper.retraction_status);
  const topics = topicLabels(paper.topics);
  const isOpenAccess =
    paper.open_access_status !== "closed" && paper.open_access_status !== "unknown";

  return (
    <article className="paper-card">
      {rank !== undefined ? (
        <div className="paper-card__rank" aria-hidden="true">
          {rank}
        </div>
      ) : null}

      <div className="paper-card__body">
        {integrity ? (
          <p className="paper-card__integrity">
            <Badge tone={integrity.level}>{integrity.label}</Badge>
          </p>
        ) : null}

        <Heading className="paper-card__title">
          <Link className="paper-card__link" to={`/papers/${paper.id}`}>
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
      </div>
    </article>
  );
}
