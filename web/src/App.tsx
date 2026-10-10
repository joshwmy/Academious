/**
 * Routes.
 *
 * `/` is a gate: a newcomer gets the landing page, and anyone who is signed in
 * or already has a profile on this device goes straight to `/feed`. Sign up,
 * sign in and first-run setup sit outside the application shell, because a
 * sidebar full of destinations is noise before there is anything in them.
 * Secondary pages are lazily loaded so the first screen does not carry their
 * code.
 */

import { lazy, Suspense, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PaperListSkeleton } from "./components/States";
import { FeedPage } from "./pages/FeedPage";
import { LandingPage } from "./pages/LandingPage";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { loadProfileDraft } from "./lib/profileStorage";

const SearchPage = lazy(() =>
  import("./pages/SearchPage").then((module) => ({ default: module.SearchPage })),
);
const PaperPage = lazy(() =>
  import("./pages/PaperPage").then((module) => ({ default: module.PaperPage })),
);
const ProfilePage = lazy(() =>
  import("./pages/ProfilePage").then((module) => ({ default: module.ProfilePage })),
);
const AccountPage = lazy(() =>
  import("./pages/AccountPage").then((module) => ({ default: module.AccountPage })),
);
const SavedPapersPage = lazy(() =>
  import("./pages/SavedPapersPage").then((module) => ({ default: module.SavedPapersPage })),
);
const VerifyPage = lazy(() =>
  import("./pages/AccountPage").then((module) => ({ default: module.VerifyPage })),
);
const SignUpPage = lazy(() =>
  import("./pages/AuthPage").then((module) => ({ default: module.SignUpPage })),
);
const SignInPage = lazy(() =>
  import("./pages/AuthPage").then((module) => ({ default: module.SignInPage })),
);
const WelcomePage = lazy(() =>
  import("./pages/WelcomePage").then((module) => ({ default: module.WelcomePage })),
);
const NotFoundPage = lazy(() =>
  import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })),
);

function HomeGate() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user || loadProfileDraft()) return <Navigate to="/feed" replace />;
  return <LandingPage />;
}

/**
 * Signed-in readers have no use for the sign-up and sign-in forms.
 *
 * Decided once, when the page opens, not on every render. Signing in from
 * this page sets the user while navigation to the next page is still pending
 * (router navigations are transitions, and the next page is lazily loaded), so
 * a check that re-ran would see the new user and send them to /feed, skipping
 * the setup step sign-up is about to show.
 */
function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const [wasGuest, setWasGuest] = useState<boolean | null>(null);
  if (!loading && wasGuest === null) setWasGuest(user === null);
  if (wasGuest === null) return null;
  return wasGuest ? children : <Navigate to="/feed" replace />;
}

export function App() {
  return (
    <AuthProvider><Routes>
      <Route index element={<HomeGate />} />
      <Route path="signup" element={<Suspense fallback={null}><GuestOnly><SignUpPage /></GuestOnly></Suspense>} />
      <Route path="signin" element={<Suspense fallback={null}><GuestOnly><SignInPage /></GuestOnly></Suspense>} />
      <Route path="welcome" element={<Suspense fallback={null}><WelcomePage /></Suspense>} />
      <Route element={<AppShell />}>
        <Route path="feed" element={<FeedPage />} />
        <Route
          path="search"
          element={
            <Suspense fallback={<PaperListSkeleton count={4} />}>
              <SearchPage />
            </Suspense>
          }
        />
        <Route
          path="profile"
          element={
            <Suspense fallback={<PaperListSkeleton count={3} />}>
              <ProfilePage />
            </Suspense>
          }
        />
        <Route path="account" element={<Suspense fallback={null}><AccountPage /></Suspense>} />
        <Route path="saved" element={<Suspense fallback={<PaperListSkeleton count={3} />}><SavedPapersPage /></Suspense>} />
        <Route path="verify" element={<Suspense fallback={null}><VerifyPage /></Suspense>} />
        <Route
          path="papers/:paperId"
          element={
            <Suspense fallback={<PaperListSkeleton count={1} />}>
              <PaperPage />
            </Suspense>
          }
        />
        <Route
          path="*"
          element={
            <Suspense fallback={null}>
              <NotFoundPage />
            </Suspense>
          }
        />
      </Route>
    </Routes></AuthProvider>
  );
}
