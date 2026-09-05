// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { POST as endRelationship } from "@/app/api/canvas/relationships/end/route";
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
  state: "ended",
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
  const request = new NextRequest(`${ORIGIN}/api/canvas/relationships/end`, {
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
  reason: "a synthetic withdrawal",
  idempotency_key: "idem-1",
  end_now: true,
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

describe("POST /api/canvas/relationships/end", () => {
  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    const response = await endRelationship(mutatingPost(cookie, VALID_BODY, origin));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("entities.relationships.end");
  });

  it("ends a typed relationship without a caller-supplied principal", async () => {
    const cookie = await signIn();
    const response = await endRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(RECEIPT);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain("/v1/entities.relationships.end");
    expect(sent[0].body.payload).toEqual(VALID_BODY);
    expect(sent[0].body.payload).not.toHaveProperty("principal_id");
    expect(sent[0].body.payload).not.toHaveProperty("effective_end");
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
    const response = await endRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(409);
    expect((await response.json()).error.errorClass).toBe("conflict");
    expect(sent[0].url).toContain("/v1/entities.relationships.end");
  });

  it("answers not_implemented under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const cookie = await signIn();
    const response = await endRelationship(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "not_implemented" },
    });
    expect(sent).toEqual([]);
  });

  it("refuses a body that names a principal", async () => {
    const cookie = await signIn();
    const response = await endRelationship(
      mutatingPost(cookie, { ...VALID_BODY, principal_id: "prn_foreign" }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it.each([
    { name: "zero", value: 0 },
    { name: "negative", value: -1 },
    { name: "missing", value: undefined },
  ])("refuses $name expected_version before the gateway", async ({ value }) => {
    const cookie = await signIn();
    const body =
      value === undefined
        ? {
            relationship_id: VALID_BODY.relationship_id,
            reason: VALID_BODY.reason,
            idempotency_key: VALID_BODY.idempotency_key,
            end_now: true,
          }
        : { ...VALID_BODY, expected_version: value };
    const response = await endRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses end_now together with effective_end before the gateway", async () => {
    const cookie = await signIn();
    const response = await endRelationship(
      mutatingPost(
        cookie,
        { ...VALID_BODY, effective_end: "2026-08-09T12:00:00.000Z" },
        ORIGIN,
      ),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("forwards effective_end without end_now", async () => {
    const cookie = await signIn();
    const body = {
      relationship_id: VALID_BODY.relationship_id,
      expected_version: 1,
      reason: VALID_BODY.reason,
      idempotency_key: VALID_BODY.idempotency_key,
      effective_end: "2026-08-09T12:00:00.000Z",
    };
    const response = await endRelationship(mutatingPost(cookie, body, ORIGIN));
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].body.payload).toEqual(body);
    expect(sent[0].body.payload).not.toHaveProperty("end_now");
  });

  it("refuses end_now false without effective_end before the gateway", async () => {
    const cookie = await signIn();
    const response = await endRelationship(
      mutatingPost(cookie, { ...VALID_BODY, end_now: false }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses empty effective_end with end_now false before the gateway", async () => {
    const cookie = await signIn();
    const response = await endRelationship(
      mutatingPost(
        cookie,
        { ...VALID_BODY, end_now: false, effective_end: "   " },
        ORIGIN,
      ),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });
});
