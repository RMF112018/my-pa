/**
 * Middleware guard behavior — unauthenticated requests never reach app
 * routes. Cookie authority at the Edge is charset/length only.
 */
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "@/middleware";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { safeReturnPath } from "@/lib/auth/return-path";

const SID = "ab".repeat(32);

function requestFor(path: string, cookie?: string): NextRequest {
  const request = new NextRequest(`http://localhost:3000${path}`);
  if (cookie) request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

describe("route guard middleware", () => {
  it("redirects unauthenticated page requests to /sign-in?next=/today", async () => {
    const response = await middleware(requestFor("/today"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/sign-in");
    expect(location.searchParams.get("next")).toBe("/today");
  });

  it("copies a validated path+search onto next", async () => {
    const response = await middleware(requestFor("/work?x=1"));
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.searchParams.get("next")).toBe("/work?x=1");
  });

  it("rejects a forged, short, or non-hex cookie", async () => {
    for (const cookie of ["forged.token", "short", "gg".repeat(32), "ab".repeat(16)]) {
      const response = await middleware(requestFor("/today", cookie));
      expect(response.status).toBe(307);
      const location = new URL(response.headers.get("location") ?? "");
      expect(location.pathname).toBe("/sign-in");
      expect(location.searchParams.get("next")).toBe("/today");
    }
  });

  it("returns 401 JSON for unauthenticated API requests without a next param", async () => {
    const response = await middleware(requestFor("/api/pulse"));
    expect(response.status).toBe(401);
    expect(response.headers.get("location")).toBeNull();
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "unauthenticated" },
    });
  });

  it("lets a valid 64-hex cookie through", async () => {
    const response = await middleware(requestFor("/today", SID));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("lets an uppercase 64-hex cookie through", async () => {
    const response = await middleware(requestFor("/today", SID.toUpperCase()));
    expect(response.status).toBe(200);
  });

  it("leaves /sign-in and /api/session unguarded", async () => {
    expect((await middleware(requestFor("/sign-in"))).status).toBe(200);
    expect((await middleware(requestFor("/api/session"))).status).toBe(200);
  });

  it("does not plant an absolute URL as next; the request path is relative", async () => {
    const response = await middleware(requestFor("/today", "https://evil.example"));
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.searchParams.get("next")).toBe("/today");
    expect(safeReturnPath(location.searchParams.get("next"))).toBe("/today");
  });
});

describe("safeReturnPath rejects open redirects", () => {
  it("refuses absolute, protocol-relative, javascript, and backslash paths", () => {
    expect(safeReturnPath("https://evil.example")).toBeNull();
    expect(safeReturnPath("//evil")).toBeNull();
    expect(safeReturnPath("javascript:alert(1)")).toBeNull();
    expect(safeReturnPath("/\\evil")).toBeNull();
  });
});
