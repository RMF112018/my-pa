// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { POST as preview } from "@/app/api/tasks/bulk/preview/route";
import { POST as confirm } from "@/app/api/tasks/bulk/confirm/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
let sent: Array<{ url: string; body: Record<string, unknown> }> = [];

async function signIn() {
  const response = await signInRoute(new NextRequest(`${ORIGIN}/api/session`, {
    method: "POST", headers: { "content-type": "application/json", origin: ORIGIN },
    body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
  }));
  return (response as unknown as { cookies: { get(name: string): { value: string } } }).cookies.get(SESSION_COOKIE_NAME).value;
}

function request(cookie: string, path: string, body: unknown) {
  const result = new NextRequest(`${ORIGIN}${path}`, { method: "POST", headers: { "content-type": "application/json", origin: ORIGIN }, body: JSON.stringify(body) });
  result.cookies.set(SESSION_COOKIE_NAME, cookie);
  return result;
}

beforeEach(() => {
  resetSessionRegistry(); sent = [];
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubGlobal("fetch", withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
    sent.push({ url: String(url), body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({ result: { bulk_operation_id: "bulk_aaaaaaaa11111111", expires_at: "2099-08-21T12:15:00Z", affected: 1, no_op: 0, rejected: 0, history_ids: [], replayed: false }, disclosure: { coverage: { state: "not_enrolled" }, freshness: { observed_at: "2026-08-21T12:00:00Z", state: "current_for_observed_version" }, trust: { level: "source_original", basis: ["user_authored_record"] }, truncation: { is_truncated: false }, limitations: [], partial_result: false } }), { status: 200, headers: { "content-type": "application/json" } });
  }));
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("Task bulk BFF routes", () => {
  it("maps preview and confirm without accepting caller authority fields", async () => {
    const cookie = await signIn();
    const mutations = [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { priority: "p1" }, clear_fields: [] }];
    const previewResponse = await preview(request(cookie, "/api/tasks/bulk/preview", { mutations, idempotencyKey: "bulk-preview-0001" }));
    const confirmResponse = await confirm(request(cookie, "/api/tasks/bulk/confirm", { bulkOperationId: "bulk_aaaaaaaa11111111", mutations, idempotencyKey: "bulk-confirm-0001" }));
    expect(previewResponse.status).toBe(200); expect(confirmResponse.status).toBe(200);
    expect(previewResponse.headers.get("cache-control")).toBe("private, no-store");
    expect(sent.map((entry) => entry.url)).toEqual(["http://127.0.0.1:8000/v1/tasks.bulk_preview", "http://127.0.0.1:8000/v1/tasks.bulk_confirm"]);
    expect((sent[0].body.payload as Record<string, unknown>).mutations).toEqual(mutations);
    expect((sent[1].body.payload as Record<string, unknown>).bulk_operation_id).toBe("bulk_aaaaaaaa11111111");
  });

  it.each(["principalId", "purpose", "bearer"])("refuses browser-supplied %s", async (field) => {
    const cookie = await signIn();
    const response = await preview(request(cookie, "/api/tasks/bulk/preview", { mutations: [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { priority: "p1" }, clear_fields: [], [field]: "foreign" }], idempotencyKey: "bulk-preview-0001", ...(field === "principalId" ? {} : { [field]: "foreign" }) }));
    expect(response.status).toBe(400);
    expect(sent).toHaveLength(0);
  });

  it.each([
    null,
    {},
    "mutations",
    [],
    Array.from({ length: 101 }, () => ({ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { priority: "p1" }, clear_fields: [] })),
    [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: "1", values: { priority: "p1" }, clear_fields: [] }],
    [{ kind: "update", task_id: [], expected_version: 1, values: { priority: "p1" }, clear_fields: [] }],
    [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { title: null }, clear_fields: [] }],
    [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { archived: "false" }, clear_fields: [] }],
    [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { priority: "p1" }, clear_fields: null }],
    [{ kind: "transition", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, to_state: {}, closure_evidence_ref: "cap_aaaaaaaa11111111" }],
    [{ kind: "transition", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, to_state: "completed", closure_evidence_ref: null }],
  ])("refuses malformed bounded mutations before the gateway", async (mutations) => {
    const cookie = await signIn();
    const response = await preview(request(cookie, "/api/tasks/bulk/preview", {
      mutations,
      idempotencyKey: "bulk-preview-0001",
    }));
    expect(response.status).toBe(400);
    expect(sent).toHaveLength(0);
  });

  it.each([null, [], {}, 42, true])("refuses non-string idempotencyKey %j", async (idempotencyKey) => {
    const cookie = await signIn();
    const response = await preview(request(cookie, "/api/tasks/bulk/preview", {
      mutations: [{ kind: "update", task_id: "tsk_aaaaaaaa11111111", expected_version: 1, values: { priority: "p1" }, clear_fields: [] }],
      idempotencyKey,
    }));
    expect(response.status).toBe(400);
    expect(sent).toHaveLength(0);
  });
});
