/**
 * The filter controls, shared by the feed and by search.
 *
 * Fully controlled: it holds no state of its own and reports every change to
 * the page, which writes the change into the URL. That is what keeps a filtered
 * feed linkable, and it means there is exactly one place a filter can be
 * described from - the query string - rather than two that can disagree. The
 * same component serves both surfaces: a reader who learns the controls once
 * should not meet a second, differently-shaped set of them on search.
 *
 * Changes apply immediately rather than behind an "Apply" button. The read
 * budget is 120 requests a minute against roughly 12 ms of database work, so a
 * request per toggle is affordable, and a filter that only takes effect after a
 * second, separate click is a filter people set and then wonder about. Search
 * is the opposite case and stays submit-driven; see SearchBar.
 */

import { useId } from "react";
import {
  NO_FILTERS,
  PREPRINT_POLICIES,
  SOURCES,
  countActiveFilters,
  type PaperFilters,
  type SourceKey,
} from "../lib/filters";
import "./FilterPanel.css";

interface FilterPanelProps {
  filters: PaperFilters;
  onChange: (next: PaperFilters) => void;
}

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const headingId = useId();
  // Radio groups are scoped by name, so the name must be unique to this
  // instance or a second panel on the page would share one selection.
  const preprintGroup = useId();
  const active = countActiveFilters(filters);

  const toggleSource = (key: SourceKey, checked: boolean) => {
    const sources = checked
      ? SOURCES.map((source) => source.key).filter(
          (candidate) => candidate === key || filters.sources.includes(candidate),
        )
      : filters.sources.filter((candidate) => candidate !== key);
    onChange({ ...filters, sources });
  };

  return (
    <section className="filters" aria-labelledby={headingId}>
      <div className="filters__head">
        <h2 className="filters__title" id={headingId}>
          Filters
        </h2>
        {active > 0 ? (
          <button type="button" className="button button--quiet" onClick={() => onChange(NO_FILTERS)}>
            Clear filters
          </button>
        ) : null}
      </div>

      <div className="filters__groups">
        <fieldset className="filters__group">
          <legend className="filters__legend">Source</legend>
          {SOURCES.map((source) => (
            <label className="filters__option" key={source.key}>
              <input
                type="checkbox"
                checked={filters.sources.includes(source.key)}
                onChange={(event) => toggleSource(source.key, event.target.checked)}
              />
              <span>{source.label}</span>
            </label>
          ))}
        </fieldset>

        <fieldset className="filters__group">
          <legend className="filters__legend">Type</legend>
          {PREPRINT_POLICIES.map((policy) => (
            <label className="filters__option" key={policy.value}>
              <input
                type="radio"
                name={preprintGroup}
                value={policy.value}
                checked={filters.preprints === policy.value}
                onChange={() => onChange({ ...filters, preprints: policy.value })}
              />
              <span>{policy.label}</span>
            </label>
          ))}
        </fieldset>

        <fieldset className="filters__group">
          <legend className="filters__legend">Availability</legend>
          <label className="filters__option">
            <input
              type="checkbox"
              checked={filters.peerReviewed}
              onChange={(event) => onChange({ ...filters, peerReviewed: event.target.checked })}
            />
            <span>Peer-reviewed only</span>
          </label>
          <label className="filters__option">
            <input
              type="checkbox"
              checked={filters.openAccess}
              onChange={(event) => onChange({ ...filters, openAccess: event.target.checked })}
            />
            <span>Open access only</span>
          </label>
        </fieldset>
      </div>

      {active > 0 ? (
        <p className="filters__summary" role="status">
          {active} {active === 1 ? "filter" : "filters"} active.
        </p>
      ) : null}
    </section>
  );
}
