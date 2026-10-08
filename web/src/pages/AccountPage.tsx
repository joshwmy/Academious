import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  deleteAccount,
  forgotPassword,
  loginAccount,
  registerAccount,
  requestVerification,
  resetPassword,
  verifyAccount,
} from "../api/client";
import { ApiError } from "../api/errors";
import { useAuth } from "../auth/AuthContext";
import { ACCOUNT_SESSION_MARKER } from "../auth/session";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import "./Page.css";
import "./ProfilePage.css";

export function AccountPage() {
  useDocumentTitle("Account");
  const { user, loading, refresh, logout } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [params] = useSearchParams();
  const navigate = useNavigate();
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

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await registerAccount({ email, password, display_name: displayName });
        await requestVerification(email);
        setNotice("Account created. Check your email to verify it, then sign in.");
        setMode("login");
      } else {
        await loginAccount(email, password);
        localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
        await refresh();
      }
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "We could not complete that request.");
    } finally {
      setBusy(false);
    }
  };

  if (resetToken) {
    return (
      <div className="page profile">
        <header className="page__header"><h1 className="page__title">Choose a new password</h1><p className="page__lead">Use at least 12 characters.</p></header>
        {error ? <p className="profile__error" role="alert">{error}</p> : null}
        <form className="profile__section" onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          void resetPassword(resetToken, password)
            .then(() => { setNotice("Password changed. You can sign in now."); navigate("/account", { replace: true }); })
            .catch((cause: unknown) => setError(cause instanceof ApiError ? cause.message : "We could not reset your password."))
            .finally(() => setBusy(false));
        }}>
          <label className="profile__choice"><span className="profile__choice-label">New password</span><input className="profile__input" type="password" autoComplete="new-password" minLength={12} value={password} required onChange={(event) => setPassword(event.target.value)} /></label>
          <button className="profile__button profile__button--primary" disabled={busy} type="submit">Set new password</button>
        </form>
      </div>
    );
  }

  return (
    <div className="page profile">
      <header className="page__header">
        <h1 className="page__title">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
        <p className="page__lead">Sync your reading profile, saved papers and recommendation tuning.</p>
      </header>
      {error ? <p className="profile__error" role="alert">{error}</p> : null}
      {notice ? <p className="feed-notice" role="status">{notice}</p> : null}
      <form className="profile__section" onSubmit={(event) => void submit(event)}>
        {mode === "register" ? <label className="profile__choice"><span className="profile__choice-label">Name</span><input className="profile__input" value={displayName} required maxLength={120} onChange={(event) => setDisplayName(event.target.value)} /></label> : null}
        <label className="profile__choice"><span className="profile__choice-label">Email</span><input className="profile__input" type="email" autoComplete="email" value={email} required onChange={(event) => setEmail(event.target.value)} /></label>
        <label className="profile__choice"><span className="profile__choice-label">Password</span><input className="profile__input" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={12} value={password} required onChange={(event) => setPassword(event.target.value)} /></label>
        {mode === "register" ? <label className="profile__choice"><span><input type="checkbox" checked={consent} required onChange={(event) => setConsent(event.target.checked)} /> I agree that Academious may store my profile, saves, impressions and explicit feedback to personalise and improve recommendations. I can delete my account and this data.</span></label> : null}
        <div className="profile__actions"><button className="profile__button profile__button--primary" disabled={busy || (mode === "register" && !consent)} type="submit">{busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}</button></div>
      </form>
      <button className="profile__remove" type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>{mode === "login" ? "Create an account" : "I already have an account"}</button>
      {mode === "login" ? <button className="profile__remove" type="button" disabled={!email || busy} onClick={() => {
        setBusy(true);
        void forgotPassword(email)
          .then(() => setNotice("If that address has an account, a password-reset email is on its way."))
          .catch(() => setNotice("If that address has an account, a password-reset email is on its way."))
          .finally(() => setBusy(false));
      }}>Forgot password</button> : null}
    </div>
  );
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
      .then(() => { setStatus("Email verified. You can sign in now."); setTimeout(() => navigate("/account"), 1200); })
      .catch(() => setStatus("This verification link is invalid or expired."));
  }, [navigate, token]);
  return <div className="page"><h1 className="page__title">Email verification</h1><p role="status">{status}</p></div>;
}
