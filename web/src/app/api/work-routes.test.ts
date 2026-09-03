// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as listTasks } from "@/app/api/tasks/route";
import { PATCH as patchTask } from "@/app/api/tasks/[taskId]/route";
import { PATCH as patchCommitment } from "@/app/api/commitments/[commitmentId]/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const DISCLOSURE = { coverage: { state: "not_enrolled" }, freshness: { observed_at: "2026-08-21T12:00:00Z", state: "current_for_observed_version" }, trust: { level: "source_original", basis: ["user_authored_record"] }, truncation: { is_truncated: false }, limitations: [], partial_result: false };
const AT = "2026-08-09T12:00:00.000Z";

function taskView(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "tsk_aaaaaaaa11111111",
    title: "Canonical",
    description: null,
    lifecycle_state: "open",
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: "direct_principal",
    closure_history_id: null,
    version: 9,
    priority: null,
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    project_id: null,
    situation_id: null,
    recurrence_id: null,
    opened_at: AT,
    closed_at: null,
    created_at: AT,
    updated_at: AT,
    commitment_id: null,
    role: null,
    ...overrides,
  };
}

function taskHistory(overrides: Record<string, unknown> = {}) {
  return {
    history_id: "thst_aaaaaaaa11111111",
    task_id: "tsk_aaaaaaaa11111111",
    action: "update",
    actor: "principal",
    outcome: "applied",
    before_version: 8,
    after_version: 9,
    occurred_at: AT,
    recorded_at: AT,
    ...overrides,
  };
}

function commitmentView(overrides: Record<string, unknown> = {}) {
  return {
    commitment_id: "cmt_aaaaaaaa11111111",
    direction: "owed_to_principal",
    state: "open",
    counterparty_person_id: null,
    title: "Canonical",
    description: null,
    due_date: null,
    created_at: AT,
    updated_at: AT,
    version: 4,
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    closed_at: null,
    counterparty: null,
    ...overrides,
  };
}

function gatewayOk(result: unknown) {
  return new Response(JSON.stringify({ result, disclosure: DISCLOSURE }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

async function cookie() {
  const response = await signInRoute(new NextRequest(`${ORIGIN}/api/session`, { method: "POST", headers: { "content-type": "application/json", origin: ORIGIN }, body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }) }));
  return (response as unknown as { cookies: { get(name: string): { value: string } } }).cookies.get(SESSION_COOKIE_NAME).value;
}
function request(session: string, path: string, init?: ConstructorParameters<typeof NextRequest>[1]) {
  const headers = new Headers(init?.headers);
  if (!headers.has("origin") && !headers.has("sec-fetch-site")) headers.set("origin", ORIGIN);
  const value = new NextRequest(`${ORIGIN}${path}`, { ...init, headers });
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function stubWorkGateway(impl?: (url: string | URL | Request, init?: RequestInit) => unknown) {
  const gateway = impl ? vi.fn(impl) : vi.fn();
  vi.stubGlobal("fetch", withSessionServiceFetch(gateway));
  return gateway;
}

beforeEach(() => { resetSessionRegistry(); vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000"); vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator"); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Work BFF request normalization", () => {
  it.each([
    { name: "foreign Origin", headers: new Headers({ origin: "https://attacker.example" }) },
    { name: "same-site initiator", headers: new Headers({ origin: ORIGIN, "sec-fetch-site": "same-site" }) },
    { name: "cross-site initiator", headers: new Headers({ origin: ORIGIN, "sec-fetch-site": "cross-site" }) },
    { name: "missing origin evidence", headers: new Headers() },
  ])("refuses $name before parsing a Work mutation body", async ({ headers }) => {
    const gateway = stubWorkGateway();
    const value = new NextRequest(`${ORIGIN}/api/tasks/tsk_aaaaaaaa11111111`, {
      method: "PATCH", headers, body: "not-json",
    });
    value.cookies.set(SESSION_COOKIE_NAME, await cookie());
    const response = await patchTask(value, { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { errorClass: "authorization", code: "cross_site_request" } });
    expect(gateway).not.toHaveBeenCalled();
  });

  it.each(["same-origin", "none"])("refuses browser-vouched %s Work mutations without Origin", async (site) => {
    const gateway = stubWorkGateway();
    const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
      method: "PATCH",
      headers: { "sec-fetch-site": site },
      body: JSON.stringify({ title: "Accepted", expectedVersion: 8, idempotencyKey: `attempt-${site}` }),
    }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ error: { errorClass: "authorization", code: "cross_site_request" } });
    expect(gateway).not.toHaveBeenCalled();
  });

  it("accepts same-origin JSON without relying on the Content-Type header", async () => {
    const gateway = stubWorkGateway(async () =>
      gatewayOk({ task: taskView(), history: taskHistory(), replayed: false }),
    );
    const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
      method: "PATCH", headers: { origin: ORIGIN },
      body: JSON.stringify({ title: "Accepted", expectedVersion: 8, idempotencyKey: "attempt-no-content-type" }),
    }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(200);
  });

  it("accepts a Work GET without Origin", async () => {
    const gateway = stubWorkGateway(async () => gatewayOk({ tasks: [] }));
    const value = new NextRequest(`${ORIGIN}/api/tasks?pageSize=25`);
    value.cookies.set(SESSION_COOKIE_NAME, await cookie());
    const response = await listTasks(value);
    expect(response.status).toBe(200);
    expect(gateway).toHaveBeenCalledOnce();
  });

  it("sends integer and exact archive query values under gateway snake-case names", async () => {
    const sent: Record<string, unknown>[] = [];
    stubWorkGateway(async (_url, init) => { sent.push(JSON.parse(String(init?.body))); return gatewayOk({ tasks: [] }); });
    const response = await listTasks(request(await cookie(), "/api/tasks?pageSize=25&archived=only&workView=all-open"));
    expect(response.status).toBe(200);
    expect(sent[0]?.payload).toMatchObject({ page_size: 25, archive_mode: "only", work_view: "all-open" });
    expect(typeof (sent[0]?.payload as Record<string, unknown>).page_size).toBe("number");
  });

  it.each(["pageSize=1.5", "pageSize=ten", "includeArchived=yes"])("refuses malformed or obsolete %s before the gateway", async (query) => {
    const gateway = stubWorkGateway();
    const response = await listTasks(request(await cookie(), `/api/tasks?${query}`));
    expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
  });

  it.each([null, [], "text", 42, true])("refuses non-object JSON body %j before the gateway", async (body) => {
    const gateway = stubWorkGateway();
    const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    expect(await response.json()).toMatchObject({ error: { code: "bad_request" } });
  });

  it.each([null, [], {}, 42, true])(
    "refuses non-string Task title %j before the gateway",
    async (title) => {
      const gateway = stubWorkGateway();
      const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, expectedVersion: 8, idempotencyKey: "attempt-1" }),
      }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
      expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    },
  );

  it.each(["8", null, [], {}, true])(
    "refuses non-integer expectedVersion %j before the gateway",
    async (expectedVersion) => {
      const gateway = stubWorkGateway();
      const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: "Proposed", expectedVersion, idempotencyKey: "attempt-1" }),
      }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
      expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    },
  );

  it.each(["true", null, [], {}, 1])(
    "refuses non-boolean archived %j before the gateway",
    async (archived) => {
      const gateway = stubWorkGateway();
      const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ archived, expectedVersion: 8, idempotencyKey: "attempt-1" }),
      }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
      expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    },
  );

  it.each([null, "description", {}, [1], Array.from({ length: 8 }, (_, index) => `field-${index}`)])(
    "refuses malformed clearFields %j before the gateway",
    async (clearFields) => {
      const gateway = stubWorkGateway();
      const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ clearFields, expectedVersion: 8, idempotencyKey: "attempt-1" }),
      }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
      expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    },
  );

  it.each(["false", null, [], {}, 0])(
    "refuses non-boolean clearDueAt %j before the gateway",
    async (clearDueAt) => {
      const gateway = stubWorkGateway();
      const response = await patchCommitment(request(await cookie(), "/api/commitments/cmt_aaaaaaaa11111111", {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ clearDueAt, expectedVersion: 3, idempotencyKey: "attempt-2" }),
      }), { params: Promise.resolve({ commitmentId: "cmt_aaaaaaaa11111111" }) });
      expect(response.status).toBe(400); expect(gateway).not.toHaveBeenCalled();
    },
  );

  it("returns a sanitized same-Principal current Task beside a mutation conflict", async () => {
    const gateway = stubWorkGateway(async (url: string | URL | Request) => String(url).endsWith("tasks.update")
      ? new Response(JSON.stringify({ error: { code: "conflict", message: "task_id" } }), { status: 409, headers: { "content-type": "application/json" } })
      : gatewayOk({ task: { ...taskView(), principal_id: "prn_secret" } }));
    const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "Proposed", expectedVersion: 8, idempotencyKey: "attempt-1" }) }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(409); const body = await response.json();
    expect(body.current).toMatchObject({ task_id: "tsk_aaaaaaaa11111111", title: "Canonical", version: 9 });
    expect(JSON.stringify(body)).not.toContain("prn_secret"); expect(gateway).toHaveBeenCalledTimes(2);
  });

  it("does not synthesize a current Task when the identifier key is missing after decode", async () => {
    const gateway = stubWorkGateway(async (url: string | URL | Request) => String(url).endsWith("tasks.update")
      ? new Response(JSON.stringify({ error: { code: "conflict", message: "task_id" } }), { status: 409, headers: { "content-type": "application/json" } })
      : gatewayOk({ title: "Canonical", version: 9, principal_id: "prn_secret" }));
    const response = await patchTask(request(await cookie(), "/api/tasks/tsk_aaaaaaaa11111111", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "Proposed", expectedVersion: 8, idempotencyKey: "attempt-keyless" }) }), { params: Promise.resolve({ taskId: "tsk_aaaaaaaa11111111" }) });
    expect(response.status).toBe(409); const body = await response.json();
    expect(body.current).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("prn_secret"); expect(gateway).toHaveBeenCalledTimes(2);
  });

  it("returns a sanitized same-Principal current Commitment beside a mutation conflict", async () => {
    const gateway = stubWorkGateway(async (url: string | URL | Request) => String(url).endsWith("commitments.update")
      ? new Response(JSON.stringify({ error: { code: "conflict", message: "commitment_id" } }), { status: 409, headers: { "content-type": "application/json" } })
      : gatewayOk({
        commitment: { ...commitmentView(), principal_id: "prn_secret" },
        follow_up_task: null,
        counterparty_options: [],
        counterparty_options_truncated: false,
      }));
    const response = await patchCommitment(request(await cookie(), "/api/commitments/cmt_aaaaaaaa11111111", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ summary: "Proposed", expectedVersion: 3, idempotencyKey: "attempt-2" }) }), { params: Promise.resolve({ commitmentId: "cmt_aaaaaaaa11111111" }) });
    expect(response.status).toBe(409); const body = await response.json();
    expect(body.current).toMatchObject({ commitment_id: "cmt_aaaaaaaa11111111", title: "Canonical", version: 4 });
    expect(JSON.stringify(body)).not.toContain("prn_secret"); expect(gateway).toHaveBeenCalledTimes(2);
  });
});
