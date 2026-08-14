/**
 * The session lifecycle, against the real route handlers.
 *
 * What is proved here is the part a signed cookie cannot prove on its own:
 * that signing out actually ends the session, that signing in rotates it, that
 * an unconfigured or production-synthetic deployment refuses to sign anyone in,
 * and that a cross-site caller cannot drive either method.
 *
 * The controlling assertion is the replay: the *exact same cookie value* that
 * worked before `DELETE` is presented again afterwards and is refused. A test
 * that only checked the `Set-Cookie` clearing header would pass against an
 * implementation with no revocation at all, because clearing a cookie is a
 * request the holder may decline.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST, DELETE, GET } from "@/app/api/session/route";
import { GET as pulse } from "@/app/api/pulse/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry, IDLE_TIMEOUT_SECONDS } from "@/lib/auth/session-registry";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";

const ORIGIN = "http://localhost:3000";

function signInRequest(
  key: unknown,
  init: { origin?: string | null; fetchSite?: string | null; body?: unknown } = {},
): NextRequest {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const origin = init.origin === undefined ? ORIGIN : init.origin;
  if (origin !== null) headers["origin"] = origin;
  if (init.fetchSite != null) headers["sec-fetch-site"] = init.fetchSite;
  return new NextRequest(`${ORIGIN}/api/session`, {
    method: "POST",
    headers,
    body: JSON.stringify(init.body ?? { syntheticPrincipal: key }),
  });
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

/** The cookie value a sign-in response sets. */
function issuedCookie(response: Response): string {
  const value = (response as unknown as { cookies: { get(name: string): { value: string } | undefined } }).cookies.get(
    SESSION_COOKIE_NAME,
  );
  expect(value).toBeDefined();
  return value!.value;
}

async function signIn(key = "synthetic-a"): Promise<string> {
  const response = await POST(signInRequest(key));
  expect(response.status).toBe(200);
  return issuedCookie(response);
}

/**
 * This file's subject is the session lifecycle, not which data provider is
 * configured. It probes `/api/pulse` purely as "a route that requires a
 * principal", and WP-06 made that route answer `not_implemented` in a default
 * build because Today has no backend capability. The synthetic provider is
 * therefore turned on explicitly here, so the probe still has something to
 * return and every assertion below stays exactly the assertion it was. The
 * default-build behaviour is asserted in `src/app/api/routes.test.ts`.
 */
beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
  resetSessionRegistry();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("sign-in", () => {
  it("mints a session for a known synthetic principal", async () => {
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ signedIn: true });
    const cookie = issuedCookie(response);
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);
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

  it("rotates the session identifier, so a prior session cannot survive it", async () => {
    const first = await signIn();
    expect((await pulse(protectedRequest(first))).status).toBe(200);

    const second = await signIn();
    expect(second).not.toBe(first);
    // The new session works and the old one does not: no session fixation.
    expect((await pulse(protectedRequest(second))).status).toBe(200);
    expect((await pulse(protectedRequest(first))).status).toBe(401);
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
});

describe("sign-out revokes server-side", () => {
  it("refuses a replay of the exact same cookie value after sign-out", async () => {
    const cookie = await signIn();
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);

    const out = await DELETE(signOutRequest(cookie));
    expect(out.status).toBe(200);

    // The controlling assertion: the identical bearer value, replayed.
    expect((await pulse(protectedRequest(cookie))).status).toBe(401);
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
});

describe("idle timeout", () => {
  it("refuses a session left unused past the idle window", async () => {
    const cookie = await signIn();
    expect((await pulse(protectedRequest(cookie))).status).toBe(200);

    const later = Date.now() + (IDLE_TIMEOUT_SECONDS + 60) * 1000;
    vi.useFakeTimers();
    vi.setSystemTime(later);
    expect((await pulse(protectedRequest(cookie))).status).toBe(401);
  });

  it("keeps a session that is used inside the window", async () => {
    const cookie = await signIn();
    vi.useFakeTimers();
    for (let step = 1; step <= 3; step++) {
      vi.setSystemTime(Date.now() + (IDLE_TIMEOUT_SECONDS - 60) * 1000);
      expect((await pulse(protectedRequest(cookie))).status).toBe(200);
    }
  });
});

describe("mode gating", () => {
  it("authenticates only the configured local operator and ignores no caller identity", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "local_operator");
    vi.stubEnv("MYPA_LOCAL_OPERATOR_SECRET", "A_credentialed_local_operator_secret_1234567890");
    const denied = await POST(
      signInRequest(undefined, { body: { operatorSecret: "wrong" } }),
    );
    expect(denied.status).toBe(401);
    const accepted = await POST(
      signInRequest(undefined, {
        body: { operatorSecret: "A_credentialed_local_operator_secret_1234567890" },
      }),
    );
    expect(accepted.status).toBe(200);
    const cookie = issuedCookie(accepted);
    const session = await (await GET(protectedRequest(cookie))).json();
    expect(session.principalId).toBe("prn_24abf5d2d0c25e1c82f6e72425e9ed37");
  });

  it("refuses local_operator mode without an admitted secret", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "local_operator");
    vi.stubEnv("MYPA_LOCAL_OPERATOR_SECRET", "");
    const response = await POST(signInRequest(undefined, { body: { operatorSecret: "x" } }));
    expect(response.status).toBe(500);
    expect((await response.json()).error.code).toBe("auth_mode_not_configured");
  });

  it("rejects caller-selected identity before local operator authentication", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "local_operator");
    vi.stubEnv("MYPA_LOCAL_OPERATOR_SECRET", "A_credentialed_local_operator_secret_1234567890");
    const response = await POST(
      signInRequest(undefined, {
        body: {
          operatorSecret: "A_credentialed_local_operator_secret_1234567890",
          principalId: "forged",
        },
      }),
    );
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("caller_supplied_principal");
  });

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

  it("refuses a synthetic key when the mode is entra", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "entra");
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "22222222-3333-4444-5555-666666666666");
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(403);
    expect((await response.json()).error.code).toBe("synthetic_sign_in_disabled");
  });

  it("refuses a synthetic principal whose tenant is not the configured home tenant", async () => {
    // The synthetic principals live in the synthetic tenant; pointing the
    // deployment at a different home tenant must reject them rather than
    // quietly accepting the tenant baked into the fixture.
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "22222222-3333-4444-5555-666666666666");
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("invalid_claims");
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
  });
});
