/**
 * The only way this application renders a link to somewhere it does not control.
 *
 * The URL is validated first (`safeExternalUrl`); an unsupported scheme renders
 * as plain text rather than as a link, so hostile metadata cannot become a
 * clickable `javascript:` payload. `rel="noopener noreferrer"` is not optional:
 * `noopener` denies the opened page a handle on this one, and `noreferrer`
 * keeps the reader's current paper out of a third party's logs.
 */

import { safeExternalUrl } from "../lib/url";
import "./ExternalLink.css";

interface ExternalLinkProps {
  href: string | null | undefined;
  children: React.ReactNode;
  className?: string;
  /** Announced to screen readers so the new tab is not a surprise. */
  describeNewTab?: boolean;
}

export function ExternalLink({
  href,
  children,
  className,
  describeNewTab = true,
}: ExternalLinkProps) {
  const safe = safeExternalUrl(href);

  if (!safe) {
    return <span className={className}>{children}</span>;
  }

  return (
    <a
      className={["external-link", className].filter(Boolean).join(" ")}
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <span aria-hidden="true" className="external-link__icon">
        ↗
      </span>
      {describeNewTab ? <span className="sr-only"> (opens in a new tab)</span> : null}
    </a>
  );
}
