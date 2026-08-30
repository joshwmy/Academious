/**
 * One error type for everything the API layer can fail with.
 *
 * Pages need to distinguish "you are going too fast" from "that paper does not
 * exist" from "the network is down", and they should not do that by matching on
 * error message strings. `kind` is the discriminant; `status` is kept for the
 * cases that care about the exact code.
 */

export type ApiErrorKind =
  | "not_found" // 404
  | "invalid_request" // 422
  | "rate_limited" // 429
  | "capacity" // 503 - search is saturated
  | "server" // 5xx other than 503
  | "network" // request never completed
  | "malformed"; // completed, but the body was not what the contract promises

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** Seconds the server asked us to wait, when it said so. */
  readonly retryAfterSeconds: number | null;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number | null; retryAfterSeconds?: number | null } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

/** True when the caller abandoned the request, e.g. by navigating away. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
