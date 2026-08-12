import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost, apiGet, NoSessionError } from "@/lib/api/client";
import { CallerSuppliedPrincipalError } from "@/lib/auth/claims";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("principal-bound api client", () => {
  it("refuses to call without a session context", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await expect(apiPost({ hasSession: false }, "/api/capture", { text: "x" })).rejects.toThrow(
      NoSessionError,
    );
    await expect(apiGet({ hasSession: false }, "/api/pulse")).rejects.toThrow(NoSessionError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects payloads carrying identity fields before any network call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await expect(
      apiPost({ hasSession: true }, "/api/capture", { text: "x", oid: "spoof" }),
    ).rejects.toThrow(CallerSuppliedPrincipalError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("posts JSON with same-origin credentials when a session exists", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ receiptId: "rcpt-1" }), { status: 200 }));
    const result = await apiPost<{ receiptId: string }>({ hasSession: true }, "/api/capture", {
      text: "note",
    });
    expect(result.ok).toBe(true);
    expect(result.data?.receiptId).toBe("rcpt-1");
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/capture",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });

  it("surfaces error envelopes from failed responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "no valid session" } }), { status: 401 }),
    );
    const result = await apiGet({ hasSession: true }, "/api/pulse");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
    expect(result.error).toBe("no valid session");
  });
});
