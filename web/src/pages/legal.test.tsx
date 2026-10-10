/**
 * The privacy policy and terms are reachable without an account, from every
 * surface a reader can arrive on, and are named before anyone signs up.
 */

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { jsonError, jsonOk, makeFields } from "../test/factories";

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = new URL(input, "http://api.test");
      if (url.pathname === "/fields") return Promise.resolve(jsonOk(makeFields()));
      return Promise.resolve(jsonError(401, "Unauthorized"));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("legal pages", () => {
  it("shows the privacy policy to a signed-out reader", async () => {
    renderApp("/privacy");
    expect(await screen.findByRole("heading", { level: 1, name: "Privacy policy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /How long we keep it/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "hello@academious.org" })[0]).toHaveAttribute(
      "href",
      "mailto:hello@academious.org",
    );
  });

  it("shows the terms and links back to the privacy policy", async () => {
    renderApp("/terms");
    expect(await screen.findByRole("heading", { level: 1, name: "Terms of use" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Governing law/ })).toBeInTheDocument();
    const footer = screen.getByText(/See also/).closest("footer");
    expect(within(footer as HTMLElement).getByRole("link", { name: "privacy policy" })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  it("names both documents on the sign-up form without leaving it", async () => {
    renderApp("/signup");
    const terms = await screen.findByRole("link", { name: "terms of use" });
    expect(terms).toHaveAttribute("href", "/terms");
    expect(terms).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "privacy policy" })).toHaveAttribute("href", "/privacy");
  });

  it("links both documents from the landing page footer", async () => {
    renderApp("/");
    const footer = (await screen.findByText(/It is not a search over all published science/)).closest("footer");
    expect(within(footer as HTMLElement).getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    expect(within(footer as HTMLElement).getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  });
});
