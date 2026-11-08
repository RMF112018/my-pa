// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsTransferAppend } from "./reports.transfer.append";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.transfer.append");

describe("reports.transfer.append closed success (Python _transfer_append_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsTransferAppend, canonical);
  });
  it("accepts the last chunk, whose next sequence is null", () => {
    expect(
      decodeReportsTransferAppend({ ...canonical, complete: true, next_sequence: null, replayed: true }).ok,
    ).toBe(true);
    expect(decodeReportsTransferAppend({ ...canonical, next_sequence: -1 }).ok).toBe(false);
  });
});
