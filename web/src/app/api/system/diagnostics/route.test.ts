// @vitest-environment node
/**
 * T03 / T04 / AC-52 / WP07-AC-056 — the single mutation owner, and what it refuses.
 *
 * These run against the real route with a real synthetic sign-in, so the
 * admission order being asserted is the one the shipped handler executes, not a
 * restatement of it. The cross-site and unauthenticated cases in particular
 * assert that **no `Set-Cookie` is produced**, because a refusal that still
 * wrote the preference would satisfy a status-code assertion and defeat the
 * whole control.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST as signInRoute, DELETE as signOutRoute } from "@/app/api/session/route";
import { POST as setDiagnostics } from "@/app/api/system/diagnostics/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";
import {
  DIAGNOSTICS_COOKIE,
  diagnosticsPrincipalBinding,
  parseDiagnosticsPreference,
} from "@/lib/diagnostics/preference";

const ORIGIN = "http://localhost:3000";
const SYNTHETIC_A_PRINCIPAL = "aaaa0001-0000-0000-0000-000000000001";

async function signIn(): Promise<string> {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
    }),
  );
  return (
    response as unknown as { cookies: { get(name: string): { value: string } } }
  ).cookies.get(SESSION_COOKIE_NAME).value;
}

function post(
  body: unknown,
  { cookie, origin = ORIGIN }: { cookie?: string; origin?: string | null } = {},
): NextRequest {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  const request = new NextRequest(`${ORIGIN}/api/system/diagnostics`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (cookie) request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

/** Every `Set-Cookie` the response carries, however many headers were appended. */
function setCookies(response: Response): string[] {
  const getter = response.headers as unknown as { getSetCookie?: () => string[] };
  if (typeof getter.getSetCookie === "function") return getter.getSetCookie();
  const raw = response.headers.get("set-cookie");
  return raw ? [raw] : [];
}

function diagnosticsCookie(response: Response): string | null {
  const header = setCookies(response).find((value) =>
    value.startsWith(`${DIAGNOSTICS_COOKIE}=`),
  );
  if (!header) return null;
  return header.slice(`${DIAGNOSTICS_COOKIE}=`.length).split(";")[0];
}

beforeEach(() => {
  resetSessionRegistry();
  // Unset `MYPA_SESSION_SERVICE_URL` couples the BFF to `MYPA_GATEWAY_URL`, so
  // sign-in needs an address even though the stub below answers it.
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubGlobal(
    "fetch",
    withSessionServiceFetch(async () => {
      throw new Error("no gateway call belongs in the diagnostics preference write");
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("POST /api/system/diagnostics — admission", () => {
  it.each([
    { name: "a foreign Origin", origin: "https://attacker.example" },
    { name: "a missing Origin", origin: null },
  ])("refuses $name and writes no preference", async ({ origin }) => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true }, { cookie, origin }));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(diagnosticsCookie(response)).toBeNull();
  });

  it("refuses an unauthenticated caller and writes no preference", async () => {
    const response = await setDiagnostics(post({ enabled: true }));
    expect(response.status).toBe(401);
    expect(diagnosticsCookie(response)).toBeNull();
  });

  it("refuses a malformed session SID and writes no preference", async () => {
    // Not 64 hex, so `parseOpaqueSessionSid` refuses it before the session
    // authority is ever consulted.
    //
    // A *dead* 64-hex SID is deliberately not asserted here: the shared
    // `withSessionServiceFetch` double answers `/sessions/resolve` with a live
    // principal for any well-formed SID, so a "dead SID is 401" assertion
    // against this harness would be measuring the double rather than the
    // route. That refusal lives in `lib/api/guard.ts` and is covered by
    // `guard.test.ts`, which can make the authority say no.
    const response = await setDiagnostics(post({ enabled: true }, { cookie: "not-a-valid-sid" }));
    expect(response.status).toBe(401);
    expect(diagnosticsCookie(response)).toBeNull();
  });
});

describe("POST /api/system/diagnostics — body vocabulary", () => {
  it.each([
    { name: "a string 'true'", body: { enabled: "true" } },
    { name: "a number", body: { enabled: 1 } },
    { name: "null", body: { enabled: null } },
    { name: "a missing field", body: {} },
  ])("refuses $name with 400 and writes no preference", async ({ body }) => {
    const cookie = await signIn();
    const response = await setDiagnostics(post(body, { cookie }));
    expect(response.status).toBe(400);
    expect(diagnosticsCookie(response)).toBeNull();
  });

  it("refuses an unknown field rather than silently ignoring it", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true, scope: "global" }, { cookie }));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "unsupported_field" } });
    expect(diagnosticsCookie(response)).toBeNull();
  });

  it("refuses a caller-supplied principal", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(
      post({ enabled: true, principalId: "someone-else" }, { cookie }),
    );
    expect(response.status).toBe(400);
    expect(diagnosticsCookie(response)).toBeNull();
  });

  it("refuses a non-JSON body", async () => {
    const cookie = await signIn();
    const request = new NextRequest(`${ORIGIN}/api/system/diagnostics`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: "not json",
    });
    request.cookies.set(SESSION_COOKIE_NAME, cookie);
    const response = await setDiagnostics(request);
    expect(response.status).toBe(400);
    expect(diagnosticsCookie(response)).toBeNull();
  });
});

describe("POST /api/system/diagnostics — accepted writes", () => {
  it("writes an ON value that parses for this principal", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true }, { cookie }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ enabled: true });

    const value = diagnosticsCookie(response);
    expect(value).not.toBeNull();
    const binding = await diagnosticsPrincipalBinding(SYNTHETIC_A_PRINCIPAL);
    expect(parseDiagnosticsPreference(value, binding)).toBe(true);
  });

  it("writes an OFF value that parses as OFF", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: false }, { cookie }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ enabled: false });

    const binding = await diagnosticsPrincipalBinding(SYNTHETIC_A_PRINCIPAL);
    expect(parseDiagnosticsPreference(diagnosticsCookie(response), binding)).toBe(false);
  });

  it("writes an HttpOnly, SameSite=Lax, Path=/ cookie", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true }, { cookie }));
    const header = setCookies(response).find((value) =>
      value.startsWith(`${DIAGNOSTICS_COOKIE}=`),
    );
    expect(header).toContain("HttpOnly");
    expect(header).toContain("SameSite=Lax");
    expect(header).toContain("Path=/");
  });

  it("is private and never cached", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true }, { cookie }));
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("never returns the raw principal id or the binding input", async () => {
    const cookie = await signIn();
    const response = await setDiagnostics(post({ enabled: true }, { cookie }));
    const payload = JSON.stringify(await response.json());
    expect(payload).not.toContain(SYNTHETIC_A_PRINCIPAL);
  });
});

describe("sign-out clears the preference", () => {
  it("expires the diagnostics cookie when the session is torn down", async () => {
    const cookie = await signIn();
    await setDiagnostics(post({ enabled: true }, { cookie }));

    const request = new NextRequest(`${ORIGIN}/api/session`, {
      method: "DELETE",
      headers: { origin: ORIGIN },
    });
    request.cookies.set(SESSION_COOKIE_NAME, cookie);
    const response = await signOutRoute(request);
    expect(response.status).toBe(200);

    const header = setCookies(response).find((value) =>
      value.startsWith(`${DIAGNOSTICS_COOKIE}=`),
    );
    expect(header).toBeDefined();
    expect(header).toContain("Max-Age=0");
  });
});
