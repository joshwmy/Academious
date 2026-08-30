import type { PaperDetail, PaperSummary } from "../api/types";

export function makeSummary(overrides: Partial<PaperSummary> = {}): PaperSummary {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Neural message passing on interaction graphs",
    abstract_preview: "We introduce a message-passing scheme over structural graphs.",
    authors: [{ name: "Lovelace, A.", position: 0, orcid: null, affiliations: [] }],
    published_date: "2026-08-21",
    published_year: 2026,
    venue: null,
    doi: "10.1101/2026.08.21.000000",
    is_preprint: true,
    is_peer_reviewed: false,
    open_access_status: "green",
    retraction_status: "none",
    topics: [{ id: "ml", label: "Machine learning", scheme: "arxiv" }],
    citation_count: null,
    ...overrides,
  };
}

export function makeDetail(overrides: Partial<PaperDetail> = {}): PaperDetail {
  return {
    ...makeSummary(),
    abstract: "A full abstract, longer than the preview and rendered whole on the detail page.",
    language: "en",
    work_type: "preprint",
    identifiers: { doi: "10.1101/2026.08.21.000000", arxiv: "2608.00001" },
    open_access: {
      status: "green",
      is_open: true,
      url: "https://example.org/paper",
      pdf_url: "https://example.org/paper.pdf",
      licence: "cc-by",
    },
    retraction_notice_url: null,
    ...overrides,
  };
}

/** A page response wrapping the given summaries. */
export function makePage(results: PaperSummary[], overrides: Partial<{ offset: number; total: number; limit: number }> = {}) {
  const limit = overrides.limit ?? 20;
  const offset = overrides.offset ?? 0;
  const total = overrides.total ?? results.length;
  return {
    page: { limit, offset, total, returned: results.length, has_more: offset + results.length < total },
    results,
  };
}

export function jsonOk(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

export function jsonError(status: number, detail: string, retryAfter?: string): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (retryAfter) headers["Retry-After"] = retryAfter;
  return new Response(JSON.stringify({ detail }), { status, headers });
}
