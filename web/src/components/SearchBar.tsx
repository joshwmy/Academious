/**
 * The search control in the application shell.
 *
 * Submit-driven, not keystroke-driven. The backend allows twenty searches a
 * minute per client and each one costs roughly 160 ms of CPU on a shared box;
 * search-as-you-type would exhaust that budget in a single typed phrase and
 * spend most of it on prefixes nobody wanted results for. One deliberate
 * submission produces exactly one request.
 */

import { useId, useState } from "react";
import { MAX_QUERY_LENGTH } from "../api/client";
import "./SearchBar.css";

interface SearchBarProps {
  /** Current query from the URL, so the field survives navigation and reload. */
  initialQuery?: string;
  onSubmit: (query: string) => void;
}

export function SearchBar({ initialQuery = "", onSubmit }: SearchBarProps) {
  const inputId = useId();
  const hintId = useId();
  const [value, setValue] = useState(initialQuery);
  const [lastQuery, setLastQuery] = useState(initialQuery);

  // The URL is authoritative: a back-button navigation must be reflected here.
  // Adjusting during render rather than in an effect - React re-renders before
  // painting, so the field never shows the stale value, and there is no second
  // render pass to cascade from.
  if (initialQuery !== lastQuery) {
    setLastQuery(initialQuery);
    setValue(initialQuery);
  }

  const trimmed = value.trim();
  const tooLong = value.length > MAX_QUERY_LENGTH;
  const canSubmit = trimmed !== "" && !tooLong;

  return (
    <form
      className="search-bar"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        // Client-side checks are courtesy, not enforcement: the backend
        // validates independently and remains authoritative.
        if (!canSubmit) return;
        onSubmit(trimmed);
      }}
    >
      <label className="sr-only" htmlFor={inputId}>
        Search papers
      </label>
      <input
        id={inputId}
        className="search-bar__input"
        type="search"
        name="q"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Search by research interest…"
        autoComplete="off"
        spellCheck={false}
        maxLength={MAX_QUERY_LENGTH}
        aria-describedby={tooLong ? hintId : undefined}
        aria-invalid={tooLong || undefined}
      />
      <button type="submit" className="button search-bar__submit" disabled={!canSubmit}>
        Search
      </button>
      {tooLong ? (
        <p id={hintId} className="search-bar__hint" role="alert">
          Queries are limited to {MAX_QUERY_LENGTH} characters.
        </p>
      ) : null}
    </form>
  );
}
