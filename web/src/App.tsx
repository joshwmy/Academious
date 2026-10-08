/**
 * Routes.
 *
 * Four public routes, all stable and all linkable. Secondary pages are lazily
 * loaded so the feed - the first thing anyone sees - does not carry the detail
 * page's code before it is needed.
 */

import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PaperListSkeleton } from "./components/States";
import { FeedPage } from "./pages/FeedPage";
import { AuthProvider } from "./auth/AuthContext";

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
const NotFoundPage = lazy(() =>
  import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })),
);

export function App() {
  return (
    <AuthProvider><Routes>
      <Route element={<AppShell />}>
        <Route index element={<FeedPage />} />
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
