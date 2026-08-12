import { describe, expect, it } from "vitest";
import { CaptureAdmissionStore } from "@/lib/capture/idempotency";

const PRINCIPAL_A = "prn_aaaa0001aaaaaaaaaaaaaaaa00000001";
const PRINCIPAL_B = "prn_bbbb0002bbbbbbbbbbbbbbbb00000002";
const NOTE = "SENTINEL capture text that must never appear in a receipt";

describe("per-principal capture admission (ADR-005, PKL-MYPA-D-WP03-001)", () => {
  it("replays the original receipt for the same principal, key, and content", () => {
    const store = new CaptureAdmissionStore();
    const first = store.admit(PRINCIPAL_A, "key-1", NOTE);
    const replay = store.admit(PRINCIPAL_A, "key-1", NOTE);
    if (!first.ok || !replay.ok) throw new Error("expected both admissions to succeed");
    expect(first.receipt.created).toBe(true);
    expect(replay.receipt.created).toBe(false);
    expect(replay.receipt.receiptId).toBe(first.receipt.receiptId);
  });

  it("scopes the idempotency key to the principal — two principals, same key, two captures", () => {
    const store = new CaptureAdmissionStore();
    const a = store.admit(PRINCIPAL_A, "shared-key", NOTE);
    const b = store.admit(PRINCIPAL_B, "shared-key", NOTE);
    if (!a.ok || !b.ok) throw new Error("expected both admissions to succeed");
    expect(a.receipt.created).toBe(true);
    expect(b.receipt.created).toBe(true);
    expect(b.receipt.receiptId).not.toBe(a.receipt.receiptId);
  });

  it("refuses the same key with different content as a conflict, never an overwrite", () => {
    const store = new CaptureAdmissionStore();
    const first = store.admit(PRINCIPAL_A, "key-1", NOTE);
    const conflict = store.admit(PRINCIPAL_A, "key-1", "different content, same key");
    if (!first.ok) throw new Error("expected the first admission to succeed");
    expect(conflict.ok).toBe(false);
    // The original admission survives the refused attempt untouched.
    const replay = store.admit(PRINCIPAL_A, "key-1", NOTE);
    if (!replay.ok) throw new Error("expected the replay to succeed");
    expect(replay.receipt.receiptId).toBe(first.receipt.receiptId);
    expect(replay.receipt.created).toBe(false);
  });

  it("holds no capture text: receipts and the store's own state omit it (QC-AC-041)", () => {
    const store = new CaptureAdmissionStore();
    const outcome = store.admit(PRINCIPAL_A, "key-1", NOTE);
    if (!outcome.ok) throw new Error("expected the admission to succeed");
    expect(JSON.stringify(outcome)).not.toContain("SENTINEL");
    // Inspect the store's internal state the way an attacker with a heap
    // dump would: serialize everything reachable and scan for the text.
    const internals = JSON.stringify(store, (_key, value) =>
      value instanceof Map ? Object.fromEntries(value) : (value as unknown),
    );
    expect(internals).not.toContain("SENTINEL");
  });
});
