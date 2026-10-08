/**
 * Building a research profile, and seeing what it produces.
 *
 * Deliberately one page rather than seven screens. The flow the backend
 * supports is create, preview, correct, accept, and a wizard would add four
 * navigation steps to a form a researcher can fill in at one sitting. Sections
 * are ordered the way the reader thinks - broad, then specific, then what they
 * do not want, then how to explore - and everything below the button is the
 * consequence of what is above it.
 *
 * The draft stays editable in this component. Anonymous readers keep it on
 * this device; verified accounts also sync the normalised draft. Every preview
 * still carries the full draft and replaces its copy with what came back. That is what
 * makes a merged duplicate or a dropped example paper visible, rather than a
 * silent divergence between what the reader sees and what the recommender got.
 *
 * Nothing here computes a weight, a score or a threshold. The levels are words,
 * their meaning belongs to `onboarding/levels.py`, and `GET /profiles/options`
 * supplies the vocabulary so this file cannot drift from it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  MAX_QUERY_LENGTH,
  getProfileOptions,
  getAccountProfile,
  listFields,
  previewProfile,
  refineProfile,
  searchPapers,
  saveAccountProfile,
} from "../api/client";
import { ApiError } from "../api/errors";
import type {
  FieldSummary,
  Importance,
  PaperSummary,
  ProfileDraft,
  ProfileOptions,
  ProfileResponse,
  Refinement,
} from "../api/types";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useAuth } from "../auth/AuthContext";
import {
  clearProfileDraft,
  loadProfileDraft,
  saveProfileDraft,
} from "../lib/profileStorage";
import "./Page.css";
import "./ProfilePage.css";

const PREVIEW_SIZE = 12;

const EMPTY_DRAFT: ProfileDraft = {
  fields: [],
  interests: [],
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

export function ProfilePage() {
  useDocumentTitle("Your research profile");
  const { user } = useAuth();

  const [draft, setDraft] = useState<ProfileDraft>(() => loadProfileDraft() ?? EMPTY_DRAFT);
  const [hasSavedProfile, setHasSavedProfile] = useState(() => loadProfileDraft() !== null);
  const [options, setOptions] = useState<ProfileOptions | null>(null);
  const [fields, setFields] = useState<FieldSummary[]>([]);
  const [result, setResult] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [interestText, setInterestText] = useState("");
  const [interestLevel, setInterestLevel] = useState<Importance>("interested");
  const [dislikeText, setDislikeText] = useState("");

  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([getProfileOptions(controller.signal), listFields(controller.signal)])
      .then(([serverOptions, fieldList]) => {
        setOptions(serverOptions);
        setFields(fieldList.fields);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(describe(cause));
      });
    return () => {
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (!user?.is_verified) return;
    void getAccountProfile()
      .then((stored) => {
        setDraft(stored);
        saveProfileDraft(stored);
        setHasSavedProfile(true);
      })
      .catch((cause: unknown) => {
        if (cause instanceof ApiError && cause.status === 404) {
          const local = loadProfileDraft();
          if (local) void saveAccountProfile(local).catch(() => setError("We could not sync this profile yet."));
          return;
        }
        setError(describe(cause));
      });
  }, [user]);

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const run = useCallback(async (work: (signal: AbortSignal) => Promise<ProfileResponse>) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError(null);
    try {
      const response = await work(controller.signal);
      // Replace the local draft with the normalised one. Anything the server
      // merged, trimmed or refused is visible from here on.
      setDraft(response.draft);
      saveProfileDraft(response.draft);
      if (user?.is_verified) await saveAccountProfile(response.draft);
      setHasSavedProfile(true);
      setResult(response);
    } catch (cause: unknown) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(describe(cause));
    } finally {
      // An older request may finish after a refinement has replaced it. It
      // must not re-enable the controls while the newer request is in flight.
      if (abort.current === controller) {
        abort.current = null;
        setBusy(false);
      }
    }
  }, [user]);

  const preview = useCallback(() => {
    void run((signal) => previewProfile(draft, PREVIEW_SIZE, signal));
  }, [draft, run]);

  const refine = useCallback(
    (refinement: Refinement) => {
      void run((signal) => refineProfile(draft, [refinement], PREVIEW_SIZE, signal));
    },
    [draft, run],
  );

  const toggleField = (slug: string) => {
    setDraft((current) => ({
      ...current,
      fields: current.fields.includes(slug)
        ? current.fields.filter((value) => value !== slug)
        : [...current.fields, slug],
    }));
  };

  const addInterest = () => {
    const text = interestText.trim();
    if (!text) return;
    setDraft((current) => ({
      ...current,
      interests: [...current.interests, { text, importance: interestLevel }],
    }));
    setInterestText("");
  };

  const addDislike = () => {
    const text = dislikeText.trim();
    if (!text) return;
    setDraft((current) => ({
      ...current,
      negatives: [...current.negatives, { text, strength: "avoid" }],
    }));
    setDislikeText("");
  };

  const ready = draft.fields.length + draft.interests.length + draft.example_papers.length > 0;

  return (
    <div className="page profile">
      <header className="page__header">
        <h1 className="page__title">Your research profile</h1>
        <p className="page__lead">
          Tell Academious what you work on, then see what it would show you. Your profile is
          {user?.is_verified ? "synced to your account" : "saved on this device"} and can be changed whenever your interests move.
        </p>
      </header>

      {error ? (
        <p className="profile__error" role="alert">
          {error}
        </p>
      ) : null}

      <section className="profile__section" aria-labelledby="areas">
        <h2 className="profile__heading" id="areas">
          What research are you interested in?
        </h2>
        <p className="profile__hint">Pick a few broad areas. This is orientation, not a filter.</p>
        <ul className="profile__chips">
          {fields.map((field) => (
            <li key={field.slug}>
              <button
                type="button"
                className="profile__chip"
                aria-pressed={draft.fields.includes(field.slug)}
                onClick={() => {
                  toggleField(field.slug);
                }}
              >
                {field.label}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="profile__section" aria-labelledby="interests">
        <h2 className="profile__heading" id="interests">
          What do you actually want to follow?
        </h2>
        <p className="profile__hint">
          In your own words, and specific: &ldquo;retrieval augmented generation&rdquo; finds far
          more than &ldquo;AI&rdquo;.
        </p>
        <div className="profile__row">
          <input
            className="profile__input"
            value={interestText}
            maxLength={options?.limits["interest_characters"] ?? 200}
            placeholder="recommendation systems and ranking"
            aria-label="A research interest"
            onChange={(event) => {
              setInterestText(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addInterest();
              }
            }}
          />
          <select
            className="profile__select"
            value={interestLevel}
            aria-label="How much it matters"
            onChange={(event) => {
              setInterestLevel(event.target.value as Importance);
            }}
          >
            {(options?.importance ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" className="profile__button" onClick={addInterest}>
            Add
          </button>
        </div>
        <ul className="profile__list">
          {draft.interests.map((interest, index) => (
            <li key={`${interest.text}-${String(index)}`} className="profile__item">
              <span>{interest.text}</span>
              <span className="profile__level">{interest.importance}</span>
              <button
                type="button"
                className="profile__remove"
                aria-label={`Remove ${interest.text}`}
                onClick={() => {
                  setDraft((current) => ({
                    ...current,
                    interests: current.interests.filter((_, at) => at !== index),
                  }));
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>

      <ExamplePaperPicker
        papers={draft.example_papers}
        limit={options?.limits["example_papers"] ?? 8}
        onAdd={(paper, importance) => {
          setDraft((current) => ({
            ...current,
            example_papers: [
              ...current.example_papers,
              { paper_id: paper.id, importance, label: paper.title },
            ],
          }));
        }}
        onRemove={(paperId) => {
          setDraft((current) => ({
            ...current,
            example_papers: current.example_papers.filter(
              (paper) => paper.paper_id !== paperId,
            ),
          }));
        }}
      />

      <section className="profile__section" aria-labelledby="dislikes">
        <h2 className="profile__heading" id="dislikes">
          Anything you do not want?
        </h2>
        <p className="profile__hint">
          Optional. Skipping a topic is not the same as disliking it - only what you type here
          counts against a paper.
        </p>
        <div className="profile__row">
          <input
            className="profile__input"
            value={dislikeText}
            maxLength={options?.limits["interest_characters"] ?? 200}
            placeholder="generative image synthesis"
            aria-label="Something to avoid"
            onChange={(event) => {
              setDislikeText(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addDislike();
              }
            }}
          />
          <button type="button" className="profile__button" onClick={addDislike}>
            Add
          </button>
        </div>
        <ul className="profile__list">
          {draft.negatives.map((negative, index) => (
            <li key={`${negative.text}-${String(index)}`} className="profile__item">
              <span>{negative.text}</span>
              <button
                type="button"
                className="profile__remove"
                aria-label={`Remove ${negative.text}`}
                onClick={() => {
                  setDraft((current) => ({
                    ...current,
                    negatives: current.negatives.filter((_, at) => at !== index),
                  }));
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="profile__section" aria-labelledby="discovery">
        <h2 className="profile__heading" id="discovery">
          How should Academious explore?
        </h2>
        <div className="profile__row profile__row--wrap">
          <Choice
            label="New research"
            value={draft.discovery.freshness}
            options={options?.freshness ?? []}
            onChange={(value) => {
              setDraft((current) => ({
                ...current,
                discovery: { ...current.discovery, freshness: value as never },
              }));
            }}
          />
          <Choice
            label="Exploration"
            value={draft.discovery.exploration}
            options={options?.exploration ?? []}
            onChange={(value) => {
              setDraft((current) => ({
                ...current,
                discovery: { ...current.discovery, exploration: value as never },
              }));
            }}
          />
          <Choice
            label="Publication stage"
            value={draft.discovery.publication}
            options={options?.publication ?? []}
            onChange={(value) => {
              setDraft((current) => ({
                ...current,
                discovery: { ...current.discovery, publication: value as never },
              }));
            }}
          />
        </div>
      </section>

      <div className="profile__actions">
        <button
          type="button"
          className="profile__button profile__button--primary"
          disabled={!ready || busy}
          onClick={preview}
        >
          {busy ? "Working…" : result ? "Update my feed" : "Show me my feed"}
        </button>
        {!ready ? (
          <span className="profile__hint">Pick a broad area or add an interest first.</span>
        ) : null}
        {hasSavedProfile ? (
          <button
            type="button"
            className="profile__remove"
            disabled={busy}
            onClick={() => {
              clearProfileDraft();
              setDraft(EMPTY_DRAFT);
              setResult(null);
              setError(null);
              setHasSavedProfile(false);
            }}
          >
            Forget this profile
          </button>
        ) : null}
      </div>

      {result ? <Result result={result} onRefine={refine} busy={busy} /> : null}
    </div>
  );
}

function ExamplePaperPicker({
  papers,
  limit,
  onAdd,
  onRemove,
}: {
  papers: ProfileDraft["example_papers"];
  limit: number;
  onAdd: (paper: PaperSummary, importance: Importance) => void;
  onRemove: (paperId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [importance, setImportance] = useState<Importance>("interested");
  const [matches, setMatches] = useState<PaperSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchAbort = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      searchAbort.current?.abort();
    },
    [],
  );

  const findPapers = async () => {
    const trimmed = query.trim();
    if (!trimmed || trimmed.length > MAX_QUERY_LENGTH) return;

    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setSearching(true);
    setSearchError(null);
    try {
      const response = await searchPapers({ q: trimmed, limit: 5 }, controller.signal);
      setMatches(response.results.map((hit) => hit.paper));
      setSearched(true);
    } catch (cause: unknown) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setSearchError(describe(cause));
    } finally {
      if (searchAbort.current === controller) {
        searchAbort.current = null;
        setSearching(false);
      }
    }
  };

  const selectedIds = new Set(papers.map((paper) => paper.paper_id));
  const atLimit = papers.length >= limit;

  return (
    <section className="profile__section" aria-labelledby="example-papers">
      <h2 className="profile__heading" id="example-papers">
        Any papers that feel like your work?
      </h2>
      <p className="profile__hint">
        Optional. Search this corpus and choose concrete examples; their full abstracts help
        anchor what your wording means.
      </p>

      <form
        className="profile__paper-search"
        role="search"
        aria-label="Find example papers"
        onSubmit={(event) => {
          event.preventDefault();
          void findPapers();
        }}
      >
        <label className="sr-only" htmlFor="profile-paper-query">
          Search for an example paper
        </label>
        <input
          id="profile-paper-query"
          className="profile__input"
          type="search"
          value={query}
          maxLength={MAX_QUERY_LENGTH}
          placeholder="paper title, method, or topic"
          autoComplete="off"
          onChange={(event) => {
            searchAbort.current?.abort();
            searchAbort.current = null;
            setSearching(false);
            setQuery(event.target.value);
            setMatches([]);
            setSearched(false);
            setSearchError(null);
          }}
        />
        <button
          type="submit"
          className="profile__button"
          disabled={searching || query.trim() === ""}
        >
          {searching ? "Searching…" : "Find papers"}
        </button>
      </form>

      {searchError ? (
        <p className="profile__error" role="alert">
          {searchError}
        </p>
      ) : null}

      {searched && matches.length === 0 ? (
        <p className="profile__empty">No papers in this corpus matched that search.</p>
      ) : null}

      {matches.length > 0 ? (
        <div className="profile__matches">
          <label className="profile__choice profile__match-level">
            <span className="profile__choice-label">How much these represent you</span>
            <select
              className="profile__select"
              value={importance}
              onChange={(event) => {
                setImportance(event.target.value as Importance);
              }}
            >
              <option value="core">Core</option>
              <option value="interested">Interested</option>
              <option value="occasional">Occasional</option>
            </select>
          </label>
          <ol className="profile__match-list" aria-label="Paper search results">
            {matches.map((paper) => {
              const selected = selectedIds.has(paper.id);
              return (
                <li key={paper.id} className="profile__match">
                  <div>
                    <p className="profile__match-title">{paper.title}</p>
                    <p className="profile__paper-meta">
                      {paper.authors.map((author) => author.name).join(", ")}
                      {paper.published_year ? ` · ${String(paper.published_year)}` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="profile__button"
                    disabled={selected || atLimit}
                    onClick={() => {
                      onAdd(paper, importance);
                    }}
                  >
                    {selected ? "Added" : "Use this paper"}
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      {atLimit ? (
        <p className="profile__hint" role="status">
          You have chosen the maximum of {limit} example papers.
        </p>
      ) : null}

      <ul className="profile__list" aria-label="Chosen example papers">
        {papers.map((paper) => (
          <li key={paper.paper_id} className="profile__item">
            <span>{paper.label ?? paper.paper_id}</span>
            <span className="profile__level">{paper.importance}</span>
            <button
              type="button"
              className="profile__remove"
              aria-label={`Remove ${paper.label ?? "example paper"}`}
              onClick={() => {
                onRemove(paper.paper_id);
              }}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="profile__choice">
      <span className="profile__choice-label">{label}</span>
      <select
        className="profile__select"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Result({
  result,
  onRefine,
  busy,
}: {
  result: ProfileResponse;
  onRefine: (refinement: Refinement) => void;
  busy: boolean;
}) {
  return (
    <>
      {result.changes.length > 0 ? (
        <p className="profile__changes" role="status">
          {result.changes.join(" ")}
        </p>
      ) : null}

      {result.issues.length > 0 ? (
        <ul className="profile__issues">
          {result.issues.map((issue, index) => (
            <li key={`${issue.code}-${String(index)}`}>{issue.message}</li>
          ))}
        </ul>
      ) : null}

      <section className="profile__section" aria-labelledby="summary">
        <h2 className="profile__heading" id="summary">
          What Academious thinks you care about
        </h2>
        {result.summary.sections.map((section) => (
          <div key={section.heading} className="profile__summary">
            <h3 className="profile__summary-heading">{section.heading}</h3>
            <ul className="profile__summary-list">
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
        <dl className="profile__preferences">
          {result.summary.preferences.map((preference) => (
            <div key={preference.label}>
              <dt>{preference.label}</dt>
              <dd>{preference.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="profile__section" aria-labelledby="preview">
        <h2 className="profile__heading" id="preview">
          Here is what your feed would look like
        </h2>
        {result.preview.length === 0 ? (
          <p className="profile__empty">
            No papers matched this profile yet. Try a broader interest or include preprints.
          </p>
        ) : (
          <ol className="profile__preview">
            {result.preview.map((item) => (
            <li key={item.paper.id} className="profile__paper">
              <h3 className="profile__paper-title">
                <Link to={`/papers/${item.paper.id}`}>{item.paper.title}</Link>
              </h3>
              <p className="profile__paper-meta">
                {item.paper.authors.map((author) => author.name).join(", ")}
                {item.paper.venue ? ` · ${item.paper.venue}` : ""}
                {item.paper.published_date ? ` · ${item.paper.published_date}` : ""}
              </p>
              {item.paper.abstract_preview ? (
                <p className="profile__paper-abstract">{item.paper.abstract_preview}</p>
              ) : null}
              <p className="profile__reasons">{item.reasons.join(" · ")}</p>
              <div className="profile__paper-actions">
                <button
                  type="button"
                  className="profile__button"
                  disabled={busy}
                  onClick={() => {
                    onRefine({
                      action: "more_like_this",
                      paper_id: item.paper.id,
                      interest_key: item.matched_interest_key ?? undefined,
                      label: item.paper.title,
                    });
                  }}
                >
                  More like this
                </button>
                <button
                  type="button"
                  className="profile__button"
                  disabled={busy}
                  onClick={() => {
                    onRefine({
                      action: "less_like_this",
                      paper_id: item.paper.id,
                      interest_key: item.matched_interest_key ?? undefined,
                      label: item.paper.title,
                    });
                  }}
                >
                  Less like this
                </button>
                <button
                  type="button"
                  className="profile__button"
                  disabled={busy}
                  onClick={() => {
                    onRefine({
                      action: "not_interested",
                      paper_id: item.paper.id,
                      interest_key: item.matched_interest_key ?? undefined,
                      label: item.paper.title,
                    });
                  }}
                >
                  Not interested
                </button>
              </div>
            </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}

function describe(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message;
  return "Something went wrong building your profile.";
}
