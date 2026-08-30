/**
 * Paper metadata is harvested from third parties. Every one of these strings is
 * something an upstream record could plausibly carry into an href.
 */

import { describe, expect, it } from "vitest";
import { doiUrl, safeExternalUrl } from "./url";

describe("safeExternalUrl", () => {
  it("allows http and https", () => {
    expect(safeExternalUrl("https://example.org/paper")).toBe("https://example.org/paper");
    expect(safeExternalUrl("http://example.org/paper")).toBe("http://example.org/paper");
  });

  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(document.cookie)  ",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "blob:https://example.org/abc",
    "chrome://settings",
  ])("refuses %s", (hostile) => {
    expect(safeExternalUrl(hostile)).toBeNull();
  });

  it("refuses values that are not absolute URLs at all", () => {
    expect(safeExternalUrl("/relative/path")).toBeNull();
    expect(safeExternalUrl("not a url")).toBeNull();
    expect(safeExternalUrl("")).toBeNull();
    expect(safeExternalUrl("   ")).toBeNull();
  });

  it("refuses null and undefined", () => {
    expect(safeExternalUrl(null)).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
  });
});

describe("doiUrl", () => {
  it("resolves a bare DOI", () => {
    expect(doiUrl("10.1101/2026.01.01.000000")).toBe(
      "https://doi.org/10.1101/2026.01.01.000000",
    );
  });

  it("passes through an already-resolved DOI", () => {
    expect(doiUrl("https://doi.org/10.1234/abc")).toBe("https://doi.org/10.1234/abc");
  });

  it("refuses a DOI-shaped string carrying a hostile scheme", () => {
    expect(doiUrl("javascript:alert(1)")).toBeNull();
  });

  it("refuses something that is not a DOI", () => {
    expect(doiUrl("just some text")).toBeNull();
    expect(doiUrl("")).toBeNull();
    expect(doiUrl(null)).toBeNull();
  });
});
