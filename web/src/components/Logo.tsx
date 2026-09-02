/**
 * The Academious mark and wordmark.
 *
 * The mark is inline SVG rather than an `<img>` so it inherits `currentColor`
 * and needs no second request; `public/logo-mark.svg` is the same geometry, kept
 * for use outside the application. The wordmark is real text, not an image, so
 * it scales with the type system, is selectable, and reads correctly to a screen
 * reader without an alt attribute standing in for it.
 */

import "./Logo.css";

/** The mark alone. Decorative wherever a visible wordmark sits beside it. */
export function LogoMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      className="logo-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="3.6"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M7 26 16 6.5 25 26" />
      <path d="M1.5 26 H30.5" />
    </svg>
  );
}

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo__word">Academious</span>
    </span>
  );
}
