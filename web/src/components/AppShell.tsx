import type { ReactNode } from "react";
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { filtersToSearchParams, parseFilters } from "../lib/filters";
import { ExternalLink } from "./ExternalLink";
import { Logo } from "./Logo";
import { SearchBar } from "./SearchBar";
import "./AppShell.css";

type IconName = "home" | "papers" | "collections" | "interests" | "profile" | "settings";

function NavIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V21h13V9.5" /><path d="M9.5 21v-7h5v7" /></>,
    papers: <><path d="M6 3.5h9l3 3V20.5H6z" /><path d="M15 3.5v4h4" /><path d="M9 11h6M9 15h6" /></>,
    collections: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
    interests: <path d="M12 20.5s-7-4.1-7-10A4 4 0 0 1 12 8a4 4 0 0 1 7 2.5c0 5.9-7 10-7 10Z" />,
    profile: <><circle cx="12" cy="8" r="3.5" /><path d="M5.5 20c.7-4 3-6 6.5-6s5.8 2 6.5 6" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
  };

  return <svg className="app-nav__icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeQuery = location.pathname === "/search" ? (searchParams.get("q") ?? "") : "";
  const isPapers = location.pathname === "/search" || location.pathname.startsWith("/papers/");
  const { user } = useAuth();

  const submitSearch = (query: string) => {
    const params = filtersToSearchParams(parseFilters(searchParams));
    params.set("q", query);
    navigate(`/search?${params.toString()}`);
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>

      <aside className="app-sidebar">
        <Link className="app-sidebar__brand" to="/" aria-label="Academious, home"><Logo /></Link>
        <nav className="app-nav" aria-label="Primary navigation">
          <Link className="app-nav__link" to="/" aria-current={location.pathname === "/" ? "page" : undefined}><NavIcon name="home" /><span>Home</span></Link>
          <Link className="app-nav__link" to="/search" aria-current={isPapers ? "page" : undefined}><NavIcon name="papers" /><span>Papers</span></Link>
          <Link className="app-nav__link" to="/saved" aria-current={location.pathname === "/saved" ? "page" : undefined}><NavIcon name="collections" /><span>Collections</span></Link>
          <Link className="app-nav__link" to="/profile" aria-current={location.pathname === "/profile" ? "page" : undefined}><NavIcon name="interests" /><span>Interests</span></Link>
          <Link className="app-nav__link" to="/profile" aria-current={location.pathname === "/profile" ? "page" : undefined}><NavIcon name="profile" /><span>Profile</span></Link>
        </nav>
        <div className="app-sidebar__bottom">
          <Link className="app-nav__link" to="/account" aria-current={location.pathname === "/account" ? "page" : undefined}><NavIcon name="settings" /><span>Settings</span></Link>
        </div>
      </aside>

      <div className="app-workspace">
        <header className="app-toolbar">
          <div className="app-toolbar__search"><SearchBar initialQuery={activeQuery} onSubmit={submitSearch} /></div>
          <Link
            className="app-toolbar__profile"
            to="/account"
            aria-current={location.pathname === "/account" ? "page" : undefined}
          >
            {user ? user.display_name : "Sign in"}
          </Link>
        </header>
        <main className="app-main" id="main"><Outlet /></main>
        <footer className="app-footer">
          <div className="app-footer__inner">
            <p className="app-footer__note">Academious searches its own curated corpus of recent research from arXiv, bioRxiv/medRxiv, Europe PMC and OpenAlex. It is not a search over all published science.</p>
            <p className="app-footer__credit">Retraction status from the <ExternalLink href="https://gitlab.com/crossref/retraction-watch-data">Retraction Watch database</ExternalLink>, distributed by Crossref under <ExternalLink href="https://creativecommons.org/licenses/by/4.0/">CC-BY 4.0</ExternalLink>.</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
