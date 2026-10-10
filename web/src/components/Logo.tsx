/**
 * The Academious mark and wordmark.
 *
 * The mark is the feed: three lines narrowing from the whole literature to the
 * few papers worth reading today, with a dot where the reader's attention lands.
 * It is drawn as geometry, never as a glyph, so it renders identically on every
 * platform regardless of which fonts are installed.
 *
 * `public/logo-mark.svg` and `public/favicon.svg` carry the same geometry for
 * use outside the application; `scripts/build-icons.py` rasterises it into the
 * PNG and ICO assets. Change all three together. The wordmark is real text, not
 * an image, so it scales with the type system, is selectable, and reads
 * correctly to a screen reader without an alt attribute standing in for it.
 */

import { useId } from "react";
import "./Logo.css";

export function LogoMark({ size = 24 }: { size?: number }) {
  // A per-instance id: two marks on one page must not share a gradient id, or
  // hiding the first would blank the second.
  const gradientId = `academious-mark-${useId()}`;
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
        <linearGradient id={gradientId} x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7d8af0" />
          <stop offset="1" stopColor="#6359dc" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gradientId})`} />
      <g stroke="#ffffff" strokeWidth="3" strokeLinecap="round">
        <path d="M9 10.5H23" />
        <path d="M9 16H19.5" />
        <path d="M9 21.5H15.5" />
      </g>
      <circle cx="22" cy="21.5" r="2" fill="#d4d0fb" />
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
