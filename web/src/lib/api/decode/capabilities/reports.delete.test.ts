// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsDelete } from "./reports.delete";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.delete");
const receipt = canonical.receipt as Record<string, unknown>;

describe("reports.delete closed success (Python _general_lifecycle_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsDelete, canonical);
  });
  it("pins the operation to delete, at the top level and in the receipt", () => {
    expect(decodeReportsDelete({ ...canonical, operation: "archive" }).ok).toBe(false);
    expect(decodeReportsDelete({ ...canonical, receipt: { ...receipt, operation: "archive" } }).ok).toBe(false);
  });
  it("accepts a no_op without an event and refuses an unknown lifecycle state", () => {
    expect(decodeReportsDelete({ ...canonical, outcome: "no_op", event_id: null }).ok).toBe(true);
    expect(decodeReportsDelete({ ...canonical, lifecycle_state: "purged" }).ok).toBe(false);
    expect(decodeReportsDelete({ ...canonical, lifecycle_revision: -1 }).ok).toBe(false);
  });
});
