/**
 * Offset pagination, matching the backend contract exactly.
 *
 * Traditional pages rather than infinite scroll, deliberately: a page number in
 * the URL is shareable and survives the back button, and a reader comparing
 * papers moves back and forth rather than forward forever. Infinite scroll
 * would also fetch on scroll, which spends a rate-limit budget the user did not
 * choose to spend.
 */

import "./Pagination.css";

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  returned: number;
  hasMore: boolean;
  onNavigate: (nextOffset: number) => void;
}

export function Pagination({
  offset,
  limit,
  total,
  returned,
  hasMore,
  onNavigate,
}: PaginationProps) {
  if (total === 0) return null;

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const first = offset + 1;
  const last = offset + returned;

  return (
    <nav className="pagination" aria-label="Pagination">
      <p className="pagination__status" role="status">
        Showing {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()} papers
      </p>

      <div className="pagination__controls">
        <button
          type="button"
          className="button button--quiet"
          onClick={() => onNavigate(Math.max(0, offset - limit))}
          disabled={offset === 0}
          // An explicit label: assembling a name from visible text plus an
          // sr-only fragment loses the space between them, and the button
          // announces as "Previouspage".
          aria-label="Previous page"
        >
          <span aria-hidden="true">← Previous</span>
        </button>

        <span className="pagination__page">
          Page {page.toLocaleString()} of {pages.toLocaleString()}
        </span>

        <button
          type="button"
          className="button button--quiet"
          onClick={() => onNavigate(offset + limit)}
          disabled={!hasMore}
          aria-label="Next page"
        >
          <span aria-hidden="true">Next →</span>
        </button>
      </div>
    </nav>
  );
}
