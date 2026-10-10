/**
 * First run: three short steps from a new account to a personal feed.
 *
 *   1. Fields   - broad areas, as chips. Required: at least one.
 *   2. Topics   - a few specific interests, typed. Optional.
 *   3. Explore  - how the feed improves, then the feed itself.
 *
 * This is the short road into the same profile /profile edits in full. It
 * writes an ordinary ProfileDraft through previewProfile, so the server
 * normalises it exactly as it would a hand-built one, and it is kept on this
 * device like any other draft; FeedPage syncs it to the account once the
 * email is verified. Dislikes, example papers and discovery settings are left
 * at their defaults - they are tuning, and tuning belongs after a first look
 * at the feed, not before it.
 */

import { useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { previewProfile, saveAccountProfile } from "../api/client";
import type { ProfileDraft } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PAGE_SIZE, type FeedHandoff } from "./FeedPage";
import { Logo } from "../components/Logo";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { FIELDS } from "../lib/filters";
import { stagger } from "../lib/motion";
import { loadProfileDraft, saveProfileDraft } from "../lib/profileStorage";
import "../styles/motion.css";
import "./AuthPage.css";
import "./WelcomePage.css";

/** Mirrors `limits` from GET /profiles/options. */
const MAX_FIELDS = 8;
const MAX_TOPICS = 12;
const MAX_TOPIC_LENGTH = 200;

const EXPLORE_TIPS = [
  { title: "Open what catches your eye", body: "Every paper you read tells your feed a little more about what you care about." },
  { title: "Save the ones worth keeping", body: "Saved papers build your collection and pull similar work closer." },
  { title: "Say more, or less, like this", body: "Each paper has quick feedback buttons. A few taps reshape tomorrow's feed." },
];

function draftFrom(fields: string[], topics: string[]): ProfileDraft {
  const existing = loadProfileDraft();
  return {
    fields,
    interests: topics.map((text) => ({ text, importance: "interested" as const })),
    example_papers: existing?.example_papers ?? [],
    negatives: existing?.negatives ?? [],
    negative_papers: existing?.negative_papers ?? [],
    blocked_topics: existing?.blocked_topics ?? [],
    discovery: existing?.discovery ?? {
      freshness: "balanced",
      exploration: "balanced",
      publication: "include_preprints",
    },
  };
}

export function WelcomePage() {
  useDocumentTitle("Welcome");
  const navigate = useNavigate();
  const { user } = useAuth();
  const [step, setStep] = useState(0);
  const [fields, setFields] = useState<string[]>(() => loadProfileDraft()?.fields ?? []);
  const [topics, setTopics] = useState<string[]>(
    () => loadProfileDraft()?.interests.map((interest) => interest.text) ?? [],
  );
  const [topicText, setTopicText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const firstName = user?.display_name.split(" ")[0];

  const toggleField = (slug: string) => {
    if (fields.includes(slug)) {
      setError(null);
      setFields(fields.filter((value) => value !== slug));
      return;
    }
    if (fields.length >= MAX_FIELDS) {
      setError(`Pick up to ${MAX_FIELDS} fields - you can refine them later.`);
      return;
    }
    setError(null);
    setFields([...fields, slug]);
  };

  const addTopic = () => {
    const text = topicText.trim().slice(0, MAX_TOPIC_LENGTH);
    if (!text) return;
    if (topics.some((topic) => topic.toLowerCase() === text.toLowerCase())) {
      setTopicText("");
      return;
    }
    if (topics.length >= MAX_TOPICS) {
      setError(`That's ${MAX_TOPICS} topics - plenty to start with.`);
      return;
    }
    setError(null);
    setTopics((current) => [...current, text]);
    setTopicText("");
  };

  const onTopicKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addTopic();
    } else if (event.key === "Backspace" && topicText === "" && topics.length > 0) {
      setTopics((current) => current.slice(0, -1));
    }
  };

  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      const pending = topicText.trim();
      const allTopics = pending && !topics.includes(pending) ? [...topics, pending] : topics;
      const response = await previewProfile(draftFrom(fields, allTopics), PAGE_SIZE);
      saveProfileDraft(response.draft);
      if (user?.is_verified) await saveAccountProfile(response.draft);
      navigate("/feed", { replace: true, state: { preview: response } satisfies FeedHandoff });
    } catch {
      setError("We couldn't build your feed just now. Try again in a moment.");
      setBusy(false);
    }
  };

  return (
    <div className="auth welcome">
      <div className="auth__glow" aria-hidden="true" />
      <Link to="/" className="auth__brand" aria-label="Academious, home"><Logo /></Link>

      <ol className="welcome__progress" aria-label="Setup progress">
        {["Fields", "Topics", "Explore"].map((label, index) => (
          <li
            key={label}
            className={index === step ? "welcome__dot welcome__dot--current" : index < step ? "welcome__dot welcome__dot--done" : "welcome__dot"}
            aria-current={index === step ? "step" : undefined}
          >
            <span className="sr-only">{label}{index < step ? " (done)" : ""}</span>
          </li>
        ))}
      </ol>

      <main className="welcome__card" key={step}>
        {step === 0 ? (
          <section className="rise" aria-labelledby="welcome-fields">
            <h1 className="welcome__title" id="welcome-fields">
              {firstName ? `Welcome, ${firstName}. ` : ""}What do you work on?
            </h1>
            <p className="welcome__lead">Pick the fields you'd like to hear about. Choose as many as fit, up to {MAX_FIELDS}.</p>
            <div className="welcome__chips" role="group" aria-label="Fields">
              {FIELDS.map((field, index) => {
                const selected = fields.includes(field.slug);
                return (
                  <button
                    key={field.slug}
                    type="button"
                    className={selected ? "chip chip--selected rise" : "chip rise"}
                    style={stagger(Math.min(index, 12) * 0.35)}
                    aria-pressed={selected}
                    onClick={() => toggleField(field.slug)}
                  >
                    {selected ? <svg className="chip__tick" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7" /></svg> : null}
                    {field.label}
                  </button>
                );
              })}
            </div>
            {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
            <div className="welcome__actions">
              <span className="welcome__count" aria-live="polite">{fields.length} selected</span>
              <button className="button" type="button" disabled={fields.length === 0} onClick={() => { setError(null); setStep(1); }}>
                Continue
              </button>
            </div>
          </section>
        ) : null}

        {step === 1 ? (
          <section className="rise" aria-labelledby="welcome-topics">
            <h1 className="welcome__title" id="welcome-topics">Anything more specific?</h1>
            <p className="welcome__lead">
              Add a few topics, methods or questions you follow. Press Enter after each one.
            </p>
            <div className="topic-input">
              {topics.map((topic) => (
                <span className="topic pop" key={topic}>
                  {topic}
                  <button type="button" className="topic__remove" aria-label={`Remove ${topic}`} onClick={() => setTopics((current) => current.filter((value) => value !== topic))}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
                  </button>
                </span>
              ))}
              <input
                className="topic-input__field"
                value={topicText}
                maxLength={MAX_TOPIC_LENGTH}
                placeholder={topics.length ? "Add another…" : "e.g. protein folding, causal inference"}
                aria-label="Add a topic"
                onChange={(event) => setTopicText(event.target.value)}
                onKeyDown={onTopicKey}
                onBlur={addTopic}
                autoFocus
              />
            </div>
            {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
            <div className="welcome__actions">
              <button className="button button--plain" type="button" onClick={() => setStep(0)}>Back</button>
              <button className="button" type="button" onClick={() => { addTopic(); setError(null); setStep(2); }}>
                {topics.length || topicText.trim() ? "Continue" : "Skip for now"}
              </button>
            </div>
          </section>
        ) : null}

        {step === 2 ? (
          <section className="rise" aria-labelledby="welcome-explore">
            <h1 className="welcome__title" id="welcome-explore">The more you explore, the better it gets</h1>
            <p className="welcome__lead">
              Your feed starts from what you just told us, then keeps learning from what you do.
            </p>
            <ul className="explore">
              {EXPLORE_TIPS.map((tip, index) => (
                <li className="explore__item rise" key={tip.title} style={stagger(index + 1)}>
                  <span className="explore__icon" aria-hidden="true">{index + 1}</span>
                  <span>
                    <strong className="explore__title">{tip.title}</strong>
                    <span className="explore__body">{tip.body}</span>
                  </span>
                </li>
              ))}
            </ul>
            {user && !user.is_verified ? (
              <p className="welcome__note">
                We sent a verification link to <strong>{user.email}</strong>. Verify it to keep your
                feed in sync across devices.
              </p>
            ) : null}
            {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
            <div className="welcome__actions">
              <button className="button button--plain" type="button" onClick={() => setStep(1)}>Back</button>
              <button className="button button--large" type="button" disabled={busy} onClick={() => void finish()}>
                {busy ? "Building your feed…" : "Show my feed"}
              </button>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
