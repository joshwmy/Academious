import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import {
  deleteAccount,
  requestVerification,
  verifyAccount,
} from "../api/client";
import { ApiError } from "../api/errors";
import { useAuth } from "../auth/AuthContext";
import { ResetPasswordPage } from "./AuthPage";
import { ACCOUNT_SESSION_MARKER } from "../auth/session";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import "./Page.css";
import "./ProfilePage.css";

export function AccountPage() {
  useDocumentTitle("Account");
  const { user, loading, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [params] = useSearchParams();
  const resetToken = params.get("reset_token");

  if (loading) return <p className="page" role="status">Checking your account…</p>;
  if (user) {
    return (
      <div className="page profile">
        <header className="page__header">
          <h1 className="page__title">Your account</h1>
          <p className="page__lead">{user.display_name} · {user.email}</p>
        </header>
        {!user.is_verified ? (
          <section className="profile__section">
            <h2 className="profile__heading">Verify your email</h2>
            <p className="profile__hint">Verification is required before personal research data is stored.</p>
            <button className="profile__button" type="button" onClick={() => {
              void requestVerification(user.email).then(() => setNotice("Verification email requested."));
            }}>Send verification email</button>
          </section>
        ) : (
          <p className="feed-notice">Your research profile, saves and recommendation feedback sync with this account.</p>
        )}
        {notice ? <p role="status">{notice}</p> : null}
        {error ? <p className="profile__error" role="alert">{error}</p> : null}
        <div className="profile__actions">
          <Link className="button" to="/profile">Edit research profile</Link>
          <button className="profile__remove" type="button" onClick={() => void logout()}>Sign out</button>
          <button className="profile__remove" type="button" disabled={busy} onClick={() => {
            if (!window.confirm("Delete your account, profile, saves and recommendation history? This cannot be undone.")) return;
            setBusy(true);
            void deleteAccount().then(() => {
              localStorage.removeItem(ACCOUNT_SESSION_MARKER);
              window.location.assign("/");
            }).catch((cause: unknown) => {
              setError(cause instanceof ApiError ? cause.message : "We could not delete your account.");
              setBusy(false);
            });
          }}>Delete account and data</button>
        </div>
      </div>
    );
  }

  // Signing in and signing up live at /signin and /signup; this page only
  // manages an account that exists, and finishes a password reset.
  if (!resetToken) return <Navigate to="/signin" replace />;

  return <ResetPasswordPage token={resetToken} />;
}

export function VerifyPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token");
  const [status, setStatus] = useState(
    token ? "Verifying your email…" : "This verification link is incomplete.",
  );
  useEffect(() => {
    if (!token) return;
    void verifyAccount(token)
      .then(() => { setStatus("Email verified. Your feed now syncs across devices."); setTimeout(() => navigate("/feed"), 1200); })
      .catch(() => setStatus("This verification link is invalid or expired."));
  }, [navigate, token]);
  return <div className="page"><h1 className="page__title">Email verification</h1><p role="status">{status}</p></div>;
}
