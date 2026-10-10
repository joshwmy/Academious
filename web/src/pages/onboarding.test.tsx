/**
 * The newcomer's path: landing page, sign-up, the three-step setup, the feed.
 *
 * The backend is stubbed by pathname and method, and every request is kept,
 * so a test can say what was sent as well as what was shown.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { AccountUser, ProfileDraft, ProfileResponse } from "../api/types";
import { loadProfileDraft, saveProfileDraft } from "../lib/profileStorage";
import { jsonOk, makePage, makeSummary } from "../test/factories";

const USER: AccountUser = {
  id: "user-1",
  email: "ada@example.org",
  display_name: "Ada Lovelace",
  is_active: true,
  is_verified: false,
  is_superuser: false,
  recommendation_data_consent: true,
  consent_version: "2026-10-08",
  consented_at: "2026-10-10T00:00:00Z",
};

function profileResponse(draft: ProfileDraft): ProfileResponse {
  return {
    schema_version: 1,
    draft,
    profile: {
      schema_version: 1,
      model_key: "specter2",
      interests: [],
      preferences: [],
      blocked_topics: [],
      peer_reviewed_only: false,
    },
    summary: { sections: [], preferences: [] },
    preview: [
      {
        rank: 1,
        paper: makeSummary({ id: "p1", title: "A paper picked for you" }),
        matched_interest: "Computer Science",
        matched_interest_key: "field:computer-science",
        reasons: ["Matches Computer Science"],
        is_exploration: false,
        is_retracted: false,
      },
    ],
    issues: [],
    changes: [],
  };
}

interface Call {
  method: string;
  path: string;
  body: unknown;
}

/** A small backend: registration, login, the session user and profile preview. */
function stubBackend({ signedIn = false } = {}) {
  const calls: Call[] = [];
  let session = signedIn;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = init?.method ?? "GET";
      let body: unknown = init?.body;
      if (typeof body === "string") {
        try {
          body = JSON.parse(body);
        } catch {
          // form-encoded login bodies stay as strings
        }
      }
      calls.push({ method, path: url.pathname, body });

      switch (url.pathname) {
        case "/auth/register":
          return Promise.resolve(jsonOk(USER));
        case "/auth/session/login":
          session = true;
          return Promise.resolve(new Response(null, { status: 204 }));
        case "/auth/request-verify-token":
          return Promise.resolve(new Response(null, { status: 202 }));
        case "/users/me":
          return Promise.resolve(session ? jsonOk(USER) : new Response("{}", { status: 401 }));
        case "/profiles/preview": {
          const sent = (body as { draft: ProfileDraft }).draft;
          return Promise.resolve(jsonOk(profileResponse(sent)));
        }
        case "/papers":
          return Promise.resolve(jsonOk(makePage([makeSummary({ id: "l1", title: "A recent paper" })])));
        case "/fields":
          return Promise.resolve(jsonOk({ fields: [], papers_without_field: 0 }));
        default:
          return Promise.resolve(new Response("{}", { status: 404 }));
      }
    }),
  );
  return calls;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

async function audit(container: HTMLElement) {
  const results = await axe.run(container, { rules: { region: { enabled: false } } });
  return results.violations.map((violation) => violation.id);
}

describe("landing page", () => {
  it("greets a newcomer with what Academious does and a way to sign up", async () => {
    stubBackend();
    renderAt("/");

    expect(await screen.findByRole("heading", { level: 1, name: /keep up with your field/i })).toBeInTheDocument();
    const signUp = screen.getAllByRole("link", { name: /create your account|get started/i });
    expect(signUp.every((link) => link.getAttribute("href") === "/signup")).toBe(true);
  });

  it("sends a reader with a saved profile straight to their feed", async () => {
    stubBackend();
    saveProfileDraft(profileResponse({
      fields: ["computer-science"],
      interests: [],
      example_papers: [],
      negatives: [],
      negative_papers: [],
      blocked_topics: [],
      discovery: { freshness: "balanced", exploration: "balanced", publication: "include_preprints" },
    }).draft);
    renderAt("/");

    expect(await screen.findByRole("link", { name: "A paper picked for you" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /keep up with your field/i })).not.toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    stubBackend();
    const { container } = renderAt("/");
    await screen.findByRole("heading", { level: 1, name: /keep up with your field/i });
    expect(await audit(container)).toEqual([]);
  });
});

describe("sign up", () => {
  it("creates the account, signs in and moves straight on to setup", async () => {
    const user = userEvent.setup();
    const calls = stubBackend();
    renderAt("/signup");

    await user.type(await screen.findByLabelText("Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.org");
    await user.type(screen.getByLabelText(/^password/i), "correct horse battery");
    await user.click(screen.getByRole("checkbox", { name: /personalise my feed/i }));
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: /what do you work on/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /welcome, ada/i })).toBeInTheDocument();
    const paths = calls.map((call) => call.path);
    expect(paths).toContain("/auth/register");
    expect(paths).toContain("/auth/session/login");
  });

  it("asks for consent before sending anything", async () => {
    const user = userEvent.setup();
    const calls = stubBackend();
    renderAt("/signup");

    await user.type(await screen.findByLabelText("Name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.org");
    await user.type(screen.getByLabelText(/^password/i), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/tick the box/i);
    expect(calls.some((call) => call.path === "/auth/register")).toBe(false);
  });

  it("explains a taken email in words, not a backend code", async () => {
    const user = userEvent.setup();
    stubBackend();
    vi.mocked(fetch).mockImplementationOnce(() =>
      Promise.resolve(new Response(JSON.stringify({ detail: "REGISTER_USER_ALREADY_EXISTS" }), { status: 400, headers: { "Content-Type": "application/json" } })),
    );
    renderAt("/signup");

    await user.type(await screen.findByLabelText("Name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.org");
    await user.type(screen.getByLabelText(/^password/i), "correct horse battery");
    await user.click(screen.getByRole("checkbox", { name: /personalise my feed/i }));
    await user.click(screen.getByRole("button", { name: "Create account" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/already exists/i);
    expect(alert).not.toHaveTextContent("REGISTER_USER_ALREADY_EXISTS");
  });

  it("has no detectable accessibility violations", async () => {
    stubBackend();
    const { container } = renderAt("/signup");
    await screen.findByRole("heading", { name: "Create your account" });
    expect(await audit(container)).toEqual([]);
  });
});

describe("first-run setup", () => {
  it("turns chosen fields and topics into a profile, then opens the feed", async () => {
    const user = userEvent.setup();
    const calls = stubBackend({ signedIn: true });
    window.localStorage.setItem("academious:has-account-session", "true");
    renderAt("/welcome");

    await user.click(await screen.findByRole("button", { name: "Computer Science" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await user.type(await screen.findByRole("textbox", { name: /add a topic/i }), "protein folding{Enter}");
    expect(screen.getByRole("button", { name: "Remove protein folding" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: /the more you explore/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show my feed" }));

    expect(await screen.findByRole("link", { name: "A paper picked for you" })).toBeInTheDocument();
    // The feed reuses the ranking setup just fetched rather than asking again.
    const previews = calls.filter((call) => call.path === "/profiles/preview");
    expect(previews).toHaveLength(1);
    const preview = previews[0];
    const sent = (preview?.body as { draft: ProfileDraft }).draft;
    expect(sent.fields).toEqual(["computer-science"]);
    expect(sent.interests).toEqual([{ text: "protein folding", importance: "interested" }]);
    await waitFor(() => expect(loadProfileDraft()?.fields).toEqual(["computer-science"]));
  });

  it("will not continue without at least one field", async () => {
    stubBackend({ signedIn: true });
    renderAt("/welcome");

    expect(await screen.findByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("has no detectable accessibility violations", async () => {
    stubBackend({ signedIn: true });
    const { container } = renderAt("/welcome");
    await screen.findByRole("heading", { name: /what do you work on/i });
    expect(await audit(container)).toEqual([]);
  });
});
