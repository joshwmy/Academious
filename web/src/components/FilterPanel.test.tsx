import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NO_FILTERS, type FeedFilters } from "../lib/filters";
import { FilterPanel } from "./FilterPanel";

function renderPanel(filters: FeedFilters = NO_FILTERS) {
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
      preprints: "exclude_preprints",
      peerReviewed: true,
      openAccess: false,
    });

    expect(screen.getByRole("checkbox", { name: /arxiv/i })).toBeChecked();
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

  it("says that filters do not reach search, only while they are set", () => {
    // The asymmetry is real - GET /search takes no filter parameters - so the
    // interface states it rather than letting a reader assume it carries over.
    const { unmount } = render(<FilterPanel filters={NO_FILTERS} onChange={vi.fn()} />);
    expect(screen.queryByText(/search results are not filtered/i)).not.toBeInTheDocument();
    unmount();

    render(<FilterPanel filters={{ ...NO_FILTERS, openAccess: true }} onChange={vi.fn()} />);
    expect(screen.getByText(/search results are not filtered/i)).toBeInTheDocument();
  });

  it("lists every source the backend knows about", () => {
    renderPanel();

    const sources = within(screen.getByRole("group", { name: /source/i })).getAllByRole(
      "checkbox",
    );
    expect(sources).toHaveLength(3);
  });
});
