import { describe, expect, it } from "vitest";

import { safeHref } from "@/lib/http/safe-href";

describe("safeHref", () => {
  it("admits https URLs and root-relative paths", () => {
    expect(safeHref("https://example.test/evidence")).toBe("https://example.test/evidence");
    expect(safeHref("/knowledge/record-1")).toBe("/knowledge/record-1");
  });

  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    " javascript:alert(1)",
    "data:text/html,unsafe",
    "vbscript:msgbox(1)",
    "//evil.example",
    "//evil.example/path",
    "///evil",
    "http://example.test/x",
    "http://https.example.test/x",
    "mailto:synthetic@example.test",
    "tel:+15555550100",
  ])("rejects %j", (href) => {
    expect(safeHref(href)).toBeNull();
  });
});
