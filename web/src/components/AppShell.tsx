/**
 * Header, search, and the main landmark every page renders into.
 *
 * Search lives in the shell so it is reachable from every route, and submitting
 * always navigates to `/search?q=…` - the URL is the query, which is what makes
 * a result page shareable, bookmarkable and correct under the back button.
 *
 * Whatever filters the current URL carries travel with the query. Both surfaces
 * accept the same filters, so a reader who narrows the feed to arXiv preprints
 * and then searches gets a search over arXiv preprints; dropping the filters at
 * the moment of searching is the asymmetry WEB-010 was raised about. Nothing is
 * hidden by this: the search page renders the same filter panel, showing
 * exactly what is in force.
 */

import { Link, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { filtersToSearchParams, parseFilters } from "../lib/filters";
import { SearchBar } from "./SearchBar";
import "./AppShell.css";

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeQuery = location.pathname === "/search" ? (searchParams.get("q") ?? "") : "";

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="app-header">
        <div className="app-header__inner">
          <Link className="app-header__brand" to="/">
            Academious
          </Link>
          <div className="app-header__search">
            <SearchBar
              initialQuery={activeQuery}
              onSubmit={(query) => {
                // Re-parsing rather than forwarding the raw query string drops
                // the feed's offset and anything unrecognised, and leaves the
                // filters canonically ordered.
                const params = filtersToSearchParams(parseFilters(searchParams));
                params.set("q", query);
                navigate(`/search?${params.toString()}`);
              }}
            />
          </div>
        </div>
      </header>

      <main className="app-main" id="main">
        <Outlet />
      </main>

      <footer className="app-footer">
        <p>
          Academious searches its own curated corpus of recent literature from arXiv and
          bioRxiv/medRxiv. It is not a search over all published science.
        </p>
      </footer>
    </>
  );
}
