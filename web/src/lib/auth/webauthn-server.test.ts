// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  callWebAuthnGateway,
  issueWebAuthnAttestation,
  WEBAUTHN_ATTESTATION_HEADER,
  WEBAUTHN_SID_HEADER,
} from "@/lib/auth/webauthn-server";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import type { PrincipalSession } from "@/contracts/identity";

const SECRET = "synthetic-test-webauthn-bff-secret-00";
const SID = "ab".repeat(32);
const PRINCIPAL: PrincipalSession = {
  principalId: "24abf5d2-d0c2-5e1c-82f6-e72425e9ed37",
  identityProvider: "local",
  identitySubject: "local-operator",
  displayName: "Local operator",
  lifecycleState: "active",
  synthetic: false,
};

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_WEBAUTHN_BFF_SECRET", SECRET);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("issueWebAuthnAttestation", () => {
  it("signs sorted {iat,pid} JSON, not tid/oid", () => {
    const token = issueWebAuthnAttestation(PRINCIPAL, 1_725_000_000_000);
    const [payload, signature] = token.split(".");
    expect(signature).toMatch(/^[0-9a-f]+$/);
    const json = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      iat: number;
      pid: string;
    };
    expect(json).toEqual({ iat: 1_725_000_000, pid: PRINCIPAL.principalId });
    expect(Object.keys(json)).toEqual(["iat", "pid"]);
    expect(JSON.stringify(json)).not.toContain("tid");
    expect(JSON.stringify(json)).not.toContain("oid");
  });
});

describe("callWebAuthnGateway", () => {
  it("sends pid attestation and copies the cookie SID on authenticated calls", async () => {
    const fetchStub = vi.fn(
      async (_url: string | URL | Request, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchStub);
    const request = new Request("http://localhost:3000/api/webauthn/registration/options", {
      method: "POST",
      headers: {
        origin: "http://localhost:3000",
        cookie: `${SESSION_COOKIE_NAME}=${SID}`,
      },
    });
    await callWebAuthnGateway("registration/options", { grant: "g" }, request, PRINCIPAL);
    const headers = new Headers(fetchStub.mock.calls[0][1]?.headers as HeadersInit);
    expect(headers.get(WEBAUTHN_SID_HEADER)).toBe(SID);
    const attestation = headers.get(WEBAUTHN_ATTESTATION_HEADER) ?? "";
    const payload = JSON.parse(
      Buffer.from(attestation.split(".")[0], "base64url").toString("utf8"),
    ) as { pid: string };
    expect(payload.pid).toBe(PRINCIPAL.principalId);
  });

  it("omits attestation and SID on public calls", async () => {
    const fetchStub = vi.fn(
      async (_url: string | URL | Request, _init?: RequestInit) =>
        new Response(JSON.stringify({ state: "ready" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchStub);
    const request = new Request("http://localhost:3000/api/webauthn/auth-state", {
      method: "POST",
      headers: { origin: "http://localhost:3000" },
    });
    await callWebAuthnGateway("auth-state", {}, request);
    const headers = new Headers(fetchStub.mock.calls[0][1]?.headers as HeadersInit);
    expect(headers.get(WEBAUTHN_ATTESTATION_HEADER)).toBeNull();
    expect(headers.get(WEBAUTHN_SID_HEADER)).toBeNull();
  });
});
