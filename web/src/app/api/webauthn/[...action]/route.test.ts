/**
 * WebAuthn BFF: issuedSid is a Set-Cookie only, never browser JSON.
 * Step-up rotates the cookie SID via the session-service.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/webauthn/[...action]/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { callWebAuthnGateway } from "@/lib/auth/webauthn-server";
import {
  callSessionService,
  rotateSid,
  revokeSid,
  MissingSessionServiceSecretError,
} from "@/lib/auth/session-service";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";
import type { PrincipalSession } from "@/contracts/identity";

vi.mock("@/lib/auth/webauthn-server", () => ({
  callWebAuthnGateway: vi.fn(),
}));

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    rotateSid: vi.fn(),
    revokeSid: vi.fn(),
    callSessionService: vi.fn(),
  };
});

const ORIGIN = "http://localhost:3000";
const SID = "ab".repeat(32);
const NEW_SID = "cd".repeat(32);
const PRIOR = "ef".repeat(32);

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: SYNTHETIC_MOSS_TENANT_ID,
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
  authenticationProvider: "synthetic",
};

const mockedGateway = vi.mocked(callWebAuthnGateway);
const mockedRotate = vi.mocked(rotateSid);
const mockedRevoke = vi.mocked(revokeSid);
const mockedCall = vi.mocked(callSessionService);

function cookieOf(response: Response): string | undefined {
  return (response as unknown as { cookies: { get(name: string): { value: string } | undefined } }).cookies.get(
    SESSION_COOKIE_NAME,
  )?.value;
}

function requestFor(
  action: string[],
  body: unknown,
  init: { cookie?: string; origin?: string } = {},
): NextRequest {
  const request = new NextRequest(`${ORIGIN}/api/webauthn/${action.join("/")}`, {
    method: "POST",
    headers: {
      origin: init.origin ?? ORIGIN,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (init.cookie) request.cookies.set(SESSION_COOKIE_NAME, init.cookie);
  return request;
}

function post(action: string[], body: unknown = {}, init: { cookie?: string; origin?: string } = {}) {
  return POST(requestFor(action, body, init), { params: Promise.resolve({ action }) });
}

beforeEach(() => {
  mockedGateway.mockReset();
  mockedRotate.mockReset();
  mockedRevoke.mockReset();
  mockedCall.mockReset();
  mockedRevoke.mockResolvedValue(true);
  mockedCall.mockResolvedValue(
    new Response(JSON.stringify({ principal: PRINCIPAL }), { status: 200 }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("authentication/complete issuedSid handoff", () => {
  it("sets the opaque SID cookie and strips issuedSid from the browser JSON", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          sessionCreated: true,
          issuedSid: SID,
          tid: SYNTHETIC_MOSS_TENANT_ID,
          oid: PRINCIPAL.oid,
        }),
        { status: 200 },
      ),
    );
    const response = await post(["authentication", "complete"], { credential: { id: "cred" } });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.sessionCreated).toBe(true);
    expect(body).not.toHaveProperty("issuedSid");
    expect(JSON.stringify(body)).not.toContain(SID);
    expect(cookieOf(response)).toBe(SID);
  });

  it("revokes a prior cookie SID after the new cookie is set", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ sessionCreated: true, issuedSid: SID }), { status: 200 }),
    );
    const response = await post(["authentication", "complete"], { credential: {} }, { cookie: PRIOR });
    expect(response.status).toBe(200);
    expect(cookieOf(response)).toBe(SID);
    expect(mockedRevoke).toHaveBeenCalledWith(PRIOR, expect.anything());
  });

  it("does not fail sign-in when prior revoke returns false", async () => {
    mockedRevoke.mockResolvedValueOnce(false);
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ sessionCreated: true, issuedSid: SID }), { status: 200 }),
    );
    const response = await post(["authentication", "complete"], { credential: {} }, { cookie: PRIOR });
    expect(response.status).toBe(200);
    expect(cookieOf(response)).toBe(SID);
  });

  it("does not mint a cookie when sessionCreated is true but issuedSid is missing", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ sessionCreated: true, tid: SYNTHETIC_MOSS_TENANT_ID }), { status: 200 }),
    );
    const response = await post(["authentication", "complete"], { credential: {} });
    expect(response.status).toBe(503);
    expect(cookieOf(response)).toBeUndefined();
  });
});

describe("recovery/consume issuedSid handoff", () => {
  it("sets the cookie and strips issuedSid", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ sessionCreated: true, issuedSid: NEW_SID }), { status: 200 }),
    );
    const response = await post(["recovery", "consume"], { code: "AAAA-BBBB" });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).not.toHaveProperty("issuedSid");
    expect(cookieOf(response)).toBe(NEW_SID);
  });
});

describe("step-up/complete rotates the SID", () => {
  it("sets the rotated SID cookie and strips any issuedSid from JSON", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ administrationGrant: "grant", issuedSid: "leak-me" }), { status: 200 }),
    );
    mockedRotate.mockResolvedValueOnce(NEW_SID);
    const response = await post(["step-up", "complete"], { credential: {} }, { cookie: SID });
    expect(response.status).toBe(200);
    expect(mockedRotate).toHaveBeenCalledWith(SID, expect.anything());
    const body = await response.json();
    expect(body.administrationGrant).toBe("grant");
    expect(body).not.toHaveProperty("issuedSid");
    expect(cookieOf(response)).toBe(NEW_SID);
  });

  it("answers 401 when rotate loses a concurrent rotation, without inventing a SID", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ administrationGrant: "grant" }), { status: 200 }),
    );
    mockedRotate.mockResolvedValueOnce(null);
    const response = await post(["step-up", "complete"], { credential: {} }, { cookie: SID });
    expect(response.status).toBe(401);
    expect(cookieOf(response)).toBe("");
    expect(JSON.stringify(await response.json())).not.toContain(NEW_SID);
  });

  it("answers 503 when the session-service secret is missing", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ administrationGrant: "grant" }), { status: 200 }),
    );
    mockedRotate.mockRejectedValueOnce(new MissingSessionServiceSecretError());
    const response = await post(["step-up", "complete"], { credential: {} }, { cookie: SID });
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("authority_unavailable");
  });
});

describe("ceremony passthrough", () => {
  it("does not attach a session cookie to authentication/options", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ challenge: "abc" }), { status: 200 }),
    );
    const response = await post(["authentication", "options"], {});
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ challenge: "abc" });
    expect(cookieOf(response)).toBeUndefined();
  });

  it("refuses a cross-site caller before the gateway", async () => {
    const response = await post(["authentication", "options"], {}, { origin: "https://evil.example" });
    expect(response.status).toBe(403);
    expect(mockedGateway).not.toHaveBeenCalled();
  });

  it("strips issuedSid from any browser-visible JSON", async () => {
    mockedGateway.mockResolvedValueOnce(
      new Response(JSON.stringify({ challenge: "abc", issuedSid: SID }), { status: 200 }),
    );
    const response = await post(["authentication", "options"], {});
    expect(await response.json()).toEqual({ challenge: "abc" });
  });
});
