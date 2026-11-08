// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsTransferFinalize } from "./reports.transfer.finalize";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const canonical = canonicalFixture("reports.transfer.finalize");

describe("reports.transfer.finalize closed success (Python _transfer_finalize_payload)", () => {
  it("accepts the committed fixture and refuses every malformed variant", () => {
    expectClosedContract(decodeReportsTransferFinalize, canonical);
  });
  it("decodes content_token as an opaque grxtk_ string and never echoes it", () => {
    const decoded = decodeReportsTransferFinalize(canonical);
    expect(decoded.ok && decoded.value.content_token).toMatch(/^grxtk_[0-9a-f]{64}$/);
    const token = `grxtk_${"f".repeat(64)}`;
    for (const wrong of [
      token.toUpperCase(),
      `${token}0`,
      token.slice(0, -1),
      `grxfr_${"f".repeat(64)}`,
      `${token}\n`,
      `grxtk_${"g".repeat(64)}`,
    ]) {
      const refused = decodeReportsTransferFinalize({ ...canonical, content_token: wrong });
      expect(refused.ok).toBe(false);
      expect(JSON.stringify(refused)).not.toContain("f".repeat(16));
    }
  });
  it("is always the finalized state", () => {
    expect(decodeReportsTransferFinalize({ ...canonical, state: "consumed" }).ok).toBe(false);
  });
});
