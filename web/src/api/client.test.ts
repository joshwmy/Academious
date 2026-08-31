/**
 * The API client's contract with the backend.
 *
 * These assert the shape of the request that goes out and the classification of
 * what comes back, because a page's error handling is only as good as the
 * `kind` it is handed.
 */

import { describe, expect, it, vi } from "vitest";
import { getPaper, listPapers, searchPapers } from "./client";
import { ApiError } from "./errors";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function stubFetch(response: Response | Promise<Response>) {
  const mock = vi.fn((_input: string, _init?: RequestInit) => Promise.resolve(response));
  vi.stubGlobal("fetch", mock);
  return mock;
}

function requestedUrl(mock: ReturnType<typeof stubFetch>): URL {
  return new URL(mock.mock.calls[0]![0], "http://api.test");
}

const emptyPage = { page: { limit: 20, offset: 0, total: 0, returned: 0, has_more: false }, results: [] };

describe("listPapers", () => {
  it("requests /papers with no parameters by default", async () => {
    const mock = stubFetch(jsonResponse(emptyPage));
    await listPapers();
    expect(requestedUrl(mock).pathname).toBe("/papers");
    expect(requestedUrl(mock).search).toBe("");
  });

  it("passes pagination through as query parameters", async () => {
    const mock = stubFetch(jsonResponse(emptyPage));
    await listPapers({ limit: 20, offset: 40 });
    const url = requestedUrl(mock);
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("offset")).toBe("40");
  });

  it("repeats array filters rather than joining them", async () => {
    const mock = stubFetch(jsonResponse(emptyPage));
    await listPapers({ source: ["arxiv", "biorxiv"] });
    expect(requestedUrl(mock).searchParams.getAll("source")).toEqual(["arxiv", "biorxiv"]);
  });

  it("omits undefined parameters entirely", async () => {
    const mock = stubFetch(jsonResponse(emptyPage));
    await listPapers({ limit: 20, offset: undefined });
    expect(requestedUrl(mock).searchParams.has("offset")).toBe(false);
  });

  it("parses an empty result page without treating it as an error", async () => {
    stubFetch(jsonResponse(emptyPage));
    const page = await listPapers();
    expect(page.results).toEqual([]);
    expect(page.page.total).toBe(0);
  });

  it("never sends cookies", async () => {
    const mock = stubFetch(jsonResponse(emptyPage));
    await listPapers();
    expect(mock.mock.calls[0]![1]?.credentials).toBe("omit");
  });
});

describe("getPaper", () => {
  it("encodes the id into the path", async () => {
    const mock = stubFetch(jsonResponse({ id: "abc" }));
    await getPaper("a b/c");
    expect(requestedUrl(mock).pathname).toBe("/papers/a%20b%2Fc");
  });

  it("classifies a 404 as not_found", async () => {
    stubFetch(jsonResponse({ detail: "Paper not found" }, { status: 404 }));
    await expect(getPaper("missing")).rejects.toMatchObject({
      kind: "not_found",
      status: 404,
    });
  });
});

describe("searchPapers", () => {
  const emptyResults = { query: "x", count: 0, limit: 20, results: [] };

  it("URL-encodes the query", async () => {
    const mock = stubFetch(jsonResponse(emptyResults));
    await searchPapers({ q: "graph neural networks & more" });
    const url = requestedUrl(mock);
    expect(url.searchParams.get("q")).toBe("graph neural networks & more");
    expect(url.search).toContain("q=graph+neural+networks+%26+more");
  });

  it("sends no retrieval-method parameter of any kind", async () => {
    const mock = stubFetch(jsonResponse(emptyResults));
    await searchPapers({ q: "graph", limit: 10 });
    const keys = [...requestedUrl(mock).searchParams.keys()];
    expect(keys.sort()).toEqual(["limit", "q"]);
    for (const forbidden of ["method", "model_key", "embedding_profile", "rrf_k", "depth"]) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it("sends metadata filters but still no retrieval configuration", async () => {
    // The two are different things that both arrive as query parameters:
    // `preprints` describes the papers a reader wants, `method` describes how
    // the ranker works. The first is a product feature; the second is not.
    const mock = stubFetch(jsonResponse(emptyResults));
    await searchPapers({
      q: "graph",
      limit: 10,
      source: ["arxiv"],
      preprints: "only_preprints",
      peer_reviewed: true,
      open_access: true,
    });

    const keys = [...requestedUrl(mock).searchParams.keys()];
    expect(keys.sort()).toEqual([
      "limit",
      "open_access",
      "peer_reviewed",
      "preprints",
      "q",
      "source",
    ]);
  });

  it("preserves the backend result order exactly", async () => {
    stubFetch(
      jsonResponse({
        query: "graph",
        count: 3,
        limit: 20,
        results: [
          { rank: 1, paper: { id: "c" } },
          { rank: 2, paper: { id: "a" } },
          { rank: 3, paper: { id: "b" } },
        ],
      }),
    );
    const response = await searchPapers({ q: "graph" });
    expect(response.results.map((hit) => hit.paper.id)).toEqual(["c", "a", "b"]);
  });

  it("classifies 429 and exposes Retry-After", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: "Rate limit exceeded. Please slow down." }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "37" },
      }),
    );
    await expect(searchPapers({ q: "graph" })).rejects.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 37,
    });
  });

  it("classifies 503 as a capacity failure, not a generic server error", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: "Search is temporarily at capacity." }), {
        status: 503,
        headers: { "Content-Type": "application/json", "Retry-After": "5" },
      }),
    );
    await expect(searchPapers({ q: "graph" })).rejects.toMatchObject({
      kind: "capacity",
      retryAfterSeconds: 5,
    });
  });

  it("classifies 422 as an invalid request and keeps the reason", async () => {
    stubFetch(
      jsonResponse({ detail: "q: String should have at most 512 characters" }, { status: 422 }),
    );
    await expect(searchPapers({ q: "x".repeat(600) })).rejects.toMatchObject({
      kind: "invalid_request",
    });
  });

  it("classifies a transport failure as network", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(searchPapers({ q: "graph" })).rejects.toMatchObject({ kind: "network" });
  });

  it("classifies an unreadable body as malformed", async () => {
    stubFetch(new Response("<html>not json</html>", { status: 200 }));
    await expect(searchPapers({ q: "graph" })).rejects.toMatchObject({ kind: "malformed" });
  });

  it("propagates an abort so callers can ignore it", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((_resolve, reject) => {
            controller.signal.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );
    const pending = searchPapers({ q: "graph" }, controller.signal);
    controller.abort();
    await expect(pending).rejects.toBeInstanceOf(DOMException);
    await expect(pending).rejects.not.toBeInstanceOf(ApiError);
  });

  it("forwards the abort signal to fetch", async () => {
    const mock = stubFetch(jsonResponse(emptyResults));
    const controller = new AbortController();
    await searchPapers({ q: "graph" }, controller.signal);
    expect(mock.mock.calls[0]![1]?.signal).toBe(controller.signal);
  });
});
