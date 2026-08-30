/**
 * A small labelled chip. Tone carries meaning, not decoration: `danger` is
 * reserved for retraction and nothing else competes with it visually.
 */

import "./Badge.css";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
}

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
