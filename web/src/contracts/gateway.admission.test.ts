// @vitest-environment node
/**
 * Structural lock: browser gateway.json admits the WP21 GoodNotes set and
 * does not admit GSQS start/status or the analyzer/orchestration verbs.
 */
import { describe, expect, it } from "vitest";
import contract from "@/contracts/gateway.json";

const WP21_BROWSER = [
  "goodnotes.notebooks.list",
  "goodnotes.pages.list",
  "goodnotes.runs.list",
  "goodnotes.read",
  "goodnotes.search",
  "goodnotes.correct",
  "goodnotes.work",
  "goodnotes.content",
] as const;

const NOT_BROWSER_ADMITTED = [
  "gsqs.start",
  "gsqs.status",
  "goodnotes.pull",
  "goodnotes.complete",
  "goodnotes.propose",
  "goodnotes.status",
] as const;

describe("gateway.json browser admission", () => {
  const admitted = Object.keys(contract.capabilities);

  it("does not admit GSQS start/status or GoodNotes pull/complete/propose/status", () => {
    for (const capability of NOT_BROWSER_ADMITTED) {
      expect(admitted, capability).not.toContain(capability);
    }
  });

  it("admits the WP21 browser GoodNotes set", () => {
    for (const capability of WP21_BROWSER) {
      expect(admitted).toContain(capability);
    }
  });
});
