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

export function LogoMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      className="logo-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="academious-mark" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
          <stop stopColor="#8a9cf5" />
          <stop offset="1" stopColor="#7169e8" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#academious-mark)" />
      <text x="16" y="22" textAnchor="middle" fill="white" fontFamily="Aptos, Segoe UI, sans-serif" fontSize="22" fontWeight="600">a</text>
    </svg>
  );
}

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo__word">academious</span>
    </span>
  );
}
