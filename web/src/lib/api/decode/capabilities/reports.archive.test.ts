// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsArchive } from "./reports.archive";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.archive");
const receipt = canonical.receipt as Record<string, unknown>;

describe("reports.archive closed success (Python _general_lifecycle_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsArchive, canonical);
  });
  it("pins the operation to archive, at the top level and in the receipt", () => {
    expect(decodeReportsArchive({ ...canonical, operation: "delete" }).ok).toBe(false);
    expect(decodeReportsArchive({ ...canonical, receipt: { ...receipt, operation: "delete" } }).ok).toBe(false);
  });
  it("accepts a no_op without an event and refuses an unknown lifecycle state", () => {
    expect(decodeReportsArchive({ ...canonical, outcome: "no_op", event_id: null }).ok).toBe(true);
    expect(decodeReportsArchive({ ...canonical, lifecycle_state: "purged" }).ok).toBe(false);
    expect(decodeReportsArchive({ ...canonical, lifecycle_revision: -1 }).ok).toBe(false);
  });
});
