/**
 * requirePrincipal distinguishes unauthenticated (401) from unavailable (503).
 * A missing session-service secret is never 401.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { callSessionService } from "@/lib/auth/session-service";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    callSessionService: vi.fn(),
  };
});

const SID = "ab".repeat(32);

const PRINCIPAL = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const mockedCall = vi.mocked(callSessionService);

function requestWithCookie(cookie?: string): NextRequest {
  const request = new NextRequest("http://localhost:3000/api/pulse");
  if (cookie) request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

beforeEach(() => {
  mockedCall.mockReset();
});

describe("requirePrincipal", () => {
  it("returns 401 when there is no valid session", async () => {
    const missing = await requirePrincipal(requestWithCookie());
    expect(missing.ok).toBe(false);
    if (missing.ok) return;
    expect(missing.response.status).toBe(401);
    await expect(missing.response.json()).resolves.toMatchObject({
      error: { code: "unauthenticated", message: "no valid session" },
    });

    mockedCall.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: "unauthenticated" } }), { status: 401 }),
    );
    const dead = await requirePrincipal(requestWithCookie(SID));
    expect(dead.ok).toBe(false);
    if (dead.ok) return;
    expect(dead.response.status).toBe(401);
  });

  it("returns 401 for an HMAC payload.sig cookie, not 503", async () => {
    const hmac = "eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef";
    const refused = await requirePrincipal(requestWithCookie(hmac));
    expect(refused.ok).toBe(false);
    if (refused.ok) return;
    expect(refused.response.status).toBe(401);
    expect(mockedCall).not.toHaveBeenCalled();
  });

  it("returns 503 authority_unavailable when the session-service cannot answer", async () => {
    mockedCall.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: "authority_unavailable" } }), { status: 503 }),
    );
    const down = await requirePrincipal(requestWithCookie(SID));
    expect(down.ok).toBe(false);
    if (down.ok) return;
    expect(down.response.status).toBe(503);
    await expect(down.response.json()).resolves.toMatchObject({
      error: { code: "authority_unavailable", message: "session authority unavailable" },
    });
  });

  it("returns 503 when the local service secret is missing, not 401", async () => {
    mockedCall.mockRejectedValueOnce(
      Object.assign(new Error("missing secret"), { name: "MissingSessionServiceSecretError" }),
    );
    const missingSecret = await requirePrincipal(requestWithCookie(SID));
    expect(missingSecret.ok).toBe(false);
    if (missingSecret.ok) return;
    expect(missingSecret.response.status).toBe(503);
    await expect(missingSecret.response.json()).resolves.toMatchObject({
      error: { code: "authority_unavailable" },
    });
  });

  it("returns the principal when the session-service resolves it", async () => {
    mockedCall.mockResolvedValueOnce(
      new Response(JSON.stringify({ principal: PRINCIPAL }), { status: 200 }),
    );
    const guarded = await requirePrincipal(requestWithCookie(SID));
    expect(guarded.ok).toBe(true);
    if (!guarded.ok) return;
    expect(guarded.principal.principalId).toBe(PRINCIPAL.principalId);
  });
});
