// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsTransferReadChunk } from "./reports.transfer.read_chunk";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.transfer.read_chunk");

describe("reports.transfer.read_chunk closed success (ApplicationService._transfer_read_range)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsTransferReadChunk, canonical);
  });
  it("accepts the last range, whose next offset is null", () => {
    expect(decodeReportsTransferReadChunk({ ...canonical, eof: true, next_offset: null }).ok).toBe(true);
  });
  it("refuses a chunk that is not canonical padded standard Base64", () => {
    for (const chunk of ["", "U3ludGhldGk", "U3ludGhldGk=\n", "U3ludGhl-GE=", "U3 ludGhldGk="]) {
      expect(decodeReportsTransferReadChunk({ ...canonical, chunk }).ok, JSON.stringify(chunk)).toBe(false);
    }
    expect(decodeReportsTransferReadChunk({ ...canonical, part: "encoded" }).ok).toBe(false);
  });
});
