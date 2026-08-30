/**
 * Automated accessibility checks over the three real pages.
 *
 * axe catches the mechanical violations - unlabelled controls, broken heading
 * order, insufficient contrast on the tokens, list markup that is not a list.
 * It does not catch whether the product makes sense to use, which is why the
 * page tests query by role and accessible name rather than by class.
 */

import { render } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { jsonOk, makeDetail, makePage, makeSummary } from "./factories";

function stub(response: () => Response) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response())));
}

async function audit(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: {
      // Landmark and region rules assume a whole document; these render a
      // subtree into a bare div, so they report noise rather than defects.
      region: { enabled: false },
    },
  });
  return results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    nodes: violation.nodes.length,
  }));
}

describe("accessibility", () => {
  it("the feed has no detectable violations", async () => {
    stub(() =>
      jsonOk(
        makePage(
          [
            makeSummary({ id: "a", title: "A paper about graphs" }),
            makeSummary({ id: "b", title: "Another paper", retraction_status: "retracted" }),
          ],
          { total: 100 },
        ),
      ),
    );
    const { container, findByRole } = render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await findByRole("link", { name: "A paper about graphs" });

    expect(await audit(container)).toEqual([]);
  });

  it("search results have no detectable violations", async () => {
    stub(() =>
      jsonOk({
        query: "graph",
        count: 2,
        limit: 20,
        results: [
          { rank: 1, paper: makeSummary({ id: "a", title: "First result" }) },
          { rank: 2, paper: makeSummary({ id: "b", title: "Second result" }) },
        ],
      }),
    );
    const { container, findByRole } = render(
      <MemoryRouter initialEntries={["/search?q=graph"]}>
        <App />
      </MemoryRouter>,
    );
    await findByRole("link", { name: "First result" });

    expect(await audit(container)).toEqual([]);
  });

  it("the paper detail page has no detectable violations", async () => {
    stub(() =>
      jsonOk(
        makeDetail({
          retraction_status: "retracted",
          retraction_notice_url: "https://example.org/notice",
        }),
      ),
    );
    const { container, findByRole } = render(
      <MemoryRouter initialEntries={["/papers/11111111-1111-4111-8111-111111111111"]}>
        <App />
      </MemoryRouter>,
    );
    await findByRole("heading", { level: 1 });

    expect(await audit(container)).toEqual([]);
  });
});
