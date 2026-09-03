// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksBulkConfirm } from "./tasks.bulk_confirm";

function confirm(overrides: Record<string, unknown> = {}) {
  return {
    bulk_operation_id: "blk_aaaaaaaa11111111",
    affected: 2,
    no_op: 1,
    rejected: 0,
    history_ids: ["thst_aaaaaaaa11111111", "thst_bbbbbbbb22222222"],
    replayed: false,
    ...overrides,
  };
}

describe("decodeTasksBulkConfirm", () => {
  it("accepts a Python bulk confirm receipt", () => {
    const decoded = decodeTasksBulkConfirm(confirm());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.history_ids).toHaveLength(2);
  });

  it("fails closed when history_ids is omitted rather than treating omit as []", () => {
    const { history_ids: _, ...rest } = confirm();
    expect(decodeTasksBulkConfirm(rest).ok).toBe(false);
  });

  it("accepts an empty history_ids array when the handler published one", () => {
    const decoded = decodeTasksBulkConfirm(confirm({ history_ids: [] }));
    expect(decoded.ok).toBe(true);
  });

  it("fails closed when history_ids is the wrong type", () => {
    expect(decodeTasksBulkConfirm(confirm({ history_ids: "thst_aaaaaaaa11111111" })).ok).toBe(
      false,
    );
  });

  it("fails closed when bulk_operation_id is missing", () => {
    const { bulk_operation_id: _, ...rest } = confirm();
    expect(decodeTasksBulkConfirm(rest).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = confirm();
    expect(decodeTasksBulkConfirm(rest).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksBulkConfirm(confirm({ extra_confirm_field: 1 })).ok).toBe(true);
  });
});
