// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { POST as createRelationship } from "@/app/api/canvas/relationships/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const FROM = "ent_aaaaaaaa11111111";
const TO = "ent_bbbbbbbb22222222";
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
  prior_version: null,
  version: 1,
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
  const request = new NextRequest(`${ORIGIN}/api/canvas/relationships`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

const VALID_BODY = {
  from_entity_id: FROM,
  to_entity_id: TO,
  relationship_type: "works_for",
  expected_from_version: 1,
  expected_to_version: 1,
  idempotency_key: "idem-1",
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

describe("POST /api/canvas/relationships", () => {
  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    const response = await createRelationship(mutatingPost(cookie, VALID_BODY, origin));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("entities.relationships.create");
  });

  it("creates a typed relationship without a caller-supplied principal", async () => {
    const cookie = await signIn();
    const response = await createRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(RECEIPT);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain("/v1/entities.relationships.create");
    expect(sent[0].body.payload).toEqual(VALID_BODY);
    expect(sent[0].body.payload).not.toHaveProperty("principal_id");
  });

  it("forwards a typed version conflict rather than succeeding", async () => {
    vi.stubGlobal(
      "fetch",
      withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
        sent.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
        return new Response(
          JSON.stringify({ error: { code: "conflict", message: "stale expected_from_version" } }),
          { status: 409, headers: { "content-type": "application/json" } },
        );
      }),
    );
    const cookie = await signIn();
    const response = await createRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(409);
    expect((await response.json()).error.errorClass).toBe("conflict");
    expect(sent[0].url).toContain("/v1/entities.relationships.create");
  });

  it("answers not_implemented under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const cookie = await signIn();
    const response = await createRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "not_implemented" },
    });
    expect(sent).toEqual([]);
  });

  it("refuses a body that names a principal", async () => {
    const cookie = await signIn();
    const response = await createRelationship(
      mutatingPost(cookie, { ...VALID_BODY, principal_id: "prn_foreign" }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it.each([
    { field: "expected_from_version" as const, value: 0 },
    { field: "expected_from_version" as const, value: -1 },
    { field: "expected_from_version" as const, value: undefined },
    { field: "expected_to_version" as const, value: 0 },
    { field: "expected_to_version" as const, value: -1 },
    { field: "expected_to_version" as const, value: undefined },
  ])("refuses $field=$value before the gateway", async ({ field, value }) => {
    const cookie = await signIn();
    const body = { ...VALID_BODY };
    if (value === undefined) {
      delete body[field];
    } else {
      body[field] = value;
    }
    const response = await createRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses from_entity_id equal to to_entity_id before the gateway", async () => {
    const cookie = await signIn();
    const response = await createRelationship(
      mutatingPost(cookie, { ...VALID_BODY, to_entity_id: FROM }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("forwards a scoped create only when both scope fields are present", async () => {
    const cookie = await signIn();
    const body = {
      ...VALID_BODY,
      scope_entity_id: "ent_cccccccc33333333",
      expected_scope_version: 2,
    };
    const response = await createRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].body.payload).toEqual(body);
  });

  it.each([
    {
      name: "scope without version",
      body: { ...VALID_BODY, scope_entity_id: "ent_cccccccc33333333" },
    },
    {
      name: "version without scope",
      body: { ...VALID_BODY, expected_scope_version: 2 },
    },
  ])("refuses $name before the gateway", async ({ body }) => {
    const cookie = await signIn();
    const response = await createRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses an unadmitted relationship_type before the gateway", async () => {
    const cookie = await signIn();
    const response = await createRelationship(
      mutatingPost(cookie, { ...VALID_BODY, relationship_type: "employment" }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });
});
