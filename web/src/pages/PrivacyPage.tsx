/**
 * Privacy policy.
 *
 * Every claim here is about behaviour the code and deployment actually have
 * (docs/security.md, docs/deployment.md, ADR 0012). Change the policy in the
 * same commit as any change to what is collected, kept or shared, and bump
 * LEGAL_VERSION with the backend consent version.
 */

import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { CONTACT_EMAIL, MINIMUM_AGE, OPERATOR, OPERATOR_COUNTRY } from "../lib/legal";
import { LegalDocument, type LegalSection } from "./LegalPage";

const mail = <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

const SECTIONS: LegalSection[] = [
  {
    id: "who",
    title: "Who we are",
    body: (
      <p>
        Academious is run by {OPERATOR}, an individual based in {OPERATOR_COUNTRY} ("we", "us").
        We are the controller of the personal data described here. You can reach us about anything
        in this policy at {mail}.
      </p>
    ),
  },
  {
    id: "collect",
    title: "What we collect",
    body: (
      <>
        <h3>When you browse without an account</h3>
        <ul>
          <li>
            <strong>Searches and interest previews.</strong> Your search text and any interests you
            describe are sent to our server to compute results. Our application stores neither,
            and its own logs record only their length and counts.
          </li>
          <li>
            <strong>Server access logs.</strong> Our web server records each request to the API: your
            IP address, the time, the address requested (which, for a search, includes the search
            text), the response status and your browser's user-agent. We use these to keep the
            service running and to stop abuse.
          </li>
          <li>
            <strong>Analytics.</strong> The website uses Vercel Web Analytics to count page views. It
            sets no cookies and builds no profile of you across sites; it records the page, referring
            site, approximate country, and browser and device type.
          </li>
          <li>
            <strong>Data kept on your device.</strong> If you build a feed without signing up, your
            interests, bookmarks and feed feedback are kept in your browser's local storage. They
            never leave your device unless you later create an account and save your profile.
          </li>
        </ul>
        <h3>When you create an account</h3>
        <ul>
          <li>
            <strong>Account details:</strong> your name, email address and password. We store only a
            one-way (Argon2) hash of the password, never the password itself. We also record when
            you agreed to personalisation and which version of this policy you agreed to.
          </li>
          <li>
            <strong>Research profile:</strong> the interests, fields and example papers you give us.
          </li>
          <li>
            <strong>Saved papers.</strong>
          </li>
          <li>
            <strong>Feed activity:</strong> which papers we recommended to you, in what position and
            why (the ranking signals at that moment), and what you did with them: seeing, opening,
            expanding the abstract, following a link out, saving, asking for more or less like it,
            dismissing or hiding a topic, and how long you spent on an item.
          </li>
          <li>
            <strong>Your personal ranking adjustments</strong>, learned from that explicit feedback.
          </li>
        </ul>
        <h3>When you email us</h3>
        <p>Your email address and whatever you choose to tell us.</p>
        <p>
          We do not collect payment details, precise location, contacts, or anything from your
          other accounts.
        </p>
      </>
    ),
  },
  {
    id: "use",
    title: "How we use it, and why we are allowed to",
    body: (
      <>
        <div className="legal__table-wrap">
          <table className="legal__table">
            <thead>
              <tr><th scope="col">Purpose</th><th scope="col">Legal basis</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>Running your account: sign-in, email verification, password reset, saved papers</td>
                <td>Providing the service you asked for (contract)</td>
              </tr>
              <tr>
                <td>Personalising your feed from your profile and feed activity</td>
                <td>Your consent, given when you sign up</td>
              </tr>
              <tr>
                <td>Collaborative recommendations (see below)</td>
                <td>Your consent, given when you sign up</td>
              </tr>
              <tr>
                <td>Security, rate limiting and preventing abuse; access logs</td>
                <td>Our legitimate interest in keeping the service safe and available</td>
              </tr>
              <tr>
                <td>Counting page views to understand what is used</td>
                <td>Our legitimate interest in improving the service</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          <strong>Collaborative recommendations.</strong> Papers that readers with similar activity
          found useful can be suggested to you, and your activity can contribute to suggestions for
          others. A paper is only suggested this way when at least three different readers support
          it, and no reader ever sees another reader's identity, profile, saves or activity.
        </p>
        <p>
          Learning from your feedback only changes <em>your</em> ranking. It never changes how
          papers are ranked for everyone else.
        </p>
        <p>
          We only email you to verify your address or reset your password. We do not send marketing.
          We do not sell your data, show advertising, or send your profile or activity to any AI or
          language-model service.
        </p>
      </>
    ),
  },
  {
    id: "share",
    title: "Who else handles it",
    body: (
      <>
        <p>We use a small number of providers who process data on our behalf, only to run Academious:</p>
        <ul>
          <li><strong>netcup GmbH</strong> (Germany): hosts the server and database.</li>
          <li><strong>Vercel Inc.</strong> (United States): hosts the website and provides its page-view analytics.</li>
          <li><strong>Resend</strong> (United States): delivers verification and password-reset emails.</li>
          <li>
            An off-site storage provider for database backups. Backups are encrypted before they
            leave our server, and the provider cannot read them.
          </li>
        </ul>
        <p>
          We will disclose personal data if the law requires it, or where necessary to protect
          the safety of people or the service. We will never otherwise share it.
        </p>
      </>
    ),
  },
  {
    id: "transfers",
    title: "International transfers",
    body: (
      <p>
        We operate from {OPERATOR_COUNTRY}, our server is in Germany, and some providers are in the
        United States, so your data crosses borders. Where the law requires it, we rely on our
        providers' data-processing terms, including the European Commission's standard contractual
        clauses, to keep it protected to the same standard.
      </p>
    ),
  },
  {
    id: "retention",
    title: "How long we keep it",
    body: (
      <ul>
        <li>
          <strong>Account data</strong> (details, profile, saves, feed activity and ranking adjustments)
          is kept while your account exists. When you delete your account, all of it is erased from
          our live database at once.
        </li>
        <li>
          <strong>Backups</strong> roll over automatically, so deleted data disappears from them within
          12 months. We do not restore deleted accounts from backups.
        </li>
        <li><strong>Sign-in sessions</strong> expire after 7 days, or when you sign out.</li>
        <li>
          <strong>Server access logs</strong> are kept in rotating files limited to about 50 MB in total;
          the oldest entries are overwritten automatically as new traffic arrives.
        </li>
        <li><strong>Emails to us</strong> are kept for as long as needed to deal with them.</li>
      </ul>
    ),
  },
  {
    id: "rights",
    title: "Your rights",
    body: (
      <>
        <p>
          Under the Data Protection Act 2017 of Mauritius, and, if you are in the European Union or
          the United Kingdom, the GDPR, you can:
        </p>
        <ul>
          <li>ask for a copy of the personal data we hold about you, in a portable format;</li>
          <li>correct it;</li>
          <li>
            delete it: <Link to="/account">Settings</Link> has a button that deletes your account and
            everything tied to it immediately;
          </li>
          <li>withdraw your consent to personalisation at any time, which you do by deleting your account;</li>
          <li>object to, or ask us to restrict, how we use it.</li>
        </ul>
        <p>
          Email {mail} from the address on your account for anything not covered in Settings. We
          reply within one month. You can also complain to the Data Protection Office of Mauritius,
          or to the data protection authority where you live.
        </p>
      </>
    ),
  },
  {
    id: "cookies",
    title: "Cookies and local storage",
    body: (
      <>
        <p>
          We set one cookie, <code>academious_session</code>, and only when you sign in. It keeps you
          signed in, cannot be read by scripts on the page, and expires after 7 days. It is strictly
          necessary, so we do not ask for permission to set it.
        </p>
        <p>
          Your browser's local storage holds your on-device profile and bookmarks and a note that you
          are signed in. Clearing your browser's site data removes all of it. We use no advertising or
          cross-site tracking cookies.
        </p>
      </>
    ),
  },
  {
    id: "children",
    title: "Children",
    body: (
      <p>
        Accounts are for people aged {MINIMUM_AGE} or over. If you believe a younger person has
        created one, tell us and we will delete it.
      </p>
    ),
  },
  {
    id: "security",
    title: "Security",
    body: (
      <p>
        Traffic is encrypted with HTTPS, passwords are hashed with Argon2, sessions can be revoked,
        backups are encrypted, and access to the server is limited to us. No system is perfectly
        secure; if a breach puts your data at risk, we will tell you and the authorities as the law
        requires.
      </p>
    ),
  },
  {
    id: "changes",
    title: "Changes to this policy",
    body: (
      <p>
        If we change this policy we will update the date at the top. If a change affects how your
        data is used for personalisation, we will tell you before it takes effect and ask for your
        agreement again where the law requires it.
      </p>
    ),
  },
];

export function PrivacyPage() {
  useDocumentTitle("Privacy policy");
  return (
    <LegalDocument
      title="Privacy policy"
      lead="What Academious collects, why, who else sees it, and how to have it removed."
      sections={SECTIONS}
      sibling={{ to: "/terms", label: "terms of use" }}
    />
  );
}
