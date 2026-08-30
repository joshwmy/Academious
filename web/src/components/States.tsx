/**
 * Loading, empty and error views.
 *
 * The error copy is deliberately specific per failure kind. "Something went
 * wrong" is true of every one of them and useful for none: a rate-limited user
 * needs to know to wait, a user whose search hit the capacity gate needs to know
 * to retry, and someone who followed a dead link needs to know the paper is
 * gone rather than the site is broken.
 */

import { Link } from "react-router-dom";
import type { ApiError } from "../api/errors";
import "./States.css";

/** Skeleton rows that hold the layout while a list loads. */
export function PaperListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="skeleton-list" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton-card" key={index}>
          <div className="skeleton-line skeleton-line--title" />
          <div className="skeleton-line skeleton-line--authors" />
          <div className="skeleton-line" />
          <div className="skeleton-line skeleton-line--short" />
        </div>
      ))}
    </div>
  );
}

/**
 * Announces progress without stealing focus. `role="status"` is polite, so a
 * screen reader finishes its current sentence before mentioning it.
 */
export function LoadingRegion({ label, children }: { label: string; children?: React.ReactNode }) {
  return (
    <div>
      <p role="status" className="sr-only">
        {label}
      </p>
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="state-panel">
      <h2 className="state-panel__title">{title}</h2>
      {children ? <div className="state-panel__body">{children}</div> : null}
    </div>
  );
}

interface ErrorStateProps {
  error: ApiError;
  onRetry?: () => void;
  /** What the user was doing, for copy that names the right thing. */
  context?: "feed" | "search" | "paper";
}

interface ErrorCopy {
  title: string;
  body: string;
  /** Retrying a 4xx that is not a rate limit just repeats the mistake. */
  retryable: boolean;
}

function errorCopy(error: ApiError, context: ErrorStateProps["context"]): ErrorCopy {
  switch (error.kind) {
    case "not_found":
      return {
        title: "Paper not found",
        body: "This paper is not in the Academious corpus. It may have been removed, or the link may be wrong.",
        retryable: false,
      };
    case "rate_limited": {
      const wait = error.retryAfterSeconds;
      return {
        title: "Too many requests",
        body: wait
          ? `You are sending requests faster than the service allows. Try again in about ${wait} seconds.`
          : "You are sending requests faster than the service allows. Wait a moment, then try again.",
        retryable: true,
      };
    }
    case "capacity":
      return {
        title: "Search is busy",
        body: "Search is handling as many requests as it can right now. Give it a few seconds and try again.",
        retryable: true,
      };
    case "invalid_request":
      return {
        title: "That request was not valid",
        body: error.message,
        retryable: false,
      };
    case "network":
      return {
        title: "Could not reach Academious",
        body: "The service did not respond. Check your connection, then try again.",
        retryable: true,
      };
    case "malformed":
      return {
        title: "Unexpected response",
        body: "Academious returned something this page could not read. Trying again may help.",
        retryable: true,
      };
    default:
      return {
        title: context === "search" ? "Search failed" : "Something went wrong",
        body: "Academious ran into a problem handling that request. Trying again may help.",
        retryable: true,
      };
  }
}

export function ErrorState({ error, onRetry, context }: ErrorStateProps) {
  const copy = errorCopy(error, context);

  return (
    <div className="state-panel state-panel--error" role="alert">
      <h2 className="state-panel__title">{copy.title}</h2>
      <p className="state-panel__body">{copy.body}</p>
      <div className="state-panel__actions">
        {copy.retryable && onRetry ? (
          <button type="button" className="button" onClick={onRetry}>
            Try again
          </button>
        ) : null}
        <Link className="button button--quiet" to="/">
          Back to recent papers
        </Link>
      </div>
    </div>
  );
}
