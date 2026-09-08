// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { POST as putWorkspace } from "@/app/api/canvas/workspace/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const FOCUS = "ent_aaaaaaaa11111111";
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};
const RECEIPT = {
  focus_entity_id: FOCUS,
  scope_entity_id: null,
  version: 1,
  positions: { [FOCUS]: { x: 12.5, y: 40.25 } },
  updated_at: "2026-08-09T12:00:00.000Z",
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
  const request = new NextRequest(`${ORIGIN}/api/canvas/workspace`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

const VALID_BODY = {
  focus_entity_id: FOCUS,
  expected_version: 0,
  positions: { [FOCUS]: { x: 12.5, y: 40.25 } },
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

describe("POST /api/canvas/workspace", () => {
  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    const response = await putWorkspace(mutatingPost(cookie, VALID_BODY, origin));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("canvas.workspace.put");
  });

  it("puts a typed overlay without a caller-supplied principal", async () => {
    const cookie = await signIn();
    const response = await putWorkspace(mutatingPost(cookie, VALID_BODY, ORIGIN));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      version: 1,
      updated_at: "2026-08-09T12:00:00.000Z",
      positions: { [FOCUS]: { x: 12.5, y: 40.25 } },
      focus_entity_id: FOCUS,
      scope_entity_id: null,
    });
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toContain("/v1/canvas.workspace.put");
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
    const response = await putWorkspace(
      mutatingPost(cookie, { ...VALID_BODY, expected_version: 0 }, ORIGIN),
    );
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.error.errorClass).toBe("conflict");
    expect(body.error.code).toBe("conflict");
    expect(body).not.toHaveProperty("positions");
    expect(body).not.toHaveProperty("version");
    expect(sent[0].url).toContain("/v1/canvas.workspace.put");
  });

  it.each([
    { name: "string", value: "0" },
    { name: "float", value: 0.5 },
    { name: "null", value: null },
    { name: "boolean", value: true },
    { name: "object", value: {} },
  ])("refuses malformed expected_version ($name) before the gateway", async ({ value }) => {
    const cookie = await signIn();
    const response = await putWorkspace(
      mutatingPost(cookie, { ...VALID_BODY, expected_version: value }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "invalid_expected_version" },
    });
    expect(sent).toEqual([]);
  });

  it("refuses a body that names a principal", async () => {
    const cookie = await signIn();
    const response = await putWorkspace(
      mutatingPost(cookie, { ...VALID_BODY, principal_id: "prn_foreign" }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses a missing seed before the gateway", async () => {
    const cookie = await signIn();
    const response = await putWorkspace(
      mutatingPost(cookie, { expected_version: 0, positions: {} }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it("refuses a negative expected_version before the gateway", async () => {
    const cookie = await signIn();
    const response = await putWorkspace(
      mutatingPost(cookie, { ...VALID_BODY, expected_version: -1 }, ORIGIN),
    );
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });
});
