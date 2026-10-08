import { describe, expect, it } from "vitest";
import type { ProfileDraft } from "../api/types";
import {
  clearProfileDraft,
  loadProfileDraft,
  recordInteractions,
  saveProfileDraft,
} from "./profileStorage";

const draft: ProfileDraft = {
  fields: ["computer-science"],
  interests: [{ text: "recommendation systems", importance: "core", horizon: "long" }],
  example_papers: [],
  negatives: [],
  negative_papers: [],
  blocked_topics: [],
  discovery: {
    freshness: "balanced",
    exploration: "balanced",
    publication: "include_preprints",
  },
};

describe("profile storage", () => {
  it("round-trips a research profile and can forget it", () => {
    saveProfileDraft(draft);
    expect(loadProfileDraft()).toEqual(draft);
    clearProfileDraft();
    expect(loadProfileDraft()).toBeNull();
  });

  it("rejects malformed stored data instead of breaking the home page", () => {
    window.localStorage.setItem("academious:profile:v1", JSON.stringify({ interests: [] }));
    expect(loadProfileDraft()).toBeNull();
  });

  it("records local impressions and explicit feedback", () => {
    recordInteractions([
      { type: "impression", paper_id: "paper-1", position: 1, occurred_at: "2026-10-08T08:00:00Z" },
      { type: "more_like_this", paper_id: "paper-1", occurred_at: "2026-10-08T08:01:00Z" },
    ]);
    expect(JSON.parse(window.localStorage.getItem("academious:interactions:v1") ?? "[]")).toHaveLength(2);
  });
});
