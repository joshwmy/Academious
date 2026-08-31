/**
 * Page behaviour, driven through the router the way a user drives it.
 *
 * These tests mount the real application shell and real routes, stubbing only
 * `fetch`. That is the level at which the interesting bugs live: a URL that does
 * not update, a result list quietly re-sorted, an error state offering a retry
 * that would only repeat the mistake.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { jsonError, jsonOk, makeDetail, makePage, makeSummary } from "../test/factories";

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/** Routes each request by pathname so a test can describe a whole backend. */
function stubApi(handlers: Record<string, (url: URL) => Response>) {
  const mock = vi.fn((input: string) => {
    const url = new URL(input, "http://api.test");
    const handler = handlers[url.pathname] ?? handlers["*"];
    if (!handler) return Promise.reject(new Error("unhandled path in test stub"));
    return Promise.resolve(handler(url));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function searchCalls(mock: ReturnType<typeof stubApi>) {
  return mock.mock.calls.filter(([input]) => String(input).includes("/search"));
}

// -------------------------------------------------------------------- feed

describe("feed", () => {
  it("renders papers returned by the API", async () => {
    stubApi({
      "/papers": () =>
        jsonOk(
          makePage([
            makeSummary({ id: "a", title: "First paper" }),
            makeSummary({ id: "b", title: "Second paper" }),
          ]),
        ),
    });
    renderApp();

    expect(await screen.findByRole("link", { name: "First paper" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Second paper" })).toBeInTheDocument();
  });

  it("links each paper to its detail route", async () => {
    stubApi({
      "/papers": () => jsonOk(makePage([makeSummary({ id: "abc", title: "Openable" })])),
    });
    renderApp();

    const link = await screen.findByRole("link", { name: "Openable" });
    expect(link).toHaveAttribute("href", "/papers/abc");
  });

  it("shows a loading state before data arrives, not an empty state", async () => {
    let release: (value: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    renderApp();

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    expect(screen.queryByText(/no papers yet/i)).not.toBeInTheDocument();

    release(jsonOk(makePage([makeSummary({ title: "Arrived" })])));
    expect(await screen.findByRole("link", { name: "Arrived" })).toBeInTheDocument();
  });

  it("shows an empty state when the corpus is empty", async () => {
    stubApi({ "/papers": () => jsonOk(makePage([])) });
    renderApp();
    expect(await screen.findByText(/no papers yet/i)).toBeInTheDocument();
  });

  it("requests the next offset when the user pages forward", async () => {
    const user = userEvent.setup();
    const mock = stubApi({
      "/papers": (url) => {
        const offset = Number(url.searchParams.get("offset") ?? "0");
        return jsonOk(
          makePage([makeSummary({ id: "p" + offset, title: "Paper at " + offset })], {
            offset,
            total: 100,
          }),
        );
      },
    });
    renderApp();

    await screen.findByRole("link", { name: "Paper at 0" });
    await user.click(screen.getByRole("button", { name: /next page/i }));

    expect(await screen.findByRole("link", { name: "Paper at 20" })).toBeInTheDocument();
    const lastUrl = new URL(mock.mock.calls.at(-1)![0] as string, "http://api.test");
    expect(lastUrl.searchParams.get("offset")).toBe("20");
  });

  it("disables Previous on the first page", async () => {
    stubApi({ "/papers": () => jsonOk(makePage([makeSummary()], { total: 100 })) });
    renderApp();
    await screen.findByRole("link", { name: /neural message passing/i });
    expect(screen.getByRole("button", { name: /previous page/i })).toBeDisabled();
  });

  it("reads the starting offset from the URL", async () => {
    const mock = stubApi({
      "/papers": () => jsonOk(makePage([makeSummary()], { offset: 40, total: 100 })),
    });
    renderApp("/?offset=40");
    await screen.findByRole("link", { name: /neural message passing/i });
    const url = new URL(mock.mock.calls[0]![0] as string, "http://api.test");
    expect(url.searchParams.get("offset")).toBe("40");
  });

  it("offers a retry when the API is unreachable", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        attempts += 1;
        if (attempts === 1) return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(jsonOk(makePage([makeSummary({ title: "Recovered" })])));
      }),
    );
    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach academious/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("link", { name: "Recovered" })).toBeInTheDocument();
  });
});

// ----------------------------------------------------------- feed filters

describe("feed filters", () => {
  /** The filter parameters of the most recent /papers request. */
  function lastFilterParams(mock: ReturnType<typeof stubApi>) {
    const url = new URL(mock.mock.calls.at(-1)![0] as string, "http://api.test");
    return {
      source: url.searchParams.getAll("source"),
      preprints: url.searchParams.get("preprints"),
      peer_reviewed: url.searchParams.get("peer_reviewed"),
      open_access: url.searchParams.get("open_access"),
      offset: url.searchParams.get("offset"),
    };
  }

  const onePage = () => jsonOk(makePage([makeSummary({ id: "x", title: "A paper" })], { total: 100 }));

  it("sends no filter parameters when the URL carries none", async () => {
    const mock = stubApi({ "/papers": onePage });
    renderApp();

    await screen.findByRole("link", { name: "A paper" });
    expect(lastFilterParams(mock)).toMatchObject({
      source: [],
      preprints: null,
      peer_reviewed: null,
      open_access: null,
    });
  });

  it("applies the filters the URL carries, so a filtered feed is linkable", async () => {
    const mock = stubApi({ "/papers": onePage });
    renderApp("/?source=arxiv&preprints=only_preprints&open_access=true");

    await screen.findByRole("link", { name: "A paper" });
    expect(lastFilterParams(mock)).toMatchObject({
      source: ["arxiv"],
      preprints: "only_preprints",
      open_access: "true",
    });
    expect(screen.getByRole("checkbox", { name: /arxiv/i })).toBeChecked();
  });

  it("drops a source the backend does not know rather than sending a 422", async () => {
    const mock = stubApi({ "/papers": onePage });
    renderApp("/?source=arxiv&source=nonsense");

    await screen.findByRole("link", { name: "A paper" });
    expect(lastFilterParams(mock).source).toEqual(["arxiv"]);
  });

  it("requests again with the new filter when one is toggled", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": onePage });
    renderApp();

    await screen.findByRole("link", { name: "A paper" });
    await user.click(screen.getByRole("checkbox", { name: /open access only/i }));

    await waitFor(() => expect(lastFilterParams(mock).open_access).toBe("true"));
  });

  it("returns to the first page when a filter changes", async () => {
    // Page 3 of an unfiltered feed is not page 3 of a filtered one, and there
    // may be no page 3 at all: staying put shows an empty page for results
    // that exist.
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": onePage });
    renderApp("/?offset=40");

    await screen.findByRole("link", { name: "A paper" });
    expect(lastFilterParams(mock).offset).toBe("40");

    await user.click(screen.getByRole("checkbox", { name: /peer-reviewed only/i }));

    await waitFor(() => expect(lastFilterParams(mock).peer_reviewed).toBe("true"));
    expect(lastFilterParams(mock).offset).toBe("0");
  });

  it("keeps the filters while paging", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": onePage });
    renderApp("/?source=biorxiv");

    await screen.findByRole("link", { name: "A paper" });
    await user.click(screen.getByRole("button", { name: /next page/i }));

    await waitFor(() => expect(lastFilterParams(mock).offset).toBe("20"));
    expect(lastFilterParams(mock).source).toEqual(["biorxiv"]);
  });

  it("clears every filter at once, and the URL with them", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": onePage });
    renderApp("/?source=arxiv&peer_reviewed=true");

    await screen.findByRole("link", { name: "A paper" });
    await user.click(screen.getByRole("button", { name: /clear filters/i }));

    await waitFor(() =>
      expect(lastFilterParams(mock)).toMatchObject({ source: [], peer_reviewed: null }),
    );
  });

  it("issues one request per filter change, not one per render", async () => {
    // The filters are derived from the URL on every render, so an unmemoised
    // object would give `useRequest` a new request identity each time and
    // refetch forever - spending the reader's rate-limit budget on nothing.
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": onePage });
    renderApp();

    await screen.findByRole("link", { name: "A paper" });
    const before = mock.mock.calls.length;

    await user.click(screen.getByRole("checkbox", { name: /open access only/i }));
    await waitFor(() => expect(lastFilterParams(mock).open_access).toBe("true"));

    expect(mock.mock.calls.length).toBe(before + 1);
  });

  it("distinguishes an empty corpus from a filter that matched nothing", async () => {
    stubApi({ "/papers": () => jsonOk(makePage([])) });
    renderApp("/?open_access=true");

    expect(await screen.findByText(/no papers match/i)).toBeInTheDocument();
    expect(screen.queryByText(/no papers yet/i)).not.toBeInTheDocument();
  });

  it("offers a way out of a filter that matched nothing", async () => {
    const user = userEvent.setup();
    const mock = stubApi({
      "/papers": (url) =>
        url.searchParams.get("open_access") === "true"
          ? jsonOk(makePage([]))
          : jsonOk(makePage([makeSummary({ title: "Everything" })])),
    });
    renderApp("/?open_access=true");

    await screen.findByText(/no papers match/i);
    await user.click(screen.getAllByRole("button", { name: /clear filters/i })[0]!);

    expect(await screen.findByRole("link", { name: "Everything" })).toBeInTheDocument();
    expect(lastFilterParams(mock).open_access).toBeNull();
  });
});

// ------------------------------------------------------------------ search

describe("search", () => {
  it("puts the query in the URL and issues exactly one request", async () => {
    const user = userEvent.setup();
    const mock = stubApi({
      "/papers": () => jsonOk(makePage([])),
      "/search": () =>
        jsonOk({ query: "graph neural networks", count: 0, limit: 20, results: [] }),
    });
    renderApp();
    await screen.findByText(/no papers yet/i);

    await user.type(screen.getByRole("searchbox"), "graph neural networks");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByRole("heading", { name: /results for/i });
    // One deliberate submission, one request. Typing must not search.
    expect(searchCalls(mock)).toHaveLength(1);
    const url = new URL(searchCalls(mock)[0]![0] as string, "http://api.test");
    expect(url.searchParams.get("q")).toBe("graph neural networks");
  });

  it("does not search while the user is typing", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": () => jsonOk(makePage([])) });
    renderApp();
    await screen.findByText(/no papers yet/i);

    await user.type(screen.getByRole("searchbox"), "graph neural networks");

    expect(searchCalls(mock)).toHaveLength(0);
  });

  it("refuses to submit a whitespace-only query", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/papers": () => jsonOk(makePage([])) });
    renderApp();
    await screen.findByText(/no papers yet/i);

    await user.type(screen.getByRole("searchbox"), "   ");
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
    expect(searchCalls(mock)).toHaveLength(0);
  });

  it("renders results in the backend order, not sorted by date or title", async () => {
    stubApi({
      "/search": () =>
        jsonOk({
          query: "graph",
          count: 3,
          limit: 20,
          results: [
            {
              rank: 1,
              paper: makeSummary({ id: "z", title: "Zebra", published_date: "2020-01-01" }),
            },
            {
              rank: 2,
              paper: makeSummary({ id: "a", title: "Apple", published_date: "2026-01-01" }),
            },
            {
              rank: 3,
              paper: makeSummary({ id: "m", title: "Mango", published_date: "2023-01-01" }),
            },
          ],
        }),
    });
    renderApp("/search?q=graph");

    const list = await screen.findByRole("list", { name: "Search results" });
    const titles = within(list)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(titles).toEqual(["Zebra", "Apple", "Mango"]);
  });

  it("explains that no results means this corpus, not all of science", async () => {
    stubApi({ "/search": () => jsonOk({ query: "zzz", count: 0, limit: 20, results: [] }) });
    renderApp("/search?q=zzz");

    expect(await screen.findByText(/no matching papers/i)).toBeInTheDocument();
    expect(screen.getByText(/academious corpus/i)).toBeInTheDocument();
    expect(screen.getByText(/not the whole of published science/i)).toBeInTheDocument();
  });

  it("prompts for a query when the URL carries none", async () => {
    stubApi({});
    renderApp("/search");
    expect(await screen.findByText(/enter a search/i)).toBeInTheDocument();
  });

  it("tells a rate-limited user how long to wait and does not auto-retry", async () => {
    const mock = stubApi({
      "/search": () => jsonError(429, "Rate limit exceeded. Please slow down.", "42"),
    });
    renderApp("/search?q=graph");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/too many requests/i);
    expect(alert).toHaveTextContent(/42 seconds/);

    // No retry storm: the failure stays put until the user asks again.
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(searchCalls(mock)).toHaveLength(1);
  });

  it("explains a 503 as search being busy and offers a manual retry", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        attempts += 1;
        if (attempts === 1) {
          return Promise.resolve(jsonError(503, "Search is temporarily at capacity.", "5"));
        }
        return Promise.resolve(
          jsonOk({
            query: "graph",
            count: 1,
            limit: 20,
            results: [{ rank: 1, paper: makeSummary({ title: "Now available" }) }],
          }),
        );
      }),
    );
    renderApp("/search?q=graph");

    expect(await screen.findByRole("alert")).toHaveTextContent(/search is busy/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("link", { name: "Now available" })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("offers no retry for a rejected query, because retrying repeats the mistake", async () => {
    stubApi({
      "/search": () => jsonError(422, "q: String should have at most 512 characters"),
    });
    renderApp("/search?q=graph");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not valid/i);
    expect(within(alert).queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ detail

describe("search filters", () => {
  /** The filter parameters of the most recent /search request. */
  function lastSearchParams(mock: ReturnType<typeof stubApi>) {
    const url = new URL(searchCalls(mock).at(-1)![0] as string, "http://api.test");
    return {
      q: url.searchParams.get("q"),
      source: url.searchParams.getAll("source"),
      preprints: url.searchParams.get("preprints"),
      peer_reviewed: url.searchParams.get("peer_reviewed"),
      open_access: url.searchParams.get("open_access"),
    };
  }

  const oneHit = () =>
    jsonOk({
      query: "graph",
      count: 1,
      limit: 20,
      results: [{ rank: 1, paper: makeSummary({ id: "x", title: "A paper" }) }],
    });

  it("sends no filter parameters when the URL carries none", async () => {
    // The Phase 2 benchmark measured an unfiltered search. An unfiltered
    // request must stay byte-identical to the one made before filters existed.
    const mock = stubApi({ "/search": oneHit });
    renderApp("/search?q=graph");

    await screen.findByRole("link", { name: "A paper" });
    expect(lastSearchParams(mock)).toMatchObject({
      source: [],
      preprints: null,
      peer_reviewed: null,
      open_access: null,
    });
  });

  it("applies the filters the URL carries, so a filtered search is linkable", async () => {
    const mock = stubApi({ "/search": oneHit });
    renderApp("/search?q=graph&source=arxiv&preprints=only_preprints&open_access=true");

    await screen.findByRole("link", { name: "A paper" });
    expect(lastSearchParams(mock)).toMatchObject({
      q: "graph",
      source: ["arxiv"],
      preprints: "only_preprints",
      open_access: "true",
    });
    expect(screen.getByRole("checkbox", { name: /arxiv/i })).toBeChecked();
  });

  it("keeps the query when a filter is toggled", async () => {
    // The failure this guards against loses the query and lands the reader on
    // an empty search page, which reads as "your search broke".
    const user = userEvent.setup();
    const mock = stubApi({ "/search": oneHit });
    renderApp("/search?q=graph");

    await screen.findByRole("link", { name: "A paper" });
    await user.click(screen.getByRole("checkbox", { name: /open access only/i }));

    await waitFor(() => expect(lastSearchParams(mock).open_access).toBe("true"));
    expect(lastSearchParams(mock).q).toBe("graph");
  });

  it("carries the filters into a new search from the search bar", async () => {
    const user = userEvent.setup();
    const mock = stubApi({ "/search": oneHit });
    renderApp("/search?q=graph&peer_reviewed=true");

    await screen.findByRole("link", { name: "A paper" });
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "transformers");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(lastSearchParams(mock).q).toBe("transformers"));
    expect(lastSearchParams(mock).peer_reviewed).toBe("true");
  });

  it("distinguishes no matches from no matches under these filters", async () => {
    const user = userEvent.setup();
    stubApi({
      "/search": () => jsonOk({ query: "graph", count: 0, limit: 20, results: [] }),
    });
    renderApp("/search?q=graph&peer_reviewed=true");

    const panel = await screen.findByText(/no papers match these filters/i);

    // Scoped to the empty state: the filter panel offers its own clear button,
    // and this test is about the one the reader is looking at when they find
    // nothing.
    const emptyState = panel.closest(".state-panel") as HTMLElement;
    await user.click(within(emptyState).getByRole("button", { name: /clear filters/i }));

    expect(await screen.findByText(/no matching papers/i)).toBeInTheDocument();
  });
});

describe("paper detail", () => {
  const PAPER_PATH = "/papers/11111111-1111-4111-8111-111111111111";

  it("shows the full record", async () => {
    stubApi({ "*": () => jsonOk(makeDetail({ title: "A detailed paper" })) });
    renderApp(PAPER_PATH);

    expect(
      await screen.findByRole("heading", { level: 1, name: "A detailed paper" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Abstract" })).toBeInTheDocument();
    expect(screen.getByText(/rendered whole on the detail page/)).toBeInTheDocument();
  });

  it("opens external links safely in a new tab", async () => {
    stubApi({ "*": () => jsonOk(makeDetail()) });
    renderApp(PAPER_PATH);

    const pdf = await screen.findByRole("link", { name: /read pdf/i });
    expect(pdf).toHaveAttribute("href", "https://example.org/paper.pdf");
    expect(pdf).toHaveAttribute("target", "_blank");
    expect(pdf).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("refuses to render a hostile URL as a link", async () => {
    stubApi({
      "*": () =>
        jsonOk(
          makeDetail({
            open_access: {
              status: "green",
              is_open: true,
              url: "javascript:alert(document.cookie)",
              pdf_url: "data:text/html,<script>alert(1)</script>",
              licence: null,
            },
          }),
        ),
    });
    const { container } = renderApp(PAPER_PATH);
    await screen.findByRole("heading", { level: 1 });

    for (const anchor of container.querySelectorAll("a")) {
      expect(anchor.getAttribute("href") ?? "").not.toMatch(/^javascript:|^data:/i);
    }
  });

  it("renders HTML-like abstract content as text", async () => {
    stubApi({
      "*": () =>
        jsonOk(
          makeDetail({
            abstract: "<script>alert(document.cookie)</script> We evaluate the method.",
          }),
        ),
    });
    const { container } = renderApp(PAPER_PATH);
    await screen.findByRole("heading", { level: 1 });

    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/alert\(document\.cookie\)/)).toBeInTheDocument();
  });

  it("makes a retraction impossible to mistake for ordinary metadata", async () => {
    stubApi({
      "*": () =>
        jsonOk(
          makeDetail({
            retraction_status: "retracted",
            retraction_notice_url: "https://example.org/notice",
          }),
        ),
    });
    renderApp(PAPER_PATH);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/retracted/i);
    expect(alert).toHaveTextContent(/withdrawn from the scientific record/i);
    expect(within(alert).getByRole("link", { name: /read the notice/i })).toBeInTheDocument();
  });

  it("shows a 404 for a paper that is not in the corpus", async () => {
    stubApi({ "*": () => jsonError(404, "Paper not found") });
    renderApp("/papers/00000000-0000-4000-8000-000000000000");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/paper not found/i);
    expect(within(alert).queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("shows a not-found page for an unknown route", async () => {
    stubApi({});
    renderApp("/nonsense");
    expect(await screen.findByRole("heading", { name: /page not found/i })).toBeInTheDocument();
  });
});
