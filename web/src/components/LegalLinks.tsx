import { Link } from "react-router-dom";

/**
 * Links to the privacy policy and terms, for footers and the sign-up form.
 *
 * `newTab` is for forms: following a link must not throw away what the reader
 * has already typed.
 */
export function LegalLinks({ className, newTab = false }: { className?: string; newTab?: boolean }) {
  const target = newTab ? { target: "_blank", rel: "noopener" } : {};
  return (
    <span className={className}>
      <Link to="/privacy" {...target}>Privacy</Link>
      {" · "}
      <Link to="/terms" {...target}>Terms</Link>
    </span>
  );
}
