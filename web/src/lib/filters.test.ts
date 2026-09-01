import { describe, expect, it } from "vitest";
import {
  NO_FILTERS,
  countActiveFilters,
  filtersToParams,
  filtersToSearchParams,
  parseFilters,
} from "./filters";

const query = (raw: string) => new URLSearchParams(raw);

describe("parseFilters", () => {
  it("returns no filters for an empty query string", () => {
    expect(parseFilters(query(""))).toEqual(NO_FILTERS);
  });

  it("reads every supported filter", () => {
    const filters = parseFilters(
      query("source=arxiv&preprints=exclude_preprints&peer_reviewed=true&open_access=true"),
    );

    expect(filters).toEqual({
      sources: ["arxiv"],
      preprints: "exclude_preprints",
      peerReviewed: true,
      openAccess: true,
    });
  });

  it("drops unknown source keys rather than forwarding them to the API", () => {
    // A hand-edited URL must not become a 422: the backend rejects unknown
    // enum values, and an unrecognised source is not a filter we can honour.
    expect(parseFilters(query("source=arxiv&source=nonsense")).sources).toEqual(["arxiv"]);
  });

  it("de-duplicates repeated sources", () => {
    expect(parseFilters(query("source=arxiv&source=arxiv")).sources).toEqual(["arxiv"]);
  });

  it("orders sources canonically, not by their order in the URL", () => {
    // Two URLs that mean the same thing must produce the same request.
    expect(parseFilters(query("source=biorxiv&source=arxiv")).sources).toEqual(
      parseFilters(query("source=arxiv&source=biorxiv")).sources,
    );
  });

  it("accepts every source the backend harvests", () => {
    // The transcription of the connector registry is the thing most likely to
    // fall behind it, and a source missing here is silently unfilterable.
    expect(parseFilters(query("source=europepmc")).sources).toEqual(["europepmc"]);
    expect(
      parseFilters(query("source=openalex&source=europepmc&source=arxiv&source=biorxiv"))
        .sources,
    ).toEqual(["arxiv", "biorxiv", "europepmc", "openalex"]);
  });

  it("falls back to 'any' for an unrecognised preprint policy", () => {
    expect(parseFilters(query("preprints=maybe")).preprints).toBe("any");
  });

  it("treats anything but 'true' as false", () => {
    expect(parseFilters(query("peer_reviewed=false")).peerReviewed).toBe(false);
    expect(parseFilters(query("open_access=1")).openAccess).toBe(false);
    expect(parseFilters(query("open_access=")).openAccess).toBe(false);
  });

  it("ignores parameters that are not filters", () => {
    expect(parseFilters(query("offset=40&q=graphs"))).toEqual(NO_FILTERS);
  });
});

describe("filtersToSearchParams", () => {
  it("writes nothing when no filter is set, so a clean feed has a clean URL", () => {
    expect(filtersToSearchParams(NO_FILTERS).toString()).toBe("");
  });

  it("writes only the values that differ from the default", () => {
    const written = filtersToSearchParams({
      ...NO_FILTERS,
      peerReviewed: true,
    }).toString();

    expect(written).toBe("peer_reviewed=true");
  });

  it("round-trips every filter", () => {
    const filters = {
      sources: ["arxiv", "biorxiv"] as const,
      preprints: "only_preprints" as const,
      peerReviewed: true,
      openAccess: true,
    };

    expect(parseFilters(filtersToSearchParams({ ...filters, sources: [...filters.sources] }))).toEqual({
      ...filters,
      sources: [...filters.sources],
    });
  });
});

describe("filtersToParams", () => {
  it("sends no filter parameters when nothing is filtered", () => {
    expect(filtersToParams(NO_FILTERS)).toEqual({});
  });

  it("uses the API's parameter names", () => {
    expect(
      filtersToParams({
        sources: ["biorxiv"],
        preprints: "only_preprints",
        peerReviewed: true,
        openAccess: true,
      }),
    ).toEqual({
      source: ["biorxiv"],
      preprints: "only_preprints",
      peer_reviewed: true,
      open_access: true,
    });
  });
});

describe("countActiveFilters", () => {
  it("counts nothing when nothing is set", () => {
    expect(countActiveFilters(NO_FILTERS)).toBe(0);
  });

  it("counts a source selection once per source", () => {
    expect(countActiveFilters({ ...NO_FILTERS, sources: ["arxiv", "biorxiv"] })).toBe(2);
  });

  it("counts a non-default preprint policy", () => {
    expect(countActiveFilters({ ...NO_FILTERS, preprints: "only_preprints" })).toBe(1);
    expect(countActiveFilters({ ...NO_FILTERS, preprints: "any" })).toBe(0);
  });

  it("counts each boolean only when it is on", () => {
    expect(countActiveFilters({ ...NO_FILTERS, peerReviewed: true, openAccess: true })).toBe(2);
  });
});
