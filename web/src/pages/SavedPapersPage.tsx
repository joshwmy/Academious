import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listSavedPapers, removeSavedPaper } from "../api/client";
import type { PaperSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PaperCard } from "../components/PaperCard";
import { EmptyState, PaperListSkeleton } from "../components/States";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import "./Page.css";

export function SavedPapersPage() {
  useDocumentTitle("Saved papers");
  const { user, loading: authLoading } = useAuth();
  const [papers, setPapers] = useState<PaperSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user?.is_verified) return;
    void listSavedPapers()
      .then(setPapers)
      .catch(() => setError("We could not load your saved papers."))
      .finally(() => setLoading(false));
  }, [authLoading, user]);

  if (authLoading || (user?.is_verified && loading)) return <div className="page"><PaperListSkeleton count={3} /></div>;
  if (!user?.is_verified) {
    return <div className="page"><EmptyState title="Sign in to keep a collection"><p>Your saved papers will follow you between devices.</p><p><Link className="button" to="/account">Sign in or create an account</Link></p></EmptyState></div>;
  }
  return (
    <div className="page">
      <header className="page__header"><h1 className="page__title">Saved papers</h1><p className="page__lead">A quiet reading list for work you want to return to.</p></header>
      {error ? <p className="profile__error" role="alert">{error}</p> : null}
      {papers.length === 0 ? <EmptyState title="Nothing saved yet"><p>Use the bookmark on a recommendation to keep it here.</p></EmptyState> : (
        <ul className="paper-list" aria-label="Saved papers">{papers.map((paper) => <li key={paper.id}><PaperCard paper={paper} initiallyBookmarked onBookmarkChange={(saved) => { if (!saved) { setPapers((current) => current.filter((item) => item.id !== paper.id)); void removeSavedPaper(paper.id).catch(() => setError("We could not remove that paper.")); } }} /></li>)}</ul>
      )}
    </div>
  );
}
