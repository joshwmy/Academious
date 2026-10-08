import type { ProfileDraft } from "../api/types";

const PROFILE_KEY = "academious:profile:v1";
const EVENTS_KEY = "academious:interactions:v1";
const MAX_EVENTS = 500;

export interface LocalInteraction {
  type: "impression" | "more_like_this" | "less_like_this" | "not_interested";
  paper_id: string;
  occurred_at: string;
  position?: number;
}

export function loadProfileDraft(): ProfileDraft | null {
  try {
    const raw = window.localStorage.getItem(PROFILE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    return isProfileDraft(value) ? value : null;
  } catch {
    return null;
  }
}

export function saveProfileDraft(draft: ProfileDraft): void {
  try {
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify(draft));
  } catch {
    // A private or storage-constrained browser can still use the current tab.
  }
}

export function clearProfileDraft(): void {
  try {
    window.localStorage.removeItem(PROFILE_KEY);
  } catch {
    // Storage is an enhancement, never a requirement for profile creation.
  }
}

export function recordInteractions(events: LocalInteraction[]): void {
  if (events.length === 0) return;
  try {
    const existingRaw = window.localStorage.getItem(EVENTS_KEY);
    const existing: unknown = existingRaw ? JSON.parse(existingRaw) : [];
    const history = Array.isArray(existing) ? existing : [];
    window.localStorage.setItem(
      EVENTS_KEY,
      JSON.stringify([...history, ...events].slice(-MAX_EVENTS)),
    );
  } catch {
    // Recommendation remains usable when interaction history cannot be kept.
  }
}

function isProfileDraft(value: unknown): value is ProfileDraft {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProfileDraft>;
  return (
    Array.isArray(candidate.fields) &&
    Array.isArray(candidate.interests) &&
    Array.isArray(candidate.example_papers) &&
    Array.isArray(candidate.negatives) &&
    Array.isArray(candidate.negative_papers) &&
    Array.isArray(candidate.blocked_topics) &&
    Boolean(candidate.discovery) &&
    typeof candidate.discovery?.freshness === "string" &&
    typeof candidate.discovery?.exploration === "string" &&
    typeof candidate.discovery?.publication === "string"
  );
}
