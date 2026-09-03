// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCaptureCreate } from "./capture.create";

const DIGEST = "a".repeat(64);
const AT = "2026-08-09T12:00:00.000Z";

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    receipt_id: "rcpt_aaaaaaaa11111111",
    capture_id: "cap_aaaaaaaa11111111",
    version_id: "capver_aaaaaaaa11111111",
    version_number: 1,
    idempotency_key: "idem-1",
    content_sha256: DIGEST,
    issued_at: AT,
    created: true,
    ...overrides,
  };
}

describe("decodeCaptureCreate", () => {
  it("accepts a Python CaptureReceiptView", () => {
    const decoded = decodeCaptureCreate(receipt());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.receipt_id).toBe("rcpt_aaaaaaaa11111111");
      expect(decoded.value.version_number).toBe(1);
      expect(decoded.value.created).toBe(true);
    }
  });

  it("fails closed when receipt_id is missing", () => {
    const { receipt_id: _, ...rest } = receipt();
    expect(decodeCaptureCreate(rest).ok).toBe(false);
  });

  it("fails closed when receipt_id is the wrong type", () => {
    expect(decodeCaptureCreate(receipt({ receipt_id: 1 })).ok).toBe(false);
  });

  it("fails closed when version_number is below 1", () => {
    expect(decodeCaptureCreate(receipt({ version_number: 0 })).ok).toBe(false);
  });

  it("fails closed when content_sha256 is not 64 lowercase hex", () => {
    expect(decodeCaptureCreate(receipt({ content_sha256: "GG" + "a".repeat(62) })).ok).toBe(false);
    expect(decodeCaptureCreate(receipt({ content_sha256: "A".repeat(64) })).ok).toBe(false);
  });

  it("fails closed when created is omitted", () => {
    const { created: _, ...rest } = receipt();
    expect(decodeCaptureCreate(rest).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    const decoded = decodeCaptureCreate(receipt({ extra_receipt_field: "ignored" }));
    expect(decoded.ok).toBe(true);
  });
});
