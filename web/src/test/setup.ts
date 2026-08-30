import { configure } from "@testing-library/dom";
import "@testing-library/jest-dom/vitest";

// Routes are code-split, so a `findBy*` waits for a dynamic import as well as
// for the stubbed request. One second is enough on an idle machine and not
// enough on a loaded one, which shows up as an intermittent timeout rather than
// as a real failure.
//
// Raised from 5 s when the suite reached eight files: vitest runs them in
// parallel, and on a four-core machine that is enough contention to push a
// dynamic import past five seconds - observed as five failures in one run and
// none in the next, on identical code. It stays below the 20 s `testTimeout` so
// a genuinely stuck test still fails on the assertion rather than on the file.
configure({ asyncUtilTimeout: 15_000 });

// Tests never reach the network. Any component that tries without an explicit
// stub fails loudly here rather than hanging or silently hitting a real API.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("unstubbed fetch in a test"))),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
