/**
 * The shell's footer carries a licence obligation, so it is asserted.
 *
 * Retraction status is derived from the Retraction Watch database, which
 * Crossref distributes under CC-BY 4.0. Attribution is the entire consideration
 * for that licence, and it went unpaid from the day retraction badges shipped
 * until 2026-09-03 because nothing here noticed it was missing. A copy edit
 * that removes the credit should fail a test rather than quietly put the
 * project back in breach.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

function renderShell() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("the shell itself fetches nothing"))),
  );
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AppShell />
    </MemoryRouter>,
  );
}

describe("AppShell footer", () => {
  it("credits Retraction Watch, because CC-BY 4.0 requires it", () => {
    renderShell();

    const credit = screen.getByRole("link", { name: /retraction watch database/i });
    expect(credit).toHaveAttribute("href", expect.stringContaining("retraction-watch-data"));
  });

  it("names the licence the credit is given under", () => {
    renderShell();

    const licence = screen.getByRole("link", { name: /cc-by 4\.0/i });
    expect(licence).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
  });

  it("names Crossref as the distributor", () => {
    renderShell();

    expect(screen.getByText(/distributed by crossref/i)).toBeInTheDocument();
  });

  it("describes the corpus including OpenAlex", () => {
    // OpenAlex supplies the largest single share of the corpus and the copy
    // used to omit it. CC0 asks for no attribution; this is about the sentence
    // being true.
    renderShell();

    const note = screen.getByText(/curated corpus of recent research/i);
    for (const source of ["arXiv", "bioRxiv/medRxiv", "Europe PMC", "OpenAlex"]) {
      expect(note).toHaveTextContent(source);
    }
  });
});
