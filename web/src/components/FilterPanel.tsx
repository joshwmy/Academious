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

import { useCallback, useId } from "react";
import { listFields } from "../api/client";
import {
  FIELDS,
  NO_FILTERS,
  PREPRINT_POLICIES,
  SOURCES,
  countActiveFilters,
  type FieldSlug,
  type PaperFilters,
  type SourceKey,
} from "../lib/filters";
import { useRequest } from "../hooks/useRequest";
import "./FilterPanel.css";

interface FilterPanelProps {
  filters: PaperFilters;
  onChange: (next: PaperFilters) => void;
}

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const headingId = useId();
  // The vocabulary itself is a constant; only the counts come from the network.
  // A failed or pending request therefore costs the numbers, never the filter:
  // the fields render either way. One request per mount, cancelled on unmount.
  const runFields = useCallback((signal: AbortSignal) => listFields(signal), []);
  const { state: fieldState } = useRequest(runFields);
  const counts = fieldState.data
    ? new Map(fieldState.data.fields.map((entry) => [entry.slug, entry.paper_count]))
    : null;
  const withoutField = fieldState.data?.papers_without_field ?? null;
  // Radio groups are scoped by name, so the name must be unique to this
  // instance or a second panel on the page would share one selection.
  const preprintGroup = useId();
  const active = countActiveFilters(filters);

  const toggleField = (slug: FieldSlug, checked: boolean) => {
    const fields = checked
      ? FIELDS.map((field) => field.slug).filter(
          (candidate) => candidate === slug || filters.fields.includes(candidate),
        )
      : filters.fields.filter((candidate) => candidate !== slug);
    onChange({ ...filters, fields });
  };

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

        <fieldset className="filters__group filters__group--fields">
          <legend className="filters__legend">Field</legend>
          <div className="filters__scroll">
            {FIELDS.map((field) => {
              const count = counts?.get(field.slug);
              // A field with nothing in it is still shown, greyed by its count
              // rather than removed: a list whose length changes with the
              // corpus makes a filter people used yesterday vanish today.
              return (
                <label className="filters__option" key={field.slug}>
                  <input
                    type="checkbox"
                    checked={filters.fields.includes(field.slug)}
                    onChange={(event) => toggleField(field.slug, event.target.checked)}
                  />
                  <span>{field.label}</span>
                  {count === undefined ? null : (
                    <span className="filters__count">{count.toLocaleString()}</span>
                  )}
                </label>
              );
            })}
          </div>
          {withoutField !== null && withoutField > 0 ? (
            // Said plainly rather than discovered: most of the corpus reaches us
            // from sources that classify papers in a vocabulary nothing maps
            // onto these fields, and choosing any field hides all of them.
            <p className="filters__note">
              {withoutField.toLocaleString()} papers carry no field and are hidden while one is
              selected.
            </p>
          ) : null}
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
        // The checkboxes already show what is set and the clear button only
        // appears when something is. This exists to announce the change to a
        // screen reader, which has no equivalent of glancing at the controls.
        <p className="sr-only" role="status">
          {active} {active === 1 ? "filter" : "filters"} active.
        </p>
      ) : null}
    </section>
  );
}
