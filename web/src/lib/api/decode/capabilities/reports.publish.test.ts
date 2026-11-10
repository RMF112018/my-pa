// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsPublish } from "./reports.publish";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.publish");

describe("reports.publish closed success (Python _general_publish_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsPublish, canonical);
  });
  it("is the standalone plane only", () => {
    expect(decodeReportsPublish({ ...canonical, plane: "intelligence" }).ok).toBe(false);
    expect(decodeReportsPublish({ ...canonical, report_id: "rpt_aaaaaaaa11111111" }).ok).toBe(false);
  });
  it("accepts a canonical digest for json content and a replay", () => {
    const content = { ...(canonical.content as Record<string, unknown>), format: "json", canonical_sha256: "b".repeat(64) };
    expect(decodeReportsPublish({ ...canonical, content, replayed: true }).ok).toBe(true);
    expect(decodeReportsPublish({ ...canonical, version_number: 0 }).ok).toBe(false);
  });
});
