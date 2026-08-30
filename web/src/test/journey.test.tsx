/**
 * The whole public journey, against responses captured from the real backend.
 *
 * `fixtures/api-contract.json` is not hand-written: it is the literal output of
 * the running FastAPI application against the development corpus. That is the
 * point - a hand-made fixture proves the frontend agrees with my idea of the
 * contract, while this proves it agrees with the contract.
 *
 * No browser and no SPECTER2. The backend keeps its own model integration test;
 * making this one load 440 MB of weights would buy nothing it does not already
 * cover.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import contract from "./fixtures/api-contract.json";

function stubRealBackend() {
  const mock = vi.fn((input: string) => {
    const url = new URL(input, "http://api.test");
    const body =
      url.pathname === "/papers"
        ? contract.papers
        : url.pathname === "/search"
          ? contract.search
          : contract.detail;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("public journey, against captured backend responses", () => {
  it("browses, opens a paper, goes back, searches, and opens a result", async () => {
    const user = userEvent.setup();
    stubRealBackend();

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    // 1. The feed loads real papers.
    const firstTitle = contract.papers.results[0]!.title;
    await screen.findByRole("link", { name: firstTitle });
    expect(screen.getByRole("heading", { level: 1, name: /recent papers/i })).toBeInTheDocument();

    // 2. Opening one shows the detail page.
    await user.click(screen.getByRole("link", { name: firstTitle }));
    await screen.findByRole("heading", { level: 1, name: contract.detail.title });
    expect(screen.getByRole("heading", { name: "Abstract" })).toBeInTheDocument();

    // 3. Back returns to the feed.
    await user.click(screen.getByRole("link", { name: /recent papers/i }));
    await screen.findByRole("heading", { level: 1, name: /recent papers/i });

    // 4. Searching navigates and renders ranked results.
    await user.type(screen.getByRole("searchbox"), "graph neural networks");
    await user.click(screen.getByRole("button", { name: "Search" }));
    const list = await screen.findByRole("list", { name: "Search results" });

    // The order is the backend's, unchanged.
    expect(
      within(list)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(contract.search.results.map((hit) => hit.paper.title));

    // 5. A result opens its paper.
    const firstResult = contract.search.results[0]!.paper.title;
    await user.click(within(list).getByRole("link", { name: firstResult }));
    expect(
      await screen.findByRole("heading", { level: 1, name: contract.detail.title }),
    ).toBeInTheDocument();
  });

  it("parses every field the real contract carries without losing data", async () => {
    stubRealBackend();
    render(
      <MemoryRouter initialEntries={["/papers/" + contract.detail.id]}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { level: 1, name: contract.detail.title });

    if (contract.detail.abstract) {
      // The whole abstract, not the preview.
      expect(screen.getByText(contract.detail.abstract)).toBeInTheDocument();
    }
    // Author names contain punctuation that would need escaping as a regex,
    // so the rendered author line is matched as a plain substring instead.
    const authorLine = screen.getByText((_content, element) =>
      element?.className === "paper-detail__authors" ? true : false,
    );
    for (const author of contract.detail.authors.slice(0, 3)) {
      expect(authorLine.textContent ?? "").toContain(author.name);
    }
  });

  it("never renders an internal field the backend does not expose", async () => {
    stubRealBackend();
    const { container } = render(
      <MemoryRouter initialEntries={["/papers/" + contract.detail.id]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 1 });

    const html = container.innerHTML;
    for (const internal of ["model_key", "specter2", "embedding", "search_tsv", "title_norm"]) {
      expect(html).not.toContain(internal);
    }
  });
});
