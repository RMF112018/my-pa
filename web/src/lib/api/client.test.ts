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
    expect(result.code).toBeNull();
  });

  it("surfaces rate_limited by code without treating it as success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            errorClass: "unavailable",
            code: "rate_limited",
            message: "too many requests",
          },
        }),
        { status: 429 },
      ),
    );
    const result = await apiGet({ hasSession: true }, "/api/pulse");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(429);
    expect(result.errorClass).toBe("unavailable");
    expect(result.code).toBe("rate_limited");
    expect(result.data).toBeNull();
  });

  it("does not treat a 2xx array or unreadable body as success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    const arrayResult = await apiGet({ hasSession: true }, "/api/pulse");
    expect(arrayResult.ok).toBe(false);
    expect(arrayResult.code).toBe("upstream_contract_invalid");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("not-json", { status: 200 }));
    const unreadable = await apiGet({ hasSession: true }, "/api/pulse");
    expect(unreadable.ok).toBe(false);
    expect(unreadable.code).toBe("upstream_contract_invalid");
  });
});
