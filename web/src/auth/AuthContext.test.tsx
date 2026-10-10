import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { jsonOk } from "../test/factories";
import { AuthProvider, useAuth } from "./AuthContext";
import { ACCOUNT_SESSION_MARKER } from "./session";

const USER = {
  id: "user-1",
  email: "ada@example.org",
  display_name: "Ada",
  is_active: true,
  is_verified: true,
  is_superuser: false,
  recommendation_data_consent: true,
  consent_version: "2026-10-08",
  consented_at: "2026-10-10T00:00:00Z",
};

function Who() {
  const { user, loading } = useAuth();
  return <p>{loading ? "checking" : user ? `signed in as ${user.display_name}` : "signed out"}</p>;
}

function renderWith(responses: Array<() => Promise<Response>>) {
  const fetch = vi.fn(() => (responses.shift() ?? (() => Promise.resolve(new Response("{}", { status: 401 }))))());
  vi.stubGlobal("fetch", fetch);
  render(<AuthProvider><Who /></AuthProvider>);
  return fetch;
}

describe("AuthProvider", () => {
  it("restores the session a reader signed in with last time", async () => {
    localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
    renderWith([() => Promise.resolve(jsonOk(USER))]);

    expect(screen.getByText("checking")).toBeInTheDocument();
    expect(await screen.findByText("signed in as Ada")).toBeInTheDocument();
  });

  it("treats a 401 as signed out, and stops asking", async () => {
    localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
    renderWith([() => Promise.resolve(new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }))]);

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(localStorage.getItem(ACCOUNT_SESSION_MARKER)).toBeNull();
  });

  it("does not sign a reader out because the API was briefly unreachable", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
      const fetch = renderWith([
        () => Promise.resolve(new Response("{}", { status: 503 })),
        () => Promise.resolve(jsonOk(USER)),
      ]);

      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
      expect(localStorage.getItem(ACCOUNT_SESSION_MARKER)).toBe("true");

      await vi.advanceTimersByTimeAsync(5000);
      expect(await screen.findByText("signed in as Ada")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("asks nothing of the server for a browser that has never signed in", () => {
    const fetch = renderWith([]);

    expect(screen.getByText("signed out")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
