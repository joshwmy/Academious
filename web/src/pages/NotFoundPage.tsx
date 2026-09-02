import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import "./Page.css";

export function NotFoundPage() {
  useDocumentTitle("Page not found");

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">Page not found</h1>
        <p className="page__lead">There is nothing at this address.</p>
      </header>
      <p>
        <Link className="button" to="/">
          Back to recent papers
        </Link>
      </p>
    </div>
  );
}
