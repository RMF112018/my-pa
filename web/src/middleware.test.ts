/**
 * Middleware guard behavior — unauthenticated requests never reach app
 * routes. Uses real NextRequest objects against the exported middleware.
 */
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "@/middleware";
import { encodeSession, SESSION_COOKIE_NAME } from "@/lib/auth/session";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

function requestFor(path: string, cookie?: string): NextRequest {
  const request = new NextRequest(`http://localhost:3000${path}`);
  if (cookie) request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

describe("route guard middleware", () => {
  it("redirects unauthenticated page requests to /sign-in", async () => {
    const response = await middleware(requestFor("/today"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/sign-in");
  });

  it("rejects a forged session cookie", async () => {
    const response = await middleware(requestFor("/today", "forged.token"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/sign-in");
  });

  it("returns 401 JSON for unauthenticated API requests", async () => {
    const response = await middleware(requestFor("/api/pulse"));
    expect(response.status).toBe(401);
  });

  it("lets a valid session through", async () => {
    const token = await encodeSession(PRINCIPAL);
    const response = await middleware(requestFor("/today", token));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("leaves /sign-in and /api/session unguarded", async () => {
    expect((await middleware(requestFor("/sign-in"))).status).toBe(200);
    expect((await middleware(requestFor("/api/session"))).status).toBe(200);
  });
});
