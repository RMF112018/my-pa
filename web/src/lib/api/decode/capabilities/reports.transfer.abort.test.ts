// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsTransferAbort } from "./reports.transfer.abort";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.transfer.abort");

describe("reports.transfer.abort closed success (the _reports_transfer_abort handler)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsTransferAbort, canonical);
  });
  it("accepts a replay and is always the aborted state", () => {
    expect(decodeReportsTransferAbort({ ...canonical, replayed: true }).ok).toBe(true);
    expect(decodeReportsTransferAbort({ ...canonical, state: "open" }).ok).toBe(false);
  });
});
