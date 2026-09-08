// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { POST as reviseRelationship } from "@/app/api/canvas/relationships/revise/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};
const RECEIPT = {
  record_id: "erel_aaaaaaaa11111111",
  record_family: "relationship",
  prior_version: 1,
  version: 2,
  state: "active",
  receipt_id: "emut_aaaaaaaa11111111",
  audit_id: "audit_aaaaaaaa11111111",
  idempotency_key: "idem-1",
  superseded_id: null,
  evidence_refs: [],
  replayed: false,
  issued_at: "2026-08-09T12:00:00.000Z",
};

let sent: Array<{ url: string; body: Record<string, unknown> }> = [];

async function signIn() {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
    }),
  );
  return (response as unknown as { cookies: { get(name: string): { value: string } } }).cookies.get(
    SESSION_COOKIE_NAME,
  ).value;
}

function mutatingPost(cookie: string, body: unknown, origin: string | null): NextRequest {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  const request = new NextRequest(`${ORIGIN}/api/canvas/relationships/revise`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

const VALID_BODY = {
  relationship_id: "erel_aaaaaaaa11111111",
  expected_version: 1,
  idempotency_key: "idem-1",
  evidence_refs: [] as readonly string[],
};

beforeEach(() => {
  resetSessionRegistry();
  sent = [];
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubGlobal(
    "fetch",
    withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
      sent.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
      return new Response(JSON.stringify({ result: RECEIPT, disclosure: DISCLOSURE }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("POST /api/canvas/relationships/revise", () => {
  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    const response = await reviseRelationship(mutatingPost(cookie, VALID_BODY, origin));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("entities.relationships.revise");
  });

  it("revises a typed relationship without a caller-supplied principal", async () => {
    const cookie = await signIn();
    const response = await reviseRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(RECEIPT);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain("/v1/entities.relationships.revise");
    expect(sent[0].body.payload).toEqual(VALID_BODY);
    expect(sent[0].body.payload).not.toHaveProperty("principal_id");
  });

  it("forwards a typed version conflict rather than succeeding", async () => {
    vi.stubGlobal(
      "fetch",
      withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
        sent.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
        return new Response(
          JSON.stringify({ error: { code: "conflict", message: "stale expected_version" } }),
          { status: 409, headers: { "content-type": "application/json" } },
        );
      }),
    );
    const cookie = await signIn();
    const response = await reviseRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.error.errorClass).toBe("conflict");
    expect(body).not.toHaveProperty("record_id");
    expect(body).not.toHaveProperty("receipt_id");
    expect(sent[0].url).toContain("/v1/entities.relationships.revise");
  });

  it("answers not_implemented under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const cookie = await signIn();
    const response = await reviseRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "not_implemented" },
    });
    expect(sent).toEqual([]);
  });

  it("refuses a body that names a principal", async () => {
    const cookie = await signIn();
    const response = await reviseRelationship(
      mutatingPost(cookie, { ...VALID_BODY, principal_id: "prn_foreign" }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it.each([
    { name: "zero", value: 0 },
    { name: "negative", value: -1 },
    { name: "missing", value: undefined },
    { name: "string", value: "1" },
    { name: "float", value: 1.5 },
    { name: "null", value: null },
    { name: "boolean", value: true },
    { name: "object", value: {} },
  ])("refuses $name expected_version before the gateway", async ({ value }) => {
    const cookie = await signIn();
    const body: Record<string, unknown> =
      value === undefined
        ? {
            relationship_id: VALID_BODY.relationship_id,
            idempotency_key: VALID_BODY.idempotency_key,
            evidence_refs: VALID_BODY.evidence_refs,
          }
        : { ...VALID_BODY, expected_version: value };
    const response = await reviseRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "invalid_expected_version" },
    });
    expect(sent).toEqual([]);
  });

  it("refuses effective_from that is also cleared before the gateway", async () => {
    const cookie = await signIn();
    const response = await reviseRelationship(
      mutatingPost(
        cookie,
        { ...VALID_BODY, effective_from: "2026-01-01T00:00:00Z", clear: ["effective_from"] },
        ORIGIN,
      ),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("forwards clear without restating the field", async () => {
    const cookie = await signIn();
    const body = { ...VALID_BODY, clear: ["effective_to"] };
    const response = await reviseRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].body.payload).toEqual(body);
  });

  it("refuses an omitted evidence_refs before the gateway", async () => {
    const cookie = await signIn();
    const withoutEvidence = {
      relationship_id: VALID_BODY.relationship_id,
      expected_version: VALID_BODY.expected_version,
      idempotency_key: VALID_BODY.idempotency_key,
    };
    const response = await reviseRelationship(mutatingPost(cookie, withoutEvidence, ORIGIN));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "missing_evidence_refs" },
    });
    expect(sent).toEqual([]);
  });

  it("forwards an explicit empty evidence_refs replacement to the gateway", async () => {
    const cookie = await signIn();
    const body = { ...VALID_BODY, evidence_refs: [] };
    const response = await reviseRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain("/v1/entities.relationships.revise");
    expect(sent[0].body.payload).toEqual(body);
  });
});
