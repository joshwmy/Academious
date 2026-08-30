/**
 * One async request, tied to the lifetime of the component that wants it.
 *
 * Three behaviours this exists to guarantee:
 *
 * 1. **Obsolete requests are cancelled.** Navigating away or changing the query
 *    aborts the request in flight, so an abandoned `/search` stops occupying one
 *    of the backend's two inference slots.
 * 2. **A late response never wins.** Even with cancellation, a resolved promise
 *    can land after a newer one, so each settled result is tagged with the
 *    request it belongs to and a stale tag is ignored.
 * 3. **React StrictMode's double invocation does not double-spend the user's
 *    rate-limit budget.** Cleanup aborts the discarded render's request rather
 *    than letting it complete.
 *
 * Loading is *derived*, not assigned: a result is stored with the token of the
 * request that produced it, and any render whose token does not match is
 * loading by definition. That avoids a synchronous `setState` in the effect and
 * the cascading render it would cause.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, isAbortError } from "../api/errors";

export type RequestState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: T; error: null }
  | { status: "error"; data: null; error: ApiError };

export interface UseRequestResult<T> {
  state: RequestState<T>;
  /** Re-runs the request. Wired to the retry button on error views. */
  retry: () => void;
}

const LOADING = { status: "loading", data: null, error: null } as const;

interface Settled<T> {
  token: object;
  state: RequestState<T>;
}

/**
 * @param run     Performs the request. Must forward the signal to the client.
 *                Callers wrap this in `useCallback` so its identity *is* the
 *                request identity.
 * @param enabled When false no request is made and the state stays loading.
 */
export function useRequest<T>(
  run: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): UseRequestResult<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  // A fresh object per (request, attempt). Comparing identity is how a render
  // knows whether the result it holds belongs to the request it is showing.
  const token = useMemo(() => ({ run, attempt }), [run, attempt]);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();

    run(controller.signal)
      .then((data) => setSettled({ token, state: { status: "success", data, error: null } }))
      .catch((error: unknown) => {
        // We asked this one to stop; it is not a failure to report.
        if (isAbortError(error)) return;
        setSettled({
          token,
          state: {
            status: "error",
            data: null,
            error:
              error instanceof ApiError
                ? error
                : new ApiError("network", "Something went wrong loading this page."),
          },
        });
      });

    return () => controller.abort();
  }, [run, token, enabled]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const state = settled && settled.token === token ? settled.state : LOADING;

  return { state, retry };
}
