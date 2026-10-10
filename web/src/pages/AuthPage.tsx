/**
 * Sign up and sign in: one narrow card each, outside the application shell.
 *
 * A new account goes straight on to /welcome, the interests step. The backend
 * lets an unverified account sign in, so there is no reason to stop someone at
 * "check your email" before they have seen anything; the verification link is
 * sent in the background and only matters for syncing across devices.
 */

import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { forgotPassword, loginAccount, registerAccount, requestVerification, resetPassword } from "../api/client";
import { ApiError } from "../api/errors";
import { useAuth } from "../auth/AuthContext";
import { ACCOUNT_SESSION_MARKER } from "../auth/session";
import { Logo } from "../components/Logo";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import "../styles/motion.css";
import "./AuthPage.css";

const MIN_PASSWORD = 12;

function AuthLayout({ title, lead, children, footer }: { title: string; lead: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth__glow" aria-hidden="true" />
      <Link to="/" className="auth__brand" aria-label="Academious, home"><Logo /></Link>
      <main className="auth__card rise">
        <h1 className="auth__title">{title}</h1>
        <p className="auth__lead">{lead}</p>
        {children}
      </main>
      <p className="auth__footer rise" style={{ animationDelay: "120ms" }}>{footer}</p>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="auth-field">
      <span className="auth-field__label">{label}</span>
      {children}
      {hint ? <span className="auth-field__hint">{hint}</span> : null}
    </label>
  );
}

function PasswordInput({ value, onChange, autoComplete }: { value: string; onChange: (value: string) => void; autoComplete: string }) {
  const [shown, setShown] = useState(false);
  return (
    <span className="auth-field__password">
      <input
        className="auth-field__input"
        type={shown ? "text" : "password"}
        autoComplete={autoComplete}
        minLength={MIN_PASSWORD}
        value={value}
        required
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="button" className="auth-field__reveal" onClick={() => setShown((current) => !current)} aria-pressed={shown}>
        {shown ? "Hide" : "Show"}
      </button>
    </span>
  );
}

/** fastapi-users answers with bare codes; a reader should never see one. */
const AUTH_CODES: Record<string, string> = {
  RESET_PASSWORD_BAD_TOKEN: "This reset link is invalid or has expired. Request a new one from the sign-in page.",
  RESET_PASSWORD_INVALID_PASSWORD: `Choose a password of at least ${MIN_PASSWORD} characters.`,
  REGISTER_USER_ALREADY_EXISTS: "An account with that email already exists. Try signing in.",
  REGISTER_INVALID_PASSWORD: `Choose a password of at least ${MIN_PASSWORD} characters that doesn't contain your email.`,
  LOGIN_BAD_CREDENTIALS: "That email and password don't match.",
  LOGIN_USER_NOT_VERIFIED: "Verify your email first - the link is in your inbox.",
};

function describe(cause: unknown, fallback: string): string {
  if (!(cause instanceof ApiError)) return fallback;
  const code = Object.keys(AUTH_CODES).find((key) => cause.message.includes(key));
  if (code) return AUTH_CODES[code] ?? fallback;
  if (cause.kind === "rate_limited") return "Too many attempts. Wait a minute and try again.";
  if (cause.kind === "network") return "We couldn't reach Academious. Check your connection.";
  return /^[A-Z_]+$/.test(cause.message) ? fallback : cause.message;
}

export function SignUpPage() {
  useDocumentTitle("Create your account");
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!consent) {
      setError("Tick the box to let us personalise your feed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerAccount({ email, password, display_name: name.trim() });
      await loginAccount(email, password);
      localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
      // Navigate before the session user lands: /signup is guest-only, and a
      // signed-in user arriving first would bounce it to /feed and skip setup.
      navigate("/welcome", { replace: true });
      void refresh();
      // Best effort: the account works without it, and a failed send is
      // retried from the account page.
      void requestVerification(email).catch(() => undefined);
    } catch (cause: unknown) {
      setError(describe(cause, "We couldn't create your account. Try again in a moment."));
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      lead="A personal feed of new research, in about a minute."
      footer={<>Already have an account? <Link to="/signin">Sign in</Link></>}
    >
      {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
      <form className="auth__form" onSubmit={(event) => void submit(event)}>
        <Field label="Name">
          <input className="auth-field__input" autoComplete="name" value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field label="Email">
          <input className="auth-field__input" type="email" autoComplete="email" value={email} required onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Password" hint={`At least ${MIN_PASSWORD} characters.`}>
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" />
        </Field>
        <label className="auth__consent">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span>
            Personalise my feed. Academious stores my interests, saves and feedback to tune
            recommendations. I can delete my account and all of it at any time.
          </span>
        </label>
        <button className="button auth__submit" type="submit" disabled={busy}>
          {busy ? "Creating your account…" : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}

export function SignInPage() {
  useDocumentTitle("Sign in");
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [notice, setNotice] = useState<string | null>(
    params.get("reset") === "done" ? "Password changed. Sign in with your new one." : null,
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await loginAccount(email, password);
      localStorage.setItem(ACCOUNT_SESSION_MARKER, "true");
      navigate("/feed", { replace: true });
      void refresh();
    } catch (cause: unknown) {
      setError(describe(cause, "We couldn't sign you in. Try again in a moment."));
      setBusy(false);
    }
  };

  const reset = () => {
    if (!email) {
      setError("Enter your email first, then choose \"Forgot password\".");
      return;
    }
    setError(null);
    const done = () => setNotice("If that address has an account, a reset link is on its way.");
    void forgotPassword(email).then(done, done);
  };

  return (
    <AuthLayout
      title="Welcome back"
      lead="Sign in to see today's papers."
      footer={<>New to Academious? <Link to="/signup">Create an account</Link></>}
    >
      {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
      {notice ? <p className="auth__notice pop" role="status">{notice}</p> : null}
      <form className="auth__form" onSubmit={(event) => void submit(event)}>
        <Field label="Email">
          <input className="auth-field__input" type="email" autoComplete="email" value={email} required onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Password">
          <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" />
        </Field>
        <button type="button" className="auth__link-button" onClick={reset}>Forgot password?</button>
        <button className="button auth__submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthLayout>
  );
}

/** Reached from the password-reset email, via /account?reset_token=... */
export function ResetPasswordPage({ token }: { token: string }) {
  useDocumentTitle("Choose a new password");
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/signin?reset=done", { replace: true });
    } catch (cause: unknown) {
      setError(describe(cause, "This reset link is invalid or has expired. Request a new one from the sign-in page."));
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Choose a new password"
      lead={`Use at least ${MIN_PASSWORD} characters.`}
      footer={<>Remembered it? <Link to="/signin">Sign in</Link></>}
    >
      {error ? <p className="auth__error pop" role="alert">{error}</p> : null}
      <form className="auth__form" onSubmit={(event) => void submit(event)}>
        <Field label="New password">
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" />
        </Field>
        <button className="button auth__submit" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Set new password"}
        </button>
      </form>
    </AuthLayout>
  );
}
