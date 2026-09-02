import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FIELDS, NO_FILTERS, SOURCES, type PaperFilters } from "../lib/filters";
import { FilterPanel } from "./FilterPanel";

/**
 * The panel asks `/fields` for the paper counts. Stubbing it is not the point
 * of most tests here, so the default stub answers with counts of zero and the
 * tests that care about numbers pass their own.
 */
function stubFields(counts: Record<string, number> = {}, papersWithoutField = 0) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            fields: FIELDS.map((field) => ({
              slug: field.slug,
              label: field.label,
              paper_count: counts[field.slug] ?? 0,
            })),
            papers_without_field: papersWithoutField,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    ),
  );
}

function renderPanel(filters: PaperFilters = NO_FILTERS) {
  const onChange = vi.fn();
  render(<FilterPanel filters={filters} onChange={onChange} />);
  return onChange;
}

describe("FilterPanel", () => {
  it("groups its controls so a screen reader announces what each one filters", () => {
    renderPanel();

    expect(screen.getByRole("group", { name: /source/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /type/i })).toBeInTheDocument();
  });

  it("reflects the filters it is given rather than holding its own state", () => {
    renderPanel({
      sources: ["arxiv"],
      fields: ["chemistry"],
      preprints: "exclude_preprints",
      peerReviewed: true,
      openAccess: false,
    });

    expect(screen.getByRole("checkbox", { name: /arxiv/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^chemistry/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: /exclude preprints/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /peer-reviewed/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /open access/i })).not.toBeChecked();
  });

  it("reports a source being added", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel();

    await user.click(screen.getByRole("checkbox", { name: /arxiv/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, sources: ["arxiv"] });
  });

  it("offers Europe PMC alongside the other sources", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel();

    await user.click(screen.getByRole("checkbox", { name: /europe pmc/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, sources: ["europepmc"] });
  });

  it("reports a source being removed without disturbing the others", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel({ ...NO_FILTERS, sources: ["arxiv", "biorxiv"] });

    await user.click(screen.getByRole("checkbox", { name: /arxiv/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, sources: ["biorxiv"] });
  });

  it("reports a preprint policy change", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel();

    await user.click(screen.getByRole("radio", { name: /only preprints/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, preprints: "only_preprints" });
  });

  it("reports the boolean filters", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel();

    await user.click(screen.getByRole("checkbox", { name: /open access/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, openAccess: true });
  });

  it("offers no clear action when there is nothing to clear", () => {
    renderPanel();

    expect(screen.queryByRole("button", { name: /clear/i })).not.toBeInTheDocument();
  });

  it("clears every filter at once", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel({
      sources: ["arxiv"],
      fields: ["chemistry"],
      preprints: "only_preprints",
      peerReviewed: true,
      openAccess: true,
    });

    await user.click(screen.getByRole("button", { name: /clear/i }));

    expect(onChange).toHaveBeenCalledWith(NO_FILTERS);
  });

  it("says how many filters are active, so the state is legible when collapsed on a phone", () => {
    renderPanel({ ...NO_FILTERS, sources: ["arxiv"], openAccess: true });

    expect(screen.getByRole("status")).toHaveTextContent("2 filters");
  });

  it("reports the active count only while filters are set", () => {
    // This summary used to carry a caveat - that search results were not
    // filtered - because GET /search accepted no filter parameters. It does
    // now (WEB-010), so the caveat is gone and the count is the whole message.
    const { unmount } = render(<FilterPanel filters={NO_FILTERS} onChange={vi.fn()} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    unmount();

    render(<FilterPanel filters={{ ...NO_FILTERS, openAccess: true }} onChange={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("1 filter active.");
    expect(screen.queryByText(/not filtered/i)).not.toBeInTheDocument();
  });

  it("lists every source the backend knows about", () => {
    renderPanel();

    const sources = within(screen.getByRole("group", { name: /source/i })).getAllByRole(
      "checkbox",
    );
    // Counted against the registry rather than a literal: a hard-coded number
    // makes this test the thing that breaks when a connector is added, which
    // is the opposite of what it is for.
    expect(sources).toHaveLength(SOURCES.length);
    expect(sources.map((el) => el.closest("label")?.textContent?.trim())).toEqual(
      SOURCES.map((source) => source.label),
    );
  });
});

describe("FilterPanel, subject fields", () => {
  it("offers every field the backend accepts", () => {
    stubFields();
    renderPanel();

    const group = screen.getByRole("group", { name: /field/i });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(FIELDS.length);
  });

  it("reports a field being selected", async () => {
    const user = userEvent.setup();
    stubFields();
    const onChange = renderPanel();

    await user.click(screen.getByRole("checkbox", { name: /^neuroscience/i }));

    expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, fields: ["neuroscience"] });
  });

  it("orders selected fields canonically rather than by the order they were clicked", async () => {
    const user = userEvent.setup();
    stubFields();
    const onChange = renderPanel({ ...NO_FILTERS, fields: ["neuroscience"] });

    await user.click(screen.getByRole("checkbox", { name: /^chemistry/i }));

    expect(onChange).toHaveBeenCalledWith({
      ...NO_FILTERS,
      fields: ["chemistry", "neuroscience"],
    });
  });

  it("shows how many papers are in each field", async () => {
    stubFields({ neuroscience: 1234 });
    renderPanel();

    expect(await screen.findByText("1,234")).toBeInTheDocument();
  });

  it("says how many papers no field can reach, because selecting one hides them", async () => {
    stubFields({}, 57_000);
    renderPanel();

    expect(await screen.findByText(/57,000 papers carry no field/i)).toBeInTheDocument();
  });

  it("still offers the fields when the counts cannot be fetched", async () => {
    // The vocabulary is a constant and the counts are a nicety. A failed
    // request must cost the numbers, never the filter.
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    renderPanel();

    const group = screen.getByRole("group", { name: /field/i });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(FIELDS.length);
    expect(screen.queryByText(/carry no field/i)).not.toBeInTheDocument();
  });
});
