/**
 * One paper in full: a reading surface, not a record view.
 *
 * The page is set to a narrow measure and the abstract is set in the serif at
 * reading size, because the thing a reader came here to do is read a paragraph
 * of dense prose. Everything else - identifiers, licence, counts - is filed
 * below it in a definition list, where it can be looked up without competing
 * with the abstract for attention.
 *
 * Integrity comes first. A retracted paper carries a banner above its own title,
 * because a reader who scans the title and abstract and leaves must not be able
 * to miss that the record has been withdrawn. It is the one place this interface
 * deliberately interrupts.
 */

import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { getPaper } from "../api/client";
import { Badge } from "../components/Badge";
import { ExternalLink } from "../components/ExternalLink";
import { Provenance } from "../components/Provenance";
import { ErrorState, LoadingRegion } from "../components/States";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useRequest } from "../hooks/useRequest";
import {
  formatAuthors,
  formatPublished,
  integrityNotice,
  paperProvenance,
  publishedDateTime,
} from "../lib/format";
import { doiUrl, safeExternalUrl } from "../lib/url";
import "./PaperPage.css";

export function PaperPage() {
  const { paperId } = useParams<{ paperId: string }>();
  const id = paperId ?? "";

  const run = useCallback((signal: AbortSignal) => getPaper(id, signal), [id]);
  const { state, retry } = useRequest(run, id !== "");

  // Null until there is a real title. The shell title is a better placeholder
  // than the word "Loading" sitting in a tab strip and in browser history.
  useDocumentTitle(state.status === "success" ? state.data.title : null);

  if (state.status === "loading") {
    return (
      <LoadingRegion label="Loading paper">
        <div className="paper-detail paper-detail--loading" aria-hidden="true">
          <div className="skeleton-line skeleton-line--title" />
          <div className="skeleton-line skeleton-line--authors" />
          <div className="skeleton-line" />
          <div className="skeleton-line" />
          <div className="skeleton-line skeleton-line--short" />
        </div>
      </LoadingRegion>
    );
  }

  if (state.status === "error") {
    return <ErrorState error={state.error} onRetry={retry} context="paper" />;
  }

  const paper = state.data;
  const authors = formatAuthors(paper.authors, Number.MAX_SAFE_INTEGER);
  const published = formatPublished(paper);
  const publishedValue = publishedDateTime(paper);
  const provenance = paperProvenance(paper);
  const integrity = integrityNotice(paper.retraction_status);
  const doiHref = doiUrl(paper.doi);
  const oaUrl = safeExternalUrl(paper.open_access?.url);
  const pdfUrl = safeExternalUrl(paper.open_access?.pdf_url);
  const noticeUrl = safeExternalUrl(paper.retraction_notice_url);

  return (
    <article className="paper-detail">
      <p className="paper-detail__back">
        <Link to="/">← Back to new research</Link>
      </p>

      {integrity ? (
        // A div, not an <aside>: `alert` is not an allowed role on an element
        // whose implicit role is `complementary`, and the retraction notice has
        // to be an alert rather than an aside.
        <div
          className={`integrity integrity--${integrity.level}`}
          role={integrity.level === "danger" ? "alert" : "note"}
        >
          <p className="integrity__label">{integrity.label}</p>
          <p className="integrity__description">{integrity.description}</p>
          {noticeUrl ? (
            <p>
              <ExternalLink href={noticeUrl}>Read the notice</ExternalLink>
            </p>
          ) : null}
        </div>
      ) : null}

      <header className="paper-detail__header">
        <h1 className="paper-detail__title">{paper.title}</h1>
        <p className="paper-detail__authors">{authors.text}</p>
        <ul className="paper-detail__meta">
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
          {paper.is_peer_reviewed ? (
            <li>
              <Badge tone="info">Peer reviewed</Badge>
            </li>
          ) : null}
          {paper.open_access?.is_open ? (
            <li>
              <Badge tone="success">Open access</Badge>
            </li>
          ) : null}
        </ul>
      </header>

      {oaUrl || pdfUrl ? (
        <p className="paper-detail__actions">
          {pdfUrl ? (
            <ExternalLink className="button" href={pdfUrl}>
              Read PDF
            </ExternalLink>
          ) : null}
          {oaUrl ? (
            <ExternalLink className="button button--quiet" href={oaUrl}>
              View at source
            </ExternalLink>
          ) : null}
        </p>
      ) : null}

      {paper.abstract ? (
        <section className="paper-detail__section" aria-labelledby="abstract-heading">
          <h2 className="eyebrow" id="abstract-heading">
            Abstract
          </h2>
          <p className="paper-detail__abstract">{paper.abstract}</p>
        </section>
      ) : null}

      <section className="paper-detail__section" aria-labelledby="details-heading">
        <h2 className="eyebrow" id="details-heading">
          Publication details
        </h2>
        <dl className="detail-grid">
          {paper.doi ? (
            <div className="detail-grid__row">
              <dt>DOI</dt>
              <dd>
                {doiHref ? <ExternalLink href={doiHref}>{paper.doi}</ExternalLink> : paper.doi}
              </dd>
            </div>
          ) : null}

          {Object.entries(paper.identifiers)
            .filter(([type]) => type !== "doi")
            .map(([type, value]) => (
              <div className="detail-grid__row" key={type}>
                <dt>{type}</dt>
                <dd>{value}</dd>
              </div>
            ))}

          {paper.venue ? (
            <div className="detail-grid__row">
              <dt>Venue</dt>
              <dd>{paper.venue}</dd>
            </div>
          ) : null}

          {paper.work_type ? (
            <div className="detail-grid__row">
              <dt>Type</dt>
              <dd>{paper.work_type}</dd>
            </div>
          ) : null}

          {paper.language ? (
            <div className="detail-grid__row">
              <dt>Language</dt>
              <dd>{paper.language}</dd>
            </div>
          ) : null}

          {paper.open_access ? (
            <div className="detail-grid__row">
              <dt>Access</dt>
              <dd>
                {paper.open_access.status}
                {paper.open_access.licence ? ` · ${paper.open_access.licence}` : ""}
              </dd>
            </div>
          ) : null}

          {typeof paper.citation_count === "number" ? (
            <div className="detail-grid__row">
              <dt>Citations</dt>
              <dd>{paper.citation_count.toLocaleString()}</dd>
            </div>
          ) : null}
        </dl>
      </section>

      {paper.topics.length > 0 ? (
        <section className="paper-detail__section" aria-labelledby="topics-heading">
          <h2 className="eyebrow" id="topics-heading">
            Topics
          </h2>
          <ul className="paper-detail__topics">
            {paper.topics.map((topic, index) => (
              <li key={`${topic.id ?? topic.label ?? "topic"}-${index}`}>
                <Badge>{topic.label ?? topic.id ?? "Unlabelled"}</Badge>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
