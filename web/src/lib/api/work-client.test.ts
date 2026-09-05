import { afterEach, describe, expect, it, vi } from "vitest";
import { browserWorkClock, captureEvidence, createAttemptKey, isDefinitiveAttemptFailure, requiredCollection, workRequest } from "@/lib/api/work-client";

afterEach(() => vi.unstubAllGlobals());

describe("Work browser client", () => {
  it("does not treat a synthetic capture acknowledgement as durable evidence", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ status: "acknowledged_not_persisted" }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(captureEvidence("synthetic note", "task-origin")).rejects.toThrow(/not durably persisted/);
  });

  it("keeps conflict distinct for deliberate refetch and reapply", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ error: { code: "conflict", message: "version changed" } }), { status: 409, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(workRequest("/api/tasks/tsk_aaaaaaaa11111111")).rejects.toMatchObject({
      status: 409,
      code: "conflict",
    });
  });

  it("does not treat unreadable 2xx JSON as an empty success object", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response("not-json", { status: 200, headers: { "content-type": "text/html" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(workRequest("/api/tasks")).rejects.toMatchObject({
      status: 503,
      code: "upstream_contract_invalid",
    });
  });

  it("does not treat a missing required collection as empty", () => {
    expect(() => requiredCollection(undefined, "tasks")).toThrow(/tasks collection was missing/);
    expect(requiredCollection([], "tasks")).toEqual([]);
  });

  it("produces an ISO work date from a validated browser IANA timezone", () => {
    const clock = browserWorkClock(new Date("2026-08-21T12:00:00Z"));
    expect(clock.workDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(() => new Intl.DateTimeFormat("en", { timeZone: clock.timezone })).not.toThrow();
  });

  it("reuses the exact key after a lost response and rotates for material request change", async () => {
    const attempt = createAttemptKey("task-create");
    const original = { title: "Call Sam", priority: "p2" };
    const first = attempt.forPayload(original);
    expect(attempt.forPayload(original)).toBe(first);
    expect(attempt.forPayload({ ...original, priority: "p1" })).not.toBe(first);
  });

  it("retries an ambiguous capture failure with the same idempotency key", async () => {
    const bodies: Array<{ idempotencyKey: string }> = [];
    const fetchMock = vi.fn<typeof fetch>(async (_path, init) => {
      bodies.push(JSON.parse(String(init?.body)));
      if (bodies.length === 1) throw new TypeError("response lost");
      return new Response(JSON.stringify({ status: "persisted", receipt: { captureId: "cap_aaaaaaaa11111111" } }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const attempt = createAttemptKey("task-origin"); const material = { note: "Called Sam" };
    await expect(captureEvidence(material.note, "task-origin", attempt.forPayload(material))).rejects.toThrow();
    await expect(captureEvidence(material.note, "task-origin", attempt.forPayload(material))).resolves.toBe("cap_aaaaaaaa11111111");
    expect(bodies[0]?.idempotencyKey).toBe(bodies[1]?.idempotencyKey);
  });

  it.each([502, 503, 504])("retains the key for retryable HTTP %s", (status) => {
    const attempt = createAttemptKey("task-update"); const payload = { title: "Retain me" };
    const original = attempt.forPayload(payload);
    expect(isDefinitiveAttemptFailure({ status })).toBe(false);
    expect(attempt.forPayload(payload)).toBe(original);
  });

  it("rotates after a definitive error but not a network error", () => {
    const attempt = createAttemptKey("task-update"); const payload = { title: "Rotate me" }; const original = attempt.forPayload(payload);
    expect(isDefinitiveAttemptFailure(new TypeError("offline"))).toBe(false); expect(attempt.forPayload(payload)).toBe(original);
    expect(isDefinitiveAttemptFailure({ status: 400 })).toBe(true); attempt.succeeded(); expect(attempt.forPayload(payload)).not.toBe(original);
  });
});
