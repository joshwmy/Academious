import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getCurrentUser, logoutAccount } from "../api/client";
import { ApiError } from "../api/errors";
import type { AccountUser } from "../api/types";
import { ACCOUNT_SESSION_MARKER } from "./session";

interface AuthValue {
  user: AccountUser | null;
  loading: boolean;
  refresh(): Promise<void>;
  logout(): Promise<void>;
}

const guestAuth: AuthValue = {
  user: null,
  loading: false,
  refresh: async () => undefined,
  logout: async () => undefined,
};

/** How long to wait before asking again after a failure that was not a 401. */
const RETRY_AFTER_MS = 4000;

function readMarker(): boolean {
  try {
    return localStorage.getItem(ACCOUNT_SESSION_MARKER) === "true";
  } catch {
    return false;
  }
}

function writeMarker(present: boolean): void {
  try {
    if (present) localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
    else localStorage.removeItem(ACCOUNT_SESSION_MARKER);
  } catch {
    // Storage is a hint for the first paint, never the source of truth.
  }
}

/**
 * Who is signed in.
 *
 * The session lives in an HTTP-only cookie the page cannot read, so the only
 * way to know whether it is still valid is to ask `/users/me`. A local marker
 * records that this browser has signed in, so a reader who never has costs no
 * request on every visit.
 *
 * Only a 401 means signed out. Any failed check used to remove the marker, and
 * with it every later check: a network blip or an API restart during a deploy
 * signed the reader out of the page for good while their cookie was still
 * valid. Now anything other than a 401 keeps the marker and asks once more.
 */
const AuthContext = createContext<AuthValue>(guestAuth);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [loading, setLoading] = useState(readMarker);

  const check = useCallback(async (): Promise<"ok" | "signed-out" | "unknown"> => {
    try {
      const account = await getCurrentUser();
      if (typeof account.id !== "string" || typeof account.email !== "string") {
        throw new Error("Malformed account response");
      }
      writeMarker(true);
      setUser(account);
      return "ok";
    } catch (cause: unknown) {
      if (cause instanceof ApiError && cause.status === 401) {
        writeMarker(false);
        setUser(null);
        return "signed-out";
      }
      return "unknown";
    }
  }, []);

  const refresh = useCallback(async () => {
    await check();
    setLoading(false);
  }, [check]);

  useEffect(() => {
    let cancelled = false;
    let retry: number | undefined;
    if (!readMarker()) return;
    const first = window.setTimeout(() => {
      void check().then((outcome) => {
        if (cancelled) return;
        setLoading(false);
        if (outcome === "unknown") {
          retry = window.setTimeout(() => void check(), RETRY_AFTER_MS);
        }
      });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(first);
      if (retry !== undefined) window.clearTimeout(retry);
    };
  }, [check]);

  const logout = useCallback(async () => {
    await logoutAccount();
    writeMarker(false);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, refresh, logout }), [user, loading, refresh, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// The hook and provider deliberately share their private context.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  return useContext(AuthContext);
}
