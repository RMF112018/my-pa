// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsTransferBegin } from "./reports.transfer.begin";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.transfer.begin");

describe("reports.transfer.begin closed success (Python _transfer_begin_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsTransferBegin, canonical);
  });
  it("is always the begin's own state, open, and a grxfr_ session", () => {
    expect(decodeReportsTransferBegin({ ...canonical, state: "finalized" }).ok).toBe(false);
    expect(decodeReportsTransferBegin({ ...canonical, session_id: "grpt_aaaaaaaa11111111" }).ok).toBe(false);
    expect(decodeReportsTransferBegin({ ...canonical, encoding: "gzip+base64", replayed: true }).ok).toBe(true);
    expect(decodeReportsTransferBegin({ ...canonical, chunk_byte_limit: 0 }).ok).toBe(false);
  });
});
