/**
 * Card rendering, with a bias toward the content that actually breaks layouts:
 * very long titles, very long author lists, and metadata that contains markup.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { makeSummary } from "../test/factories";
import { PaperCard } from "./PaperCard";

function renderCard(paper = makeSummary(), rank?: number) {
  return render(
    <MemoryRouter>
      <PaperCard paper={paper} {...(rank !== undefined ? { rank } : {})} />
    </MemoryRouter>,
  );
}

describe("PaperCard", () => {
  it("links the title to the paper detail route", () => {
    const paper = makeSummary();
    renderCard(paper);
    const link = screen.getByRole("link", { name: paper.title });
    expect(link).toHaveAttribute("href", `/papers/${paper.id}`);
  });

  it("gives the link the paper title as its accessible name", () => {
    // A card-sized anchor would name itself with the whole card; the title alone
    // is what a screen-reader user needs from a list of links.
    const paper = makeSummary({ title: "A precise accessible name" });
    renderCard(paper);
    expect(screen.getByRole("link", { name: "A precise accessible name" })).toBeInTheDocument();
  });

  it("renders HTML-like metadata as text, never as markup", () => {
    const paper = makeSummary({
      title: '<img src=x onerror="alert(1)"> Structural priors',
      abstract_preview: "<script>alert(document.cookie)</script> We show that…",
      authors: [
        { name: "<b>Bold</b>, A.", position: 0, orcid: null, affiliations: [] },
      ],
      venue: "<iframe src='https://evil.example'></iframe>",
    });
    const { container } = renderCard(paper);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByText(/onerror="alert\(1\)"/)).toBeInTheDocument();
    expect(screen.getByText(/<b>Bold<\/b>, A\./)).toBeInTheDocument();
  });

  it("collapses a long author list rather than printing all of it", () => {
    const paper = makeSummary({
      authors: Array.from({ length: 40 }, (_, index) => ({
        name: `Author ${index}`,
        position: index,
        orcid: null,
        affiliations: [],
      })),
    });
    renderCard(paper);
    expect(screen.getByText(/and 34 others/)).toBeInTheDocument();
  });

  it("renders a very long title without truncating its text content", () => {
    const title = "Supercalifragilistic ".repeat(30).trim();
    renderCard(makeSummary({ title }));
    expect(screen.getByRole("link", { name: title })).toBeInTheDocument();
  });

  it("shows a rank marker in search results and hides it from assistive tech", () => {
    const { container } = renderCard(makeSummary(), 3);
    const rank = container.querySelector(".paper-card__rank");
    expect(rank).toHaveTextContent("3");
    expect(rank).toHaveAttribute("aria-hidden", "true");
  });

  it("marks a retracted paper visibly", () => {
    renderCard(makeSummary({ retraction_status: "retracted" }));
    expect(screen.getByText("Retracted")).toBeInTheDocument();
  });

  it("does not label an ordinary paper with an integrity notice", () => {
    renderCard(makeSummary({ retraction_status: "none" }));
    expect(screen.queryByText("Retracted")).not.toBeInTheDocument();
    expect(screen.queryByText("Corrected")).not.toBeInTheDocument();
  });

  it("omits the date element entirely when no date is known", () => {
    const { container } = renderCard(
      makeSummary({ published_date: null, published_year: null }),
    );
    expect(container.querySelector("time")).toBeNull();
  });
});
