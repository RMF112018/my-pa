// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsUpdate } from "./reports.update";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.update");
const receipt = canonical.receipt as Record<string, unknown>;

describe("reports.update closed success (Python _general_update_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsUpdate, canonical);
  });
  it("accepts a no_op answer, which has no change kind", () => {
    const noOp = { ...canonical, outcome: "no_op", change_kind: null, receipt: { ...receipt, outcome: "no_op" } };
    expect(decodeReportsUpdate(noOp).ok).toBe(true);
  });
  it("pins the receipt operation and the identifier kinds", () => {
    expect(decodeReportsUpdate({ ...canonical, receipt: { ...receipt, operation: "publish" } }).ok).toBe(false);
    expect(decodeReportsUpdate({ ...canonical, receipt: { ...receipt, audit_id: "corr_aaaaaaaa11111111" } }).ok).toBe(false);
    expect(decodeReportsUpdate({ ...canonical, change_kind: "initial_v2" }).ok).toBe(false);
  });
});
