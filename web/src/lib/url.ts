/**
 * External links come from harvested metadata, which is not ours and is not
 * trusted.
 *
 * A DOI landing page, a PDF location or a retraction notice all arrive as
 * strings from upstream sources. React escapes text, but it does not stop an
 * `href` from being `javascript:alert(1)` - and a paper record is a plausible
 * place for a hostile string to reach a user's browser. So every URL that
 * becomes an `href` passes through here first, and anything that is not plainly
 * http(s) is refused rather than sanitised into something that looks safe.
 */

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * Returns the URL when it is safe to navigate to, and `null` otherwise.
 * `null` means "render this as text, or not at all" - never as a link.
 */
export function safeExternalUrl(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (trimmed === "") return null;

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    // Relative or malformed. A bare path from upstream metadata is not
    // something we can resolve safely against our own origin.
    return null;
  }

  // Covers javascript:, data:, vbscript:, file:, blob: and anything else new.
  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) return null;

  return parsed.toString();
}

/** A DOI rendered as a resolvable link, or null when the DOI is unusable. */
export function doiUrl(doi: string | null | undefined): string | null {
  if (typeof doi !== "string") return null;
  const trimmed = doi.trim();
  if (trimmed === "") return null;
  // Upstream records store DOIs both bare and pre-resolved.
  if (/^https?:\/\//i.test(trimmed)) return safeExternalUrl(trimmed);
  if (!/^10\.\d{4,9}\//.test(trimmed)) return null;
  return safeExternalUrl(`https://doi.org/${encodeURI(trimmed)}`);
}
