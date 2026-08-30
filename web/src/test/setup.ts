import { configure } from "@testing-library/dom";
import "@testing-library/jest-dom/vitest";

// Routes are code-split, so a `findBy*` waits for a dynamic import as well as
// for the stubbed request. One second is enough on an idle machine and not
// enough on a loaded one, which shows up as an intermittent timeout rather than
// as a real failure.
configure({ asyncUtilTimeout: 5000 });

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
