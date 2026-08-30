/**
 * Routes.
 *
 * Three public routes, all stable and all linkable. Detail pages are lazily
 * loaded so the feed - the first thing anyone sees - does not carry the detail
 * page's code before it is needed.
 */

import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PaperListSkeleton } from "./components/States";
import { FeedPage } from "./pages/FeedPage";

const SearchPage = lazy(() =>
  import("./pages/SearchPage").then((module) => ({ default: module.SearchPage })),
);
const PaperPage = lazy(() =>
  import("./pages/PaperPage").then((module) => ({ default: module.PaperPage })),
);
const NotFoundPage = lazy(() =>
  import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })),
);

export function App() {
  return (
    <Routes>
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
    </Routes>
  );
}
