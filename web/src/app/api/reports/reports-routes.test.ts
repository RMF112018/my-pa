// @vitest-environment node
/**
 * Reports Modernization WP07 (contract U4, U5, U1 guard): the /api/reports BFF
 * routes against the real handlers. Only session resolution and the gateway's
 * HTTP transport (`fetch`) are stubbed; canonical successes come from the
 * Python-built fixtures (success.json and reports.standalone.json).
 *
 * The generic admission matrix for the success.json-covered capabilities is in
 * ../core-admission.test.ts; this file adds the standalone reads, the closed
 * nested objects, the plane rule, U5 `current` and the content-token rules.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { PrincipalSession } from "@/contracts/identity";
import contract from "@/contracts/gateway.json";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import { GET as catalog, POST as publish } from "./route";
import { GET as read } from "./[reportId]/route";
import { POST as update } from "./[reportId]/update/route";
import { POST as archive } from "./[reportId]/archive/route";
import { POST as del } from "./[reportId]/delete/route";
import { POST as restore } from "./[reportId]/restore/route";
import { GET as history } from "./[reportId]/history/route";
import { GET as content } from "./[reportId]/content/route";
import { POST as begin } from "./transfers/route";
import { POST as append } from "./transfers/[sessionId]/append/route";
import { POST as finalize } from "./transfers/[sessionId]/finalize/route";
import { POST as abort } from "./transfers/[sessionId]/abort/route";

const { resolveSessionPrincipal } = vi.hoisted(() => ({ resolveSessionPrincipal: vi.fn() }));
vi.mock("@/lib/auth/principal", () => ({
  resolveSessionPrincipal,
  AuthorityUnavailableError: class AuthorityUnavailableError extends Error {},
}));

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001", identityProvider: "synthetic",
  identitySubject: "synthetic:aaaa0001", displayName: "Synthetic operator",
  lifecycleState: "active", synthetic: true,
};
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-11-08T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false }, limitations: [], partial_result: false,
};
const ORIGIN = "http://localhost:3000";
const GATEWAY = "http://127.0.0.1:8000";
const reportId = `grpt_${"a".repeat(16)}`;
const sessionId = `grxfr_${"a".repeat(16)}`;
const TOKEN = `grxtk_${"0123456789abcdef".repeat(4)}`;
const SHA = "b".repeat(64);
const STANDALONE_READ = standalone["reports.read.no_body"] as Record<string, unknown>;

type ReportParams = { params: Promise<{ reportId: string }> };
type SessionParams = { params: Promise<{ sessionId: string }> };
const at = (id = reportId): ReportParams => ({ params: Promise.resolve({ reportId: id }) });
const session = (id = sessionId): SessionParams => ({ params: Promise.resolve({ sessionId: id }) });

const fetchStub = vi.fn<typeof fetch>();
const consoleError = vi.fn();

function answerWith(...bodies: { status?: number; body: unknown }[]) {
  for (const { status = 200, body } of bodies) {
    fetchStub.mockImplementationOnce(async () => new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    }));
  }
}
const ok = (result: unknown) => ({ body: { result, disclosure: DISCLOSURE } });
/** A Python ProblemDetail; the web tier keeps code and message and drops `safe_details`. */
const refused = (status: number, code: string, safeDetails: string[] = [], message = "safe_field") =>
  ({ status, body: { error: { code, message, safe_details: safeDetails } } });

function get(path: string) {
  return new NextRequest(new URL(path, ORIGIN), { method: "GET", headers: { origin: ORIGIN } });
}
function post(path: string, body?: unknown, origin = ORIGIN) {
  return new NextRequest(new URL(path, ORIGIN), {
    method: "POST", headers: { "content-type": "application/json", origin },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
async function answer(response: Response, status: number) {
  expect(response.status).toBe(status);
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  return response.json();
}
function call(index = 0) {
  const [url, init] = fetchStub.mock.calls[index]!;
  return { url, payload: JSON.parse(String(init!.body)).payload as Record<string, unknown> };
}
async function refusedBeforeGateway(response: Promise<Response>, status = 400) {
  const body = await answer(await response, status);
  expect(body.shape).toBeUndefined();
  expect(fetchStub).not.toHaveBeenCalled();
  return body;
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchStub.mockReset();
  vi.stubEnv("MYPA_GATEWAY_URL", GATEWAY);
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
  resolveSessionPrincipal.mockResolvedValue(PRINCIPAL);
  vi.stubGlobal("fetch", fetchStub);
  vi.spyOn(console, "error").mockImplementation(consoleError);
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

describe("GET /api/reports (plane-selected catalog)", () => {
  it("requires plane standalone|all before any gateway call", async () => {
    for (const query of ["", "?plane=intelligence", "?plane=", "?plane=Standalone", "?plane=all&plane=standalone"]) {
      await refusedBeforeGateway(catalog(get(`/api/reports${query}`)));
    }
  });
  it("lists the standalone plane through reports.list and decodes the standalone page", async () => {
    answerWith(ok(standalone["reports.list.standalone"]));
    const body = await answer(await catalog(get("/api/reports?plane=standalone")), 200);
    expect(fetchStub).toHaveBeenCalledTimes(1);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.list`, payload: { plane: "standalone" } });
    expect(body).toMatchObject({ shape: "backend", ...standalone["reports.list.standalone"] });
    expect(body.disclosure).toBeDefined();
  });
  it("sends plane all and decodes mixed-plane items", async () => {
    answerWith(ok(standalone["reports.list.all"]));
    const body = await answer(await catalog(get("/api/reports?plane=all")), 200);
    expect(call().payload).toEqual({ plane: "all" });
    expect(body.items.map((item: { plane: string }) => item.plane)).toEqual(
      standalone["reports.list.all"].items.map((item) => item.plane),
    );
  });
  it("searches through reports.search when query is present, mapping every filter", async () => {
    answerWith(ok(standalone["reports.search.all"]));
    const query = new URLSearchParams([
      ["plane", "all"], ["query", "synthetic"], ["type", "weekly_note"], ["topics", "a"], ["topics", "b"],
      ["tags", "t"], ["lifecycleStates", "active"], ["lifecycleStates", "archived"],
      ["createdFrom", "2026-11-01T00:00:00Z"], ["createdTo", "2026-11-08T00:00:00Z"],
      ["reportDateFrom", "2026-11-01"], ["reportDateTo", "2026-11-08"], ["pageSize", "10"], ["cursor", "opaque"],
    ]);
    await answer(await catalog(get(`/api/reports?${query}`)), 200);
    expect(call()).toEqual({
      url: `${GATEWAY}/v1/reports.search`,
      payload: {
        plane: "all", query: "synthetic", type: "weekly_note", topics: ["a", "b"], tags: ["t"],
        lifecycle_states: ["active", "archived"], created_from: "2026-11-01T00:00:00Z",
        created_to: "2026-11-08T00:00:00Z", report_date_from: "2026-11-01", report_date_to: "2026-11-08",
        page_size: 10, cursor: "opaque",
      },
    });
  });
  it("refuses pipeline filters, unknown fields, bad enums and bounds before dispatch", async () => {
    for (const extra of [
      "cycleRunId=micr_aaaaaaaa11111111", "stage=final", "createdBy=x", "associatedWith=x", "principalId=x",
      "lifecycleStates=purged", "lifecycleStates=active&lifecycleStates=active", "pageSize=0", "pageSize=101",
      "createdFrom=2026-11-01", "reportDateFrom=2026-11-01T00:00:00Z", "query=", "query=%20", "includeHeld=true",
    ]) {
      await refusedBeforeGateway(catalog(get(`/api/reports?plane=standalone&${extra}`)));
    }
  });
  it("answers 503 when the result is not a standalone page (legacy shape refused)", async () => {
    answerWith(ok(fixtures["reports.list"]));
    const body = await answer(await catalog(get("/api/reports?plane=standalone")), 503);
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });
  it("refuses an unauthenticated caller with zero gateway calls", async () => {
    resolveSessionPrincipal.mockResolvedValue(null);
    const body = await refusedBeforeGateway(catalog(get("/api/reports?plane=standalone")), 401);
    expect(body.error.code).toBe("unauthenticated");
  });
  it("passes gateway refusals through with class, status and code", async () => {
    answerWith(refused(400, "invalid_request"));
    const body = await answer(await catalog(get("/api/reports?plane=standalone")), 400);
    expect(body.error).toMatchObject({ errorClass: "validation", code: "invalid_request" });
  });
});

describe("GET /api/reports/[reportId] (standalone read)", () => {
  it("reads through reports.read with the mapped selectors", async () => {
    answerWith(ok(standalone["reports.read.markdown"]));
    const query = `versionNumber=1&includeBody=true&includeManifest=false&includeWithdrawn=true`;
    const body = await answer(await read(get(`/api/reports/${reportId}?${query}`), at()), 200);
    expect(call()).toEqual({
      url: `${GATEWAY}/v1/reports.read`,
      payload: { report_id: reportId, version_number: 1, include_body: true, include_manifest: false, include_withdrawn: true },
    });
    expect(body).toMatchObject({ shape: "backend", plane: "standalone", held: standalone["reports.read.markdown"].held });
  });
  it("refuses a pipeline, malformed or padded report id before dispatch", async () => {
    for (const id of ["rpt_aaaaaaaa11111111", "grpt_short", `${reportId} `, "bad"]) {
      await refusedBeforeGateway(read(get(`/api/reports/${id}`), at(id)));
    }
  });
  it("refuses unknown query fields before dispatch", async () => {
    for (const query of ["includeBytes=true", "principalId=x", "versionId=rpt_aaaaaaaa11111111", "versionNumber=0"]) {
      await refusedBeforeGateway(read(get(`/api/reports/${reportId}?${query}`), at()));
    }
  });
  it("answers 503 when the result is the legacy pipeline shape", async () => {
    answerWith(ok(fixtures["reports.read"]));
    const body = await answer(await read(get(`/api/reports/${reportId}`), at()), 503);
    expect(body.error.code).toBe("upstream_contract_invalid");
  });
  it("passes not_found through", async () => {
    answerWith(refused(404, "not_found", ["artifact_id"]));
    const body = await answer(await read(get(`/api/reports/${reportId}`), at()), 404);
    expect(body.error).toMatchObject({ errorClass: "not_found", code: "not_found" });
  });

  describe("WP08 C-WP07 R1 #4: identity keys in content.data", () => {
    const withData = (name: "reports.read.json" | "reports.read.mixed", data: unknown) => {
      const result = structuredClone(standalone[name]) as Record<string, unknown>;
      (result.content as Record<string, unknown>).data = data;
      return result;
    };
    it.each(["reports.read.json", "reports.read.mixed"] as const)(
      "%s: strips principal keys (no identity echo) and says so with identity_keys_withheld: true",
      async (name) => {
        answerWith(ok(withData(name, { rows: [{ principal_id: "p", keep: 1 }], meta: { principalId: "q" } })));
        const body = await answer(await read(get(`/api/reports/${reportId}?includeBody=true`), at()), 200);
        expect(body.identity_keys_withheld).toBe(true);
        expect(body.content.data).toEqual({ rows: [{ keep: 1 }], meta: {} });
        expect(JSON.stringify(body)).not.toMatch(/principal_?[iI]d/);
      },
    );
    it("leaves the flag off when the strip removes nothing from content.data (tid/oid are not stripped)", async () => {
      answerWith(ok(withData("reports.read.json", { tid: "t", oid: "o", rows: [1] })));
      const body = await answer(await read(get(`/api/reports/${reportId}?includeBody=true`), at()), 200);
      expect(body).not.toHaveProperty("identity_keys_withheld");
      expect(body.content.data).toEqual({ tid: "t", oid: "o", rows: [1] });
      answerWith(ok(standalone["reports.read.markdown"]));
      const plain = await answer(await read(get(`/api/reports/${reportId}`), at()), 200);
      expect(plain).not.toHaveProperty("identity_keys_withheld");
    });
    it("never flags a catalog page", async () => {
      answerWith(ok(standalone["reports.list.standalone"]));
      const body = await answer(await catalog(get("/api/reports?plane=standalone")), 200);
      expect(body).not.toHaveProperty("identity_keys_withheld");
    });
  });
});

describe("POST /api/reports (publish)", () => {
  const base = { title: "Synthetic", idempotencyKey: "k-1" };
  it("maps inline content for each format exactly", async () => {
    for (const [inline, sent] of [
      [{ format: "markdown", body: "# x" }, { format: "markdown", body: "# x" }],
      [{ format: "text", body: "x" }, { format: "text", body: "x" }],
      [{ format: "json", data: { a: [1] } }, { format: "json", data: { a: [1] } }],
      [{ format: "mixed", body: "x", data: null }, { format: "mixed", body: "x", data: null }],
    ] as const) {
      fetchStub.mockClear(); answerWith(ok(fixtures["reports.publish"]));
      await answer(await publish(post("/api/reports", { ...base, content: inline, topics: ["t"], tags: ["g"], summary: "s", reportDate: "2026-11-08", type: "note", clientIntentId: "intent-1" })), 200);
      expect(call()).toEqual({
        url: `${GATEWAY}/v1/reports.publish`,
        payload: { title: "Synthetic", content: sent, idempotency_key: "k-1", topics: ["t"], tags: ["g"], summary: "s", report_date: "2026-11-08", type: "note", client_intent_id: "intent-1" },
      });
    }
  });
  it("maps a staged transfer reference to the gateway spelling", async () => {
    answerWith(ok(fixtures["reports.publish"]));
    await answer(await publish(post("/api/reports", { ...base, content: { transfer: { sessionId, contentToken: TOKEN } } })), 200);
    expect(call().payload.content).toEqual({ transfer: { session_id: sessionId, content_token: TOKEN } });
  });
  it("refuses metadata, associations, coverage, encoding, principal and server fields before dispatch", async () => {
    const inline = { format: "markdown", body: "x" };
    for (const extra of [
      { metadata: {} }, { associations: [] }, { coverage_period: {} }, { coveragePeriod: {} },
      { principal_id: "prn_x" }, { principalId: "x" }, { reportId }, { report_id: reportId }, { purge: true },
      { idempotency_key: "k" }, { held: false },
    ]) {
      await refusedBeforeGateway(publish(post("/api/reports", { ...base, content: inline, ...extra })));
    }
  });
  it("refuses a principal key nested inside inline json/mixed content data before dispatch", async () => {
    for (const key of ["principal_id", "principalId", "tid", "oid"]) {
      for (const inline of [
        { format: "json", data: { [key]: "prn_x" } },
        { format: "json", data: { outer: [{ inner: { [key]: "prn_x" } }] } },
        { format: "mixed", body: "x", data: { [key]: "prn_x" } },
      ]) {
        await refusedBeforeGateway(publish(post("/api/reports", { ...base, content: inline })));
      }
    }
    answerWith(ok(fixtures["reports.publish"]));
    await answer(await publish(post("/api/reports", { ...base, content: { format: "json", data: { outer: [{ inner: { owner: "x" } }] } } })), 200);
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });
  it("refuses open or malformed content before dispatch, never echoing it", async () => {
    for (const bad of [
      { format: "markdown", body: "x", encoding: "identity" },
      { format: "markdown", encoding: "gzip+base64", encoded: "H4sI" },
      { format: "markdown" }, { format: "markdown", body: "x", data: {} }, { format: "json", body: "x" },
      { format: "json" }, { format: "mixed", body: "x" }, { format: "html", body: "x" }, { body: "x" },
      { format: "markdown", body: 1 }, "x", null, [],
      { transfer: { session_id: sessionId, content_token: TOKEN } },
      { transfer: { sessionId, contentToken: TOKEN, extra: 1 } },
      { transfer: { sessionId, contentToken: "grxtk_short" } },
      { transfer: { sessionId: "grxfr_bad", contentToken: TOKEN } },
      { transfer: { sessionId, contentToken: TOKEN }, format: "markdown" },
    ]) {
      const body = await refusedBeforeGateway(publish(post("/api/reports", { ...base, content: bad })));
      expect(JSON.stringify(body)).not.toContain(TOKEN);
    }
  });
  it("refuses cross-site and unauthenticated callers with zero gateway calls", async () => {
    const body = { ...base, content: { format: "text", body: "x" } };
    const cross = await refusedBeforeGateway(publish(post("/api/reports", body, "https://other.invalid")), 403);
    expect(cross.error.code).toBe("cross_site_request");
    resolveSessionPrincipal.mockResolvedValue(null);
    await refusedBeforeGateway(publish(post("/api/reports", body)), 401);
  });
  it("refuses any query on a mutation", async () => {
    await refusedBeforeGateway(publish(post("/api/reports?plane=standalone", { ...base, content: { format: "text", body: "x" } })));
  });
  it("never echoes a content token in a refusal or a log", async () => {
    answerWith(refused(400, "invalid_request", ["transfer"]));
    const body = await answer(await publish(post("/api/reports", { ...base, content: { transfer: { sessionId, contentToken: TOKEN } } })), 400);
    expect(JSON.stringify(body)).not.toContain(TOKEN);
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain(TOKEN);
  });
  it("does not attach current to a publish conflict", async () => {
    answerWith(refused(409, "conflict", ["idempotency_conflict"]));
    const body = await answer(await publish(post("/api/reports", { ...base, content: { format: "text", body: "x" } })), 409);
    expect(body.current).toBeUndefined();
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });
});

describe("POST /api/reports/[reportId]/update", () => {
  const base = { expectedVersion: 3, changeReason: "why", idempotencyKey: "k-2" };
  it("maps a closed patch and clearFields", async () => {
    answerWith(ok(fixtures["reports.update"]));
    await answer(await update(post(`/api/reports/${reportId}/update`, {
      ...base,
      patch: { title: "T", content: { transfer: { sessionId, contentToken: TOKEN } }, type: "note", topics: ["a"], tags: [], summary: "s", reportDate: "2026-11-08" },
      clearFields: ["reportDate", "type"],
    }), at()), 200);
    expect(call()).toEqual({
      url: `${GATEWAY}/v1/reports.update`,
      payload: {
        report_id: reportId, expected_version: 3, change_reason: "why", idempotency_key: "k-2",
        patch: { title: "T", content: { transfer: { session_id: sessionId, content_token: TOKEN } }, type: "note", topics: ["a"], tags: [], summary: "s", report_date: "2026-11-08" },
        clear_fields: ["report_date", "type"],
      },
    });
  });
  it("refuses a principal key nested inside patch content data before dispatch", async () => {
    for (const key of ["principal_id", "principalId", "tid", "oid"]) {
      for (const content of [
        { format: "json", data: { [key]: "prn_x" } },
        { format: "mixed", body: "x", data: { nested: { [key]: "prn_x" } } },
      ]) {
        await refusedBeforeGateway(update(post(`/api/reports/${reportId}/update`, { ...base, patch: { content } }), at()));
      }
    }
    answerWith(ok(fixtures["reports.update"]));
    await answer(await update(post(`/api/reports/${reportId}/update`, { ...base, patch: { content: { format: "json", data: { nested: { owner: "x" } } } } }), at()), 200);
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });
  it("refuses open patches and unknown clear fields before dispatch", async () => {
    for (const extra of [
      { patch: { metadata: {} } }, { patch: { associations: [] } }, { patch: { coverage_period: {} } },
      { patch: { report_date: "2026-11-08" } }, { patch: { title: null } }, { patch: { title: 1 } },
      { patch: { content: { format: "text", body: "x", encoding: "identity" } } }, { patch: { principalId: "x" } },
      { patch: "x" }, { patch: null }, { patch: {}, clearFields: ["coveragePeriod"] },
      { patch: {}, clearFields: ["title"] }, { patch: {}, clearFields: ["type", "type"] },
      { patch: {}, clear_fields: ["type"] }, { patch: {}, expectedVersion: 0 },
    ]) {
      await refusedBeforeGateway(update(post(`/api/reports/${reportId}/update`, { ...base, ...extra }), at()));
    }
    const missing = { ...base } as Record<string, unknown>;
    await refusedBeforeGateway(update(post(`/api/reports/${reportId}/update`, missing), at()));
  });
});

describe("U5: lifecycle and update conflicts carry `current`", () => {
  const routes = [
    ["reports.update", () => update(post(`/api/reports/${reportId}/update`, { expectedVersion: 1, patch: { title: "T" }, changeReason: "r", idempotencyKey: "k" }), at())],
    ["reports.archive", () => archive(post(`/api/reports/${reportId}/archive`, { expectedLifecycleRevision: 0, idempotencyKey: "k" }), at())],
    ["reports.delete", () => del(post(`/api/reports/${reportId}/delete`, { expectedLifecycleRevision: 0, idempotencyKey: "k", reason: "tidy" }), at())],
    ["reports.restore", () => restore(post(`/api/reports/${reportId}/restore`, { expectedLifecycleRevision: 1, idempotencyKey: "k" }), at())],
  ] as const;
  for (const [capability, run] of routes) {
    it(`${capability}: stale_version 409 answers the refusal unchanged plus one read's current`, async () => {
      const current: Record<string, unknown> = { ...STANDALONE_READ, report_id: reportId };
      answerWith(refused(409, "conflict", ["stale_version"], "the request conflicts"), ok(current));
      const body = await answer(await run(), 409);
      expect(body.error).toEqual({ errorClass: "conflict", code: "conflict", message: "the request conflicts" });
      expect(body.current).toEqual({
        headVersionNumber: current.head_version_number, headVersionId: current.head_version_id,
        lifecycleState: current.lifecycle_state, lifecycleRevision: current.lifecycle_revision, held: current.held,
      });
      expect(fetchStub).toHaveBeenCalledTimes(2);
      expect(call(0).url).toBe(`${GATEWAY}/v1/${capability}`);
      expect(call(1)).toEqual({
        url: `${GATEWAY}/v1/reports.read`,
        payload: { report_id: reportId, include_body: false, include_withdrawn: true },
      });
    });
    it(`${capability}: a failed or mismatched current read leaves the plain refusal`, async () => {
      for (const second of [refused(404, "not_found"), ok(fixtures["reports.read"]), ok({ ...STANDALONE_READ, report_id: `grpt_${"b".repeat(16)}` })]) {
        fetchStub.mockReset();
        answerWith(refused(409, "conflict", ["stale_version"]), second);
        const body = await answer(await run(), 409);
        expect(body.error.code).toBe("conflict");
        expect(body.current).toBeUndefined();
        expect(fetchStub).toHaveBeenCalledTimes(2);
      }
    });
    it(`${capability}: a non-409 refusal makes no second call`, async () => {
      answerWith(refused(403, "denied"));
      await answer(await run(), 403);
      expect(fetchStub).toHaveBeenCalledTimes(1);
    });
  }
  it("lifecycle routes map the closed body and refuse purge-ish fields", async () => {
    answerWith(ok(fixtures["reports.delete"]));
    await answer(await del(post(`/api/reports/${reportId}/delete`, { expectedLifecycleRevision: 2, idempotencyKey: "k", reason: "r" }), at()), 200);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.delete`, payload: { report_id: reportId, expected_lifecycle_revision: 2, idempotency_key: "k", reason: "r" } });
    fetchStub.mockReset();
    for (const extra of [{ purge: true }, { permanent: true }, { hold: true }, { expectedLifecycleRevision: -1 }, { reason: null }]) {
      await refusedBeforeGateway(del(post(`/api/reports/${reportId}/delete`, { expectedLifecycleRevision: 0, idempotencyKey: "k", ...extra }), at()));
    }
  });
});

describe("history and content reads", () => {
  it("history maps entries, page, cursor and flags", async () => {
    answerWith(ok(fixtures["reports.history"]));
    await answer(await history(get(`/api/reports/${reportId}/history?entries=lifecycle&pageSize=5&after=grlev_aaaaaaaa11111111&includeWithdrawn=true&includeManifests=false`), at()), 200);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.history`, payload: { report_id: reportId, entries: "lifecycle", page_size: 5, after: "grlev_aaaaaaaa11111111", include_withdrawn: true, include_manifests: false } });
    fetchStub.mockReset();
    for (const query of ["entries=all", "pageSize=51", "after=bad", "includeHeld=true"]) {
      await refusedBeforeGateway(history(get(`/api/reports/${reportId}/history?${query}`), at()));
    }
  });
  it("content requires exactly one version selector and maps the range", async () => {
    answerWith(ok(fixtures["reports.transfer.read_chunk"]));
    await answer(await content(get(`/api/reports/${reportId}/content?versionId=grver_aaaaaaaa11111111&part=original&offset=0&length=1024&includeWithdrawn=false`), at()), 200);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.transfer.read_chunk`, payload: { report_id: reportId, version_id: "grver_aaaaaaaa11111111", part: "original", offset: 0, length: 1024, include_withdrawn: false } });
    fetchStub.mockReset();
    for (const query of ["", "versionNumber=1&versionId=grver_aaaaaaaa11111111", "versionNumber=1&part=encoded", "versionNumber=1&offset=-1", "versionNumber=1&length=0"]) {
      await refusedBeforeGateway(content(get(`/api/reports/${reportId}/content?${query}`), at()));
    }
  });
});

describe("transfer routes", () => {
  it("begin fixes encoding identity and refuses a browser encoding", async () => {
    answerWith(ok(fixtures["reports.transfer.begin"]));
    await answer(await begin(post("/api/reports/transfers", { format: "mixed", byteCount: 600000, sha256: SHA, idempotencyKey: "k", ttlSeconds: 600 })), 200);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.transfer.begin`, payload: { format: "mixed", byte_count: 600000, sha256: SHA, idempotency_key: "k", ttl_seconds: 600, encoding: "identity" } });
    fetchStub.mockReset();
    for (const extra of [{ encoding: "identity" }, { encoding: "gzip+base64" }, { format: "html" }, { sha256: "B".repeat(64) }, { byteCount: 0 }, { sessionId }, { path: "/etc/passwd" }]) {
      await refusedBeforeGateway(begin(post("/api/reports/transfers", { format: "text", byteCount: 1, sha256: SHA, idempotencyKey: "k", ...extra })));
    }
  });
  it("append accepts a ~350 KB chunk body and maps it", async () => {
    const chunk = "QUFB".repeat(90_000); // 360,000 Base64 characters
    answerWith(ok(fixtures["reports.transfer.append"]));
    await answer(await append(post(`/api/reports/transfers/${sessionId}/append`, { sequence: 0, chunk, chunkSha256: SHA }), session()), 200);
    const { url, payload } = call();
    expect(url).toBe(`${GATEWAY}/v1/reports.transfer.append`);
    expect(payload).toEqual({ session_id: sessionId, sequence: 0, chunk, chunk_sha256: SHA });
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain("QUFB");
  });
  it("finalize answers the content token once, in its own body only", async () => {
    const result = { ...fixtures["reports.transfer.finalize"], content_token: TOKEN };
    answerWith(ok(result));
    const response = await finalize(post(`/api/reports/transfers/${sessionId}/finalize`), session());
    expect(response.headers.get("location")).toBeNull();
    const body = await answer(response, 200);
    expect(body.content_token).toBe(TOKEN);
    expect(JSON.stringify(body).split(TOKEN).length).toBe(2);
    expect(JSON.stringify(body.disclosure)).not.toContain(TOKEN);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.transfer.finalize`, payload: { session_id: sessionId } });
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain(TOKEN);
  });
  it("finalize/abort refuse bodies with fields, queries and malformed session ids", async () => {
    for (const [run, name] of [[finalize, "finalize"], [abort, "abort"]] as const) {
      await refusedBeforeGateway(run(post(`/api/reports/transfers/${sessionId}/${name}`, { sessionId }), session()));
      await refusedBeforeGateway(run(post(`/api/reports/transfers/${sessionId}/${name}?x=1`, {}), session()));
      for (const id of ["grxfr_short", reportId, `${sessionId}\n`]) {
        await refusedBeforeGateway(run(post(`/api/reports/transfers/${id}/${name}`, {}), session(id)));
      }
    }
  });
  it("abort dispatches exactly the session id", async () => {
    answerWith(ok(fixtures["reports.transfer.abort"]));
    await answer(await abort(post(`/api/reports/transfers/${sessionId}/abort`, {}), session()), 200);
    expect(call()).toEqual({ url: `${GATEWAY}/v1/reports.transfer.abort`, payload: { session_id: sessionId } });
  });
});

describe("U1 guard: the reports surface never reaches an operator-only capability", () => {
  const FORBIDDEN = /reports\.(?:hold|retention|purge)/;
  const here = dirname(fileURLToPath(import.meta.url));
  const appRoot = join(here, "../..");
  function files(directory: string): string[] {
    if (!existsSync(directory)) return [];
    return readdirSync(directory).flatMap((entry) => {
      const full = join(directory, entry);
      return statSync(full).isDirectory() ? files(full) : [full];
    });
  }
  it("gateway.json reports.* is exactly the legacy five plus the WP07 eleven", () => {
    const reports = Object.keys(contract.capabilities).filter((name) => name.startsWith("reports.")).sort();
    expect(reports).toEqual([
      "reports.archive", "reports.delete", "reports.history", "reports.latest", "reports.list",
      "reports.publish", "reports.read", "reports.resolve_set", "reports.restore", "reports.search",
      "reports.transfer.abort", "reports.transfer.append", "reports.transfer.begin",
      "reports.transfer.finalize", "reports.transfer.read_chunk", "reports.update",
    ]);
    expect(Object.keys(contract.capabilities).filter((name) => FORBIDDEN.test(name))).toEqual([]);
    expect(JSON.stringify(contract)).not.toMatch(FORBIDDEN);
  });
  it("no file under api/reports or (app)/reports mentions hold, retention or purge capabilities", () => {
    const scanned = [...files(join(appRoot, "api/reports")), ...files(join(appRoot, "(app)/reports"))]
      .filter((path) => !path.endsWith("reports-routes.test.ts"));
    expect(scanned.length).toBeGreaterThan(0);
    for (const path of scanned) expect(readFileSync(path, "utf8"), path).not.toMatch(FORBIDDEN);
  });
});
