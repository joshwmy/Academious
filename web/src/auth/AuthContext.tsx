import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getCurrentUser, logoutAccount } from "../api/client";
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
const AuthContext = createContext<AuthValue>(guestAuth);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [loading, setLoading] = useState(
    () => localStorage.getItem(ACCOUNT_SESSION_MARKER) === "true",
  );

  const refresh = useCallback(async () => {
    try {
      const account = await getCurrentUser();
      if (typeof account.id !== "string" || typeof account.email !== "string") {
        throw new Error("Malformed account response");
      }
      localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
      setUser(account);
    } catch {
      localStorage.removeItem(ACCOUNT_SESSION_MARKER);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (localStorage.getItem(ACCOUNT_SESSION_MARKER) !== "true") return;
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const logout = useCallback(async () => {
    await logoutAccount();
    localStorage.removeItem(ACCOUNT_SESSION_MARKER);
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
