/**
 * The front door, for anyone without an account or a saved profile.
 *
 * One job: say what Academious does in the time it takes to read a headline,
 * then ask for a sign-up. Everything below the hero answers the two questions a
 * researcher asks before handing over an email address - where do the papers
 * come from, and why would this be better than a search box - and each section
 * ends at the same call to action rather than inventing a new one.
 *
 * The feed preview in the hero is an illustration, hidden from assistive
 * technology: its titles are representative, not records from the corpus.
 */

import { Link } from "react-router-dom";
import { LogoMark, Logo } from "../components/Logo";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useReveal } from "../hooks/useReveal";
import { stagger } from "../lib/motion";
import "../styles/motion.css";
import "./LandingPage.css";

const SOURCES = ["arXiv", "bioRxiv", "medRxiv", "Europe PMC", "OpenAlex"];

const STEPS = [
  {
    title: "Tell us what you study",
    body: "Pick your fields and a few topics. It takes about a minute, and you can change it whenever your work moves on.",
  },
  {
    title: "We read the new literature",
    body: "Every day, fresh preprints and papers from five open sources are matched against your interests and ranked for you.",
  },
  {
    title: "Your feed learns as you explore",
    body: "Open what catches your eye, save what matters, and tell it when something misses. The more you explore, the sharper your feed becomes.",
  },
];

const PROMISES = [
  {
    title: "Retraction-aware",
    body: "Retracted work is flagged, using the Retraction Watch database.",
  },
  {
    title: "Open access, marked",
    body: "See at a glance which papers you can read in full right now.",
  },
  {
    title: "Your data, your call",
    body: "Personalisation is opt-in, and deleting your account deletes everything.",
  },
];

const PREVIEW = [
  { title: "Single-cell atlas of the developing human cortex", tags: ["neuroscience", "Open access"], source: "bioRxiv" },
  { title: "Scaling laws for protein language models", tags: ["machine learning"], source: "arXiv" },
  { title: "Long-term outcomes of early sepsis bundles", tags: ["medicine", "Peer-reviewed"], source: "Europe PMC" },
];

export function LandingPage() {
  useDocumentTitle(null);
  const revealRef = useReveal<HTMLDivElement>();

  return (
    <div className="landing" ref={revealRef}>
      <a className="skip-link" href="#landing-main">Skip to content</a>
      <header className="landing-nav">
        <Link to="/" className="landing-nav__brand" aria-label="Academious, home"><Logo /></Link>
        <nav className="landing-nav__links" aria-label="Site">
          <a href="#how" className="landing-nav__link">How it works</a>
          <Link to="/feed" className="landing-nav__link">Browse papers</Link>
          <Link to="/signin" className="landing-nav__link landing-nav__link--keep">Sign in</Link>
          <Link to="/signup" className="button landing-nav__cta">Get started</Link>
        </nav>
      </header>

      <main id="landing-main">
        <section className="hero">
          <div className="hero__glow" aria-hidden="true" />
          <div className="hero__copy">
            <p className="hero__eyebrow rise" style={stagger(0)}>
              <span className="hero__dot" aria-hidden="true" />
              New research, every morning
            </p>
            <h1 className="hero__title rise" style={stagger(1)}>
              Keep up with your field, <span className="hero__accent">without the search box.</span>
            </h1>
            <p className="hero__lead rise" style={stagger(2)}>
              Academious reads the new papers so you don't have to. Tell it what you work on, and
              each day it brings you the handful worth your attention.
            </p>
            <div className="hero__actions rise" style={stagger(3)}>
              <Link to="/signup" className="button button--large">Create your account</Link>
              <Link to="/feed" className="button button--quiet button--large">Browse papers first</Link>
            </div>
          </div>

          <div className="hero__visual" aria-hidden="true">
            <div className="preview">
              <div className="preview__head">
                <span className="preview__title">Recommended for you</span>
                <span className="preview__pill">Today</span>
              </div>
              {PREVIEW.map((paper, index) => (
                <div className="preview__card rise" key={paper.title} style={stagger(index + 3)}>
                  <div className="preview__card-top">
                    <span className="preview__card-title">{paper.title}</span>
                    <svg className="preview__bookmark" viewBox="0 0 24 24"><path d="M7 4h10v16l-5-3.5L7 20z" /></svg>
                  </div>
                  <span className="preview__meta">{paper.source} · today</span>
                  <span className="preview__tags">
                    {paper.tags.map((tag) => <span className="preview__tag" key={tag}>{tag}</span>)}
                  </span>
                </div>
              ))}
            </div>
            <div className="hero__badge hero__badge--one">
              <LogoMark size={20} />
              <span>12 new matches</span>
            </div>
            <div className="hero__badge hero__badge--two">
              <span className="hero__badge-dot" />
              <span>Learning from what you open</span>
            </div>
          </div>
        </section>

        <section className="sources reveal" aria-label="Where the papers come from">
          <p className="sources__label">Drawing on</p>
          <ul className="sources__list">
            {SOURCES.map((source) => <li key={source}>{source}</li>)}
          </ul>
        </section>

        <section className="how" id="how" aria-labelledby="how-title">
          <p className="section-eyebrow reveal">How it works</p>
          <h2 className="section-title reveal" id="how-title">A personal research feed in three steps</h2>
          <ol className="how__steps">
            {STEPS.map((step, index) => (
              <li className="how__step reveal" key={step.title} style={stagger(index)}>
                <span className="how__number">{index + 1}</span>
                <h3 className="how__title">{step.title}</h3>
                <p className="how__body">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="promises" aria-label="What you can count on">
          {PROMISES.map((promise, index) => (
            <div className="promise reveal" key={promise.title} style={stagger(index)}>
              <h3 className="promise__title">{promise.title}</h3>
              <p className="promise__body">{promise.body}</p>
            </div>
          ))}
        </section>

        <section className="closing reveal" aria-labelledby="closing-title">
          <h2 className="closing__title" id="closing-title">Your field, read for you.</h2>
          <p className="closing__lead">Set up your feed in about a minute.</p>
          <Link to="/signup" className="button button--large button--inverse">Get started</Link>
        </section>
      </main>

      <footer className="landing-footer">
        <Logo size={20} />
        <p>
          Academious searches its own curated corpus of recent research from arXiv, bioRxiv/medRxiv,
          Europe PMC and OpenAlex. It is not a search over all published science.
        </p>
      </footer>
    </div>
  );
}
