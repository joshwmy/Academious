/**
 * Terms of use.
 *
 * Written for a free service run by one person: plain obligations on both
 * sides, the research-content caveats that matter most (preprints, no medical
 * advice), and liability limited only as far as consumer law allows.
 */

import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { CONTACT_EMAIL, MINIMUM_AGE, OPERATOR, OPERATOR_COUNTRY } from "../lib/legal";
import { LegalDocument, type LegalSection } from "./LegalPage";

const mail = <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

const SECTIONS: LegalSection[] = [
  {
    id: "agreement",
    title: "Agreement",
    body: (
      <>
        <p>
          Academious is run by {OPERATOR}, an individual based in {OPERATOR_COUNTRY} ("we", "us"). By
          using Academious or creating an account you agree to these terms. If you do not agree,
          please do not use it.
        </p>
        <p>
          You must be at least {MINIMUM_AGE} to create an account. How we handle your data is set out
          in the <Link to="/privacy">privacy policy</Link>, which forms part of these terms.
        </p>
      </>
    ),
  },
  {
    id: "service",
    title: "The service",
    body: (
      <>
        <p>
          Academious is a free tool for discovering recent research. It shows bibliographic records,
          abstracts and links gathered from public sources, including arXiv, bioRxiv, medRxiv, Europe
          PMC and OpenAlex, and recommends papers based on the interests you give it.
        </p>
        <p>
          We may change, pause or stop any part of the service at any time, and we do not promise it
          will always be available or free of errors. If we close Academious, we will give account
          holders reasonable notice where we can.
        </p>
      </>
    ),
  },
  {
    id: "account",
    title: "Your account",
    body: (
      <ul>
        <li>Give accurate details, and keep your password to yourself.</li>
        <li>An account is for one person. You are responsible for what happens under it.</li>
        <li>Tell us at {mail} if you think someone else has used it.</li>
        <li>
          You can delete your account at any time from <Link to="/account">Settings</Link>.
        </li>
      </ul>
    ),
  },
  {
    id: "use",
    title: "Acceptable use",
    body: (
      <>
        <p>Do not:</p>
        <ul>
          <li>break the law, or use Academious to infringe anyone's rights;</li>
          <li>access, or try to access, another person's account or data;</li>
          <li>
            bulk-download or scrape the service, or send automated traffic intended to get round
            rate limits; the original sources offer their own bulk access;
          </li>
          <li>probe, overload or disrupt the service or its security;</li>
          <li>submit content that is unlawful or malicious.</li>
        </ul>
        <p>We may suspend or close an account that breaks these rules.</p>
      </>
    ),
  },
  {
    id: "content",
    title: "Research content",
    body: (
      <>
        <p>
          Papers, abstracts and other research shown on Academious belong to their authors and
          publishers and are shared under their own licences. We link to the original source; check
          its licence before you reuse anything.
        </p>
        <p>
          <strong>Preprints have not been peer reviewed.</strong> Many records come from preprint
          servers, and their findings may be incomplete, revised or wrong. Retraction flags come from
          third-party data and may be missing or out of date.
        </p>
        <p>
          <strong>Nothing on Academious is medical, clinical, legal or other professional advice.</strong>{" "}
          Recommendations and the reasons given for them are generated automatically and can be
          inaccurate. Do not base decisions about health or treatment on what you find here.
        </p>
      </>
    ),
  },
  {
    id: "yours",
    title: "What you give us",
    body: (
      <p>
        Your profile, saves and feedback remain yours. You let us store and process them only to
        provide and improve Academious for you, as described in the privacy policy. That permission
        ends when you delete your account.
      </p>
    ),
  },
  {
    id: "ours",
    title: "Our name and design",
    body: (
      <p>
        The Academious name, logo and design are ours. Software we publish under an open-source
        licence is governed by that licence.
      </p>
    ),
  },
  {
    id: "warranty",
    title: "No warranty",
    body: (
      <p>
        Academious is provided "as is" and "as available". To the extent the law allows, we make no
        promise that it is accurate, complete, uninterrupted or fit for a particular purpose.
      </p>
    ),
  },
  {
    id: "liability",
    title: "Limits on our liability",
    body: (
      <>
        <p>
          To the extent the law allows, we are not liable for any indirect or consequential loss, or
          for loss of data, profits or opportunity, arising from your use of Academious or of research
          found through it. Because the service is free, our total liability to you for any claim is
          limited to USD 50.
        </p>
        <p>
          Nothing in these terms limits liability that cannot be limited by law, such as for fraud,
          or removes rights you have as a consumer where you live.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes to these terms",
    body: (
      <p>
        We may update these terms and will change the date at the top when we do. We will tell
        account holders about significant changes before they take effect. If you keep using
        Academious after that, the new terms apply; if you do not accept them, delete your account.
      </p>
    ),
  },
  {
    id: "law",
    title: "Governing law",
    body: (
      <p>
        These terms are governed by the laws of the Republic of Mauritius, and the courts of
        Mauritius have jurisdiction over any dispute. If you are a consumer, you keep any protection
        that the mandatory law of your own country gives you, and you may also bring a claim there.
      </p>
    ),
  },
];

export function TermsPage() {
  useDocumentTitle("Terms of use");
  return (
    <LegalDocument
      title="Terms of use"
      lead="The agreement between you and Academious: what we provide, what we ask of you, and where responsibility stops."
      sections={SECTIONS}
      sibling={{ to: "/privacy", label: "privacy policy" }}
    />
  );
}
