// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  InvalidSessionServiceUrlError,
  MissingSessionServiceSecretError,
  SESSION_SERVICE_HEADER,
  callSessionService,
  issueSessionServiceToken,
  sessionServiceBaseUrl,
  issueSyntheticSession,
  rotateSid,
  revokeSid,
  touchSid,
} from "@/lib/auth/session-service";

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

function stubFetch(status: number, body: unknown) {
  const fetchStub = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_CANONICAL_ORIGIN", "http://localhost:3000");
  vi.stubEnv("MYPA_SESSION_SERVICE_SECRET", "synthetic-test-session-service-secret-00");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("issueSessionServiceToken", () => {
  it("signs sorted {iat}-only JSON", () => {
    const token = issueSessionServiceToken(1_725_000_000_000);
    const [payload, signature] = token.split(".");
    expect(signature).toMatch(/^[0-9a-f]+$/);
    const json = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      iat: number;
    };
    expect(json).toEqual({ iat: 1_725_000_000 });
    expect(Object.keys(json)).toEqual(["iat"]);
  });

  it("refuses a short or missing secret", () => {
    vi.stubEnv("MYPA_SESSION_SERVICE_SECRET", "short");
    vi.stubEnv("MY_PA_SESSION_SERVICE_SECRET", "");
    expect(() => issueSessionServiceToken()).toThrow(MissingSessionServiceSecretError);
  });
});

describe("callSessionService", () => {
  it("POSTs SID-only JSON with Origin and the session-service header, not attestation", async () => {
    const fetchStub = stubFetch(200, { principal: PRINCIPAL });
    const request = new Request("http://localhost:3000/today", {
      headers: { origin: "http://localhost:3000" },
    });
    await callSessionService("sessions/touch", { sid: SID }, request);
    expect(fetchStub).toHaveBeenCalledTimes(1);
    const [url, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/webauthn/v1/sessions/touch");
    const headers = new Headers(init.headers);
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("origin")).toBe("http://localhost:3000");
    expect(headers.get(SESSION_SERVICE_HEADER)).toMatch(/^[A-Za-z0-9_-]+\.[0-9a-f]+$/);
    expect(headers.get("x-my-pa-webauthn-attestation")).toBeNull();
    expect(JSON.parse(String(init.body))).toEqual({ sid: SID });
  });

  it("uses MYPA_GATEWAY_URL when MYPA_SESSION_SERVICE_URL is unset", () => {
    vi.stubEnv("MYPA_SESSION_SERVICE_URL", "");
    expect(sessionServiceBaseUrl()).toBe("http://127.0.0.1:8000");
  });

  it("POSTs session-service to MYPA_SESSION_SERVICE_URL when set", async () => {
    vi.stubEnv("MYPA_SESSION_SERVICE_URL", "http://127.0.0.1:9099");
    const fetchStub = stubFetch(200, { principal: PRINCIPAL });
    await callSessionService("sessions/touch", { sid: SID });
    const [url] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:9099/webauthn/v1/sessions/touch");
  });

  it("refuses a non-http MYPA_SESSION_SERVICE_URL", () => {
    vi.stubEnv("MYPA_SESSION_SERVICE_URL", "file:///etc/passwd");
    expect(() => sessionServiceBaseUrl()).toThrow(InvalidSessionServiceUrlError);
  });
});

describe("session-service helpers", () => {
  it("touchSid maps a 200 principal", async () => {
    stubFetch(200, { principal: PRINCIPAL });
    await expect(touchSid(SID)).resolves.toMatchObject({
      principalId: PRINCIPAL.principalId,
      authenticationProvider: "synthetic",
    });
  });

  it("rotateSid returns issuedSid or null on 401", async () => {
    stubFetch(200, { issuedSid: "11".repeat(32) });
    await expect(rotateSid(SID)).resolves.toBe("11".repeat(32));
    stubFetch(401, { error: { code: "unauthenticated" } });
    await expect(rotateSid(SID)).resolves.toBeNull();
  });

  it("rotate loser learns no SID even if 401 JSON names issuedSid", async () => {
    stubFetch(401, {
      error: { code: "unauthenticated" },
      issuedSid: "11".repeat(32),
    });
    await expect(rotateSid(SID)).resolves.toBeNull();
  });

  it("touchSid maps two SIDs to two principals and never the other", async () => {
    const sidB = "cd".repeat(32);
    const principalB = {
      ...PRINCIPAL,
      principalId: "syn-bbbb0002",
      oid: "bbbb0002-0000-0000-0000-000000000002",
      upn: "synthetic.b@moss.example",
      displayName: "Synthetic B",
    };
    const fetchStub = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const sid = (JSON.parse(String(init?.body)) as { sid?: string }).sid;
      if (sid === SID) {
        return new Response(JSON.stringify({ principal: PRINCIPAL }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (sid === sidB) {
        return new Response(JSON.stringify({ principal: principalB }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ error: { code: "unauthenticated" } }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchStub);
    await expect(touchSid(SID)).resolves.toMatchObject({ principalId: PRINCIPAL.principalId });
    await expect(touchSid(sidB)).resolves.toMatchObject({ principalId: principalB.principalId });
    await expect(touchSid(SID)).resolves.not.toMatchObject({
      principalId: principalB.principalId,
    });
  });

  it("revokeSid returns true on 200 and false on 401", async () => {
    stubFetch(200, { revoked: true });
    await expect(revokeSid(SID)).resolves.toBe(true);
    stubFetch(401, { error: { code: "unauthenticated" } });
    await expect(revokeSid(SID)).resolves.toBe(false);
  });

  it("issueSyntheticSession returns issuedSid and principal", async () => {
    stubFetch(200, { issuedSid: "22".repeat(32), principal: PRINCIPAL });
    await expect(issueSyntheticSession("synthetic-a")).resolves.toMatchObject({
      issuedSid: "22".repeat(32),
      principal: { principalId: PRINCIPAL.principalId },
    });
  });
});
