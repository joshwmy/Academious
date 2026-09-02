/**
 * Header, search, and the main landmark every page renders into.
 *
 * Search lives in the shell so it is reachable from every route, and submitting
 * always navigates to `/search?q=…` - the URL is the query, which is what makes
 * a result page shareable, bookmarkable and correct under the back button.
 *
 * It is deliberately the quieter half of the header. This product's first job is
 * discovery: the reader who already knows what to search for is the reader who
 * needed Academious least, so the field sits to one side of the brand at a fixed
 * modest width rather than spanning the bar like a search engine's.
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
import { ExternalLink } from "./ExternalLink";
import { Logo } from "./Logo";
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
          <Link className="app-header__brand" to="/" aria-label="Academious, home">
            <Logo />
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
        <div className="app-footer__inner">
          <p className="app-footer__note">
            Academious searches its own curated corpus of recent research from arXiv,
            bioRxiv/medRxiv, Europe PMC and OpenAlex. It is not a search over all published
            science.
          </p>
          {/*
            Not decoration, and not optional. Retraction status comes from the
            Retraction Watch database, which Crossref distributes under CC-BY
            4.0 - attribution is the whole of what that licence asks in return,
            and the badge on a retracted paper is the feature it pays for. See
            docs/licensing.md.
          */}
          <p className="app-footer__credit">
            Retraction status from the{" "}
            <ExternalLink href="https://gitlab.com/crossref/retraction-watch-data">
              Retraction Watch database
            </ExternalLink>
            , distributed by Crossref under{" "}
            <ExternalLink href="https://creativecommons.org/licenses/by/4.0/">
              CC-BY 4.0
            </ExternalLink>
            .
          </p>
        </div>
      </footer>
    </>
  );
}
