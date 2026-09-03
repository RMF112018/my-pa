// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksBulkPreview } from "./tasks.bulk_preview";

function preview(overrides: Record<string, unknown> = {}) {
  return {
    bulk_operation_id: "blk_aaaaaaaa11111111",
    expires_at: "2026-08-09T12:15:00.000Z",
    affected: 2,
    no_op: 1,
    rejected: 0,
    replayed: false,
    ...overrides,
  };
}

describe("decodeTasksBulkPreview", () => {
  it("accepts a Python bulk preview receipt", () => {
    const decoded = decodeTasksBulkPreview(preview());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.bulk_operation_id).toBe("blk_aaaaaaaa11111111");
  });

  it("fails closed when bulk_operation_id is missing rather than inventing one", () => {
    const { bulk_operation_id: _, ...rest } = preview();
    expect(decodeTasksBulkPreview(rest).ok).toBe(false);
  });

  it("fails closed when affected is the wrong type", () => {
    expect(decodeTasksBulkPreview(preview({ affected: "2" })).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = preview();
    expect(decodeTasksBulkPreview(rest).ok).toBe(false);
  });

  it("fails closed when expires_at is omitted", () => {
    const { expires_at: _, ...rest } = preview();
    expect(decodeTasksBulkPreview(rest).ok).toBe(false);
  });

  it("fails closed when rejected is negative", () => {
    expect(decodeTasksBulkPreview(preview({ rejected: -1 })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksBulkPreview(preview({ extra_preview_field: true })).ok).toBe(true);
  });
});
