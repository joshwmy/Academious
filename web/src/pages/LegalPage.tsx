/**
 * Shared frame for the privacy policy and the terms.
 *
 * Both live inside the application shell so a reader reaches them from any
 * page, signed in or not, and both read as plain prose: a contents list, then
 * numbered sections that can be linked to directly.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { CONTACT_EMAIL, LEGAL_UPDATED } from "../lib/legal";
import "./Page.css";
import "./LegalPage.css";

export interface LegalSection {
  id: string;
  title: string;
  body: ReactNode;
}

interface LegalDocumentProps {
  title: string;
  lead: ReactNode;
  sections: LegalSection[];
  sibling: { to: string; label: string };
}

export function LegalDocument({ title, lead, sections, sibling }: LegalDocumentProps) {
  return (
    <article className="page legal">
      <header className="page__header">
        <h1 className="page__title">{title}</h1>
        <p className="legal__updated">Last updated {LEGAL_UPDATED}</p>
        <p className="page__lead">{lead}</p>
      </header>
      <nav className="legal__contents" aria-label="Contents">
        <ol>
          {sections.map((section) => (
            <li key={section.id}><a href={`#${section.id}`}>{section.title}</a></li>
          ))}
        </ol>
      </nav>
      {sections.map((section, index) => (
        <section key={section.id} id={section.id} className="legal__section" aria-labelledby={`${section.id}-title`}>
          <h2 id={`${section.id}-title`} className="legal__heading">
            <span className="legal__number">{index + 1}.</span> {section.title}
          </h2>
          {section.body}
        </section>
      ))}
      <footer className="legal__footer">
        <p>
          Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. See also
          the <Link to={sibling.to}>{sibling.label}</Link>.
        </p>
      </footer>
    </article>
  );
}

