/**
 * The session lifecycle, against the real route handlers.
 *
 * Python AuthSessionStore is the authority. These tests mock the session-service
 * HTTP helpers and keep the route behaviour honest: the cookie is a raw 64-hex
 * SID, browser JSON never carries `issuedSid`, and the *exact same cookie value*
 * that worked before `DELETE` is refused afterwards.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST, DELETE, GET } from "@/app/api/session/route";
import { GET as pulse } from "@/app/api/pulse/route";
import { SESSION_COOKIE_NAME, sessionReplayBinding } from "@/lib/auth/session";
import {
  issueSyntheticSession,
  revokeSid,
  callSessionService,
  MissingSessionServiceSecretError,
} from "@/lib/auth/session-service";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";
import type { PrincipalSession } from "@/contracts/identity";
import type { SyntheticSessionKey } from "@/lib/auth/session-service";

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    issueSyntheticSession: vi.fn(),
    revokeSid: vi.fn(),
    callSessionService: vi.fn(),
  };
});

const ORIGIN = "http://localhost:3000";
const HMAC_SHAPED = "eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef";

const PRINCIPAL_A: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: SYNTHETIC_MOSS_TENANT_ID,
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
  authenticationProvider: "synthetic",
};

const PRINCIPAL_B: PrincipalSession = {
  principalId: "syn-bbbb0002",
  tid: SYNTHETIC_MOSS_TENANT_ID,
  oid: "bbbb0002-0000-0000-0000-000000000002",
  upn: "synthetic.b@moss.example",
  displayName: "Synthetic B",
  lifecycleState: "active",
  synthetic: true,
  authenticationProvider: "synthetic",
};

const mockedIssue = vi.mocked(issueSyntheticSession);
const mockedRevoke = vi.mocked(revokeSid);
const mockedCall = vi.mocked(callSessionService);

const live = new Map<string, PrincipalSession>();
let sidSeq = 0;

function nextSid(): string {
  sidSeq += 1;
  return sidSeq.toString(16).padStart(64, "0");
}

function principalFor(key: SyntheticSessionKey): PrincipalSession {
  return key === "synthetic-b" ? PRINCIPAL_B : PRINCIPAL_A;
}

function signInRequest(
  key: unknown,
  init: { origin?: string | null; fetchSite?: string | null; body?: unknown; cookie?: string } = {},
): NextRequest {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const origin = init.origin === undefined ? ORIGIN : init.origin;
  if (origin !== null) headers["origin"] = origin;
  if (init.fetchSite != null) headers["sec-fetch-site"] = init.fetchSite;
  const request = new NextRequest(`${ORIGIN}/api/session`, {
    method: "POST",
    headers,
    body: JSON.stringify(init.body ?? { syntheticPrincipal: key }),
  });
  if (init.cookie) request.cookies.set(SESSION_COOKIE_NAME, init.cookie);
  return request;
}

function signOutRequest(cookie?: string, origin: string | null = ORIGIN): NextRequest {
  const headers: Record<string, string> = {};
  if (origin !== null) headers["origin"] = origin;
  const request = new NextRequest(`${ORIGIN}/api/session`, { method: "DELETE", headers });
  if (cookie) request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

function protectedRequest(cookie: string): NextRequest {
  const request = new NextRequest(`${ORIGIN}/api/pulse`);
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

function sessionGetRequest(cookie: string): NextRequest {
  const request = new NextRequest(`${ORIGIN}/api/session`);
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

/** The cookie value a sign-in response sets. */
function issuedCookie(response: Response): string {
  const value = (response as unknown as { cookies: { get(name: string): { value: string } | undefined } }).cookies.get(
    SESSION_COOKIE_NAME,
  );
  expect(value).toBeDefined();
  return value!.value;
}

function expectOpaqueSid(cookie: string): void {
  expect(cookie).toMatch(/^[0-9a-f]{64}$/);
  expect(cookie).not.toContain(".");
}

async function signIn(key: SyntheticSessionKey = "synthetic-a", cookie?: string): Promise<string> {
  const response = await POST(signInRequest(key, { cookie }));
  expect(response.status).toBe(200);
  const issued = issuedCookie(response);
  expectOpaqueSid(issued);
  return issued;
}

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
  live.clear();
  sidSeq = 0;
  mockedIssue.mockImplementation(async (key) => {
    const issuedSid = nextSid();
    const principal = principalFor(key);
    live.set(issuedSid, principal);
    return { issuedSid, principal };
  });
  mockedRevoke.mockImplementation(async (sid) => {
    if (!live.has(sid)) return false;
    live.delete(sid);
    return true;
  });
  mockedCall.mockImplementation(async (action, body) => {
    if (action === "sessions/touch" || action === "sessions/resolve") {
      const sid = typeof body.sid === "string" ? body.sid : "";
      const principal = live.get(sid);
      if (!principal) {
        return new Response(JSON.stringify({ error: { code: "unauthenticated" } }), { status: 401 });
      }
      return new Response(JSON.stringify({ principal }), { status: 200 });
    }
    return new Response(JSON.stringify({ error: { code: "invalid_request" } }), { status: 400 });
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("sign-in", () => {
  it("mints a session for a known synthetic principal", async () => {
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ signedIn: true });
    expect(body).not.toHaveProperty("issuedSid");
    const cookie = issuedCookie(response);
    expectOpaqueSid(cookie);
    expect(cookie).not.toBe(HMAC_SHAPED);
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);
  });

  it("sets a 64-hex SID cookie, not an HMAC token", async () => {
    const cookie = await signIn();
    expect(cookie).toMatch(/^[0-9a-f]{64}$/);
    expect(cookie.split(".")).toHaveLength(1);
  });

  it("never returns issuedSid in the browser JSON", async () => {
    const issuedSid = "ab".repeat(32);
    mockedIssue.mockImplementationOnce(async (key) => {
      const principal = principalFor(key);
      live.set(issuedSid, principal);
      return { issuedSid, principal };
    });
    const response = await POST(signInRequest("synthetic-a"));
    const text = JSON.stringify(await response.json());
    expect(text).not.toContain("issuedSid");
    expect(text).not.toContain(issuedSid);
  });

  it("refuses an unknown principal key", async () => {
    expect((await POST(signInRequest("synthetic-z"))).status).toBe(400);
  });

  it("refuses a body carrying caller-supplied identity", async () => {
    for (const body of [
      { syntheticPrincipal: "synthetic-a", principalId: "syn-forged" },
      { syntheticPrincipal: "synthetic-a", tid: SYNTHETIC_MOSS_TENANT_ID },
      { syntheticPrincipal: "synthetic-a", nested: { oid: "aaaa0001-0000-0000-0000-000000000001" } },
    ]) {
      const response = await POST(signInRequest(undefined, { body }));
      expect(response.status).toBe(400);
      expect((await response.json()).error.code).toBe("caller_supplied_principal");
    }
  });

  it("revokes only the prior cookie SID, so a carried session cannot survive sign-in", async () => {
    const first = await signIn();
    expect((await pulse(protectedRequest(first))).status).toBe(200);

    const second = await signIn("synthetic-a", first);
    expect(second).not.toBe(first);
    expect((await pulse(protectedRequest(second))).status).toBe(200);
    expect((await pulse(protectedRequest(first))).status).toBe(401);
  });

  it("does not revoke other live SIDs for the same principal when no prior cookie is sent", async () => {
    const first = await signIn();
    const second = await signIn();
    expect(second).not.toBe(first);
    expect((await pulse(protectedRequest(first))).status).toBe(200);
    expect((await pulse(protectedRequest(second))).status).toBe(200);
  });

  it("does not revoke a different principal's session", async () => {
    const a = await signIn("synthetic-a");
    const b = await signIn("synthetic-b");
    expect((await pulse(protectedRequest(a))).status).toBe(200);
    expect((await pulse(protectedRequest(b))).status).toBe(200);
  });

  it("resolves two synthetic principals to two distinct identities", async () => {
    const a = await signIn("synthetic-a");
    const b = await signIn("synthetic-b");
    const first = await (await pulse(protectedRequest(a))).json();
    const second = await (await pulse(protectedRequest(b))).json();
    const owners = (items: { principalId?: string }[]) =>
      new Set(items.map((item) => item.principalId));
    expect(owners(first.items)).not.toEqual(owners(second.items));
    for (const owner of owners(first.items)) {
      expect(owners(second.items).has(owner)).toBe(false);
    }
  });

  it("does not fail sign-in when prior SID revoke returns false", async () => {
    const first = await signIn();
    mockedRevoke.mockResolvedValueOnce(false);
    const response = await POST(signInRequest("synthetic-a", { cookie: first }));
    expect(response.status).toBe(200);
    expectOpaqueSid(issuedCookie(response));
  });
});

describe("sign-out revokes server-side", () => {
  it("refuses a replay of the exact same cookie value after sign-out", async () => {
    const cookie = await signIn();
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);

    const out = await DELETE(signOutRequest(cookie));
    expect(out.status).toBe(200);

    expect((await pulse(protectedRequest(cookie))).status).toBe(401);
    expect((await GET(sessionGetRequest(cookie))).status).toBe(401);
  });

  it("clears the cookie as well, which is the tidy half rather than the control", async () => {
    const cookie = await signIn();
    const out = await DELETE(signOutRequest(cookie));
    const cleared = (out as unknown as { cookies: { get(n: string): { value: string } | undefined } }).cookies.get(
      SESSION_COOKIE_NAME,
    );
    expect(cleared?.value).toBe("");
  });

  it("is safe with no cookie at all", async () => {
    expect((await DELETE(signOutRequest())).status).toBe(200);
  });

  it("clears the cookie when revoke reports the SID already dead", async () => {
    const cookie = await signIn();
    live.delete(cookie);
    mockedRevoke.mockResolvedValueOnce(false);
    const out = await DELETE(signOutRequest(cookie));
    expect(out.status).toBe(200);
    const cleared = (out as unknown as { cookies: { get(n: string): { value: string } | undefined } }).cookies.get(
      SESSION_COOKIE_NAME,
    );
    expect(cleared?.value).toBe("");
    expect((await pulse(protectedRequest(cookie))).status).toBe(401);
  });
});

describe("GET session", () => {
  it("returns a replay binding derived from the opaque SID", async () => {
    const cookie = await signIn();
    const response = await GET(sessionGetRequest(cookie));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.principalId).toBe(PRINCIPAL_A.principalId);
    expect(body.replayBinding).toBe(await sessionReplayBinding(cookie));
    expect(body).not.toHaveProperty("issuedSid");
  });

  it("answers 401 when the SID is dead", async () => {
    const cookie = await signIn();
    live.delete(cookie);
    expect((await GET(sessionGetRequest(cookie))).status).toBe(401);
  });
});

describe("mode gating", () => {
  it("refuses to sign anyone in when MYPA_AUTH_MODE is unset", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "");
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(500);
    expect((await response.json()).error.code).toBe("auth_mode_not_configured");
  });

  it("refuses the synthetic provider in a production build", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://app.example.test");
    const response = await POST(
      signInRequest("synthetic-a", { origin: "https://app.example.test" }),
    );
    expect(response.status).toBe(500);
    expect((await response.json()).error.message).toContain("NODE_ENV");
  });

  it("refuses a synthetic key when the mode is passkey", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(403);
    expect((await response.json()).error.code).toBe("synthetic_sign_in_disabled");
  });

  it("refuses a synthetic principal whose tenant is not the configured home tenant", async () => {
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "22222222-3333-4444-5555-666666666666");
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("invalid_claims");
  });
});

describe("session-service authority", () => {
  it("answers 503 authority_unavailable when POST cannot authenticate to the service", async () => {
    mockedIssue.mockRejectedValueOnce(new MissingSessionServiceSecretError());
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("authority_unavailable");
  });

  it("answers 503 authority_unavailable when DELETE cannot authenticate to the service", async () => {
    const cookie = await signIn();
    mockedRevoke.mockRejectedValueOnce(new MissingSessionServiceSecretError());
    const response = await DELETE(signOutRequest(cookie));
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("authority_unavailable");
  });
});

describe("cross-site requests", () => {
  it("refuses a POST from another origin", async () => {
    const response = await POST(signInRequest("synthetic-a", { origin: "https://evil.example" }));
    expect(response.status).toBe(403);
    expect((await response.json()).error.code).toBe("cross_site_request");
  });

  it("refuses a DELETE from another origin, and leaves the session live", async () => {
    const cookie = await signIn();
    const response = await DELETE(signOutRequest(cookie, "https://evil.example"));
    expect(response.status).toBe(403);
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);
  });

  it("refuses a request carrying no origin evidence at all", async () => {
    const response = await POST(signInRequest("synthetic-a", { origin: null }));
    expect(response.status).toBe(403);
  });

  it("refuses a cross-site Sec-Fetch-Site even with a matching Origin", async () => {
    const response = await POST(
      signInRequest("synthetic-a", { fetchSite: "cross-site" }),
    );
    expect(response.status).toBe(403);
  });

  it("accepts the app's own same-origin fetch", async () => {
    const response = await POST(signInRequest("synthetic-a", { fetchSite: "same-origin" }));
    expect(response.status).toBe(200);
    expectOpaqueSid(issuedCookie(response));
  });
});
