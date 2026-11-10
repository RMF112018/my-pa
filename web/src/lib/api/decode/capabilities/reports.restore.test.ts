// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsRestore } from "./reports.restore";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.restore");
const receipt = canonical.receipt as Record<string, unknown>;

describe("reports.restore closed success (Python _general_lifecycle_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsRestore, canonical);
  });
  it("pins the operation to restore, at the top level and in the receipt", () => {
    expect(decodeReportsRestore({ ...canonical, operation: "archive" }).ok).toBe(false);
    expect(decodeReportsRestore({ ...canonical, receipt: { ...receipt, operation: "archive" } }).ok).toBe(false);
  });
  it("accepts a no_op without an event and refuses an unknown lifecycle state", () => {
    expect(decodeReportsRestore({ ...canonical, outcome: "no_op", event_id: null }).ok).toBe(true);
    expect(decodeReportsRestore({ ...canonical, lifecycle_state: "purged" }).ok).toBe(false);
    expect(decodeReportsRestore({ ...canonical, lifecycle_revision: -1 }).ok).toBe(false);
  });
});
