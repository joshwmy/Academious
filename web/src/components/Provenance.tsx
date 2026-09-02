/**
 * Where a paper came from, and what kind of record it is.
 *
 * Deliberately not a `Badge`. Status pills already own that shape, and
 * provenance is a different dimension from integrity: a reader must never have
 * to work out whether a coloured chip is telling them "bioRxiv" or "Retracted".
 * A leading rule and a name reads as a source line instead.
 */

import type { Provenance as ProvenanceValue } from "../lib/format";
import "./Provenance.css";

export function Provenance({ value }: { value: ProvenanceValue }) {
  return <span className={`provenance provenance--${value.kind}`}>{value.label}</span>;
}
