// @vitest-environment node
/**
 * R01-WP09 S3: the two bounded structured field types and the pre-dispatch hooks.
 *
 * `workPost` is exercised directly with the Constraint authoring field maps,
 * because the routes that will carry them do not exist yet and because what is
 * under test is the transport, not a route: which bodies are refused before a
 * capability is spent, what an admitted body becomes on the wire, and where in
 * the order the `validate` and `admit` hooks run. The harness is the one the
 * Constraint route tests use — a real session cookie through `/api/session` and
 * an outbound `fetch` stubbed at the Response level — so the Principal on every
 * gateway document is the one the session resolved, never one a test wrote.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { workGet, workPost, isAwareRfc3339, isCanonicalId, isCanonicalTimezoneKey, type AdmissionContext } from "@/lib/api/work-route";
import {
  CATEGORY_REORDER_FIELDS,
  CONSTRAINT_CREATE_DRAFT_FIELDS,
  CONSTRAINT_TRANSITION_FIELDS,
  CONSTRAINT_UPDATE_FIELDS,
  SETTINGS_FIELDS,
  validateCategoryReorder,
} from "@/app/api/project-controls/constraint-requests";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const PROJECT = "prj_aaaaaaaa11111111";
const CONSTRAINT = "cst_aaaaaaaa11111111";
const CATEGORY_A = "ccat_aaaaaaaa11111111";
const CATEGORY_B = "ccat_bbbbbbbb22222222";
const CATEGORY_C = "ccat_cccccccc33333333";
const GATEWAY = "http://127.0.0.1:8000/v1/";
const PYTHON = JSON.parse(
  readFileSync(join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json"), "utf8"),
) as Record<string, unknown>;

const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["principal_partition"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

function success(capability: string) {
  return new Response(JSON.stringify({ result: PYTHON[capability], disclosure: DISCLOSURE }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

async function cookie() {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
    }),
  );
  return (
    response as unknown as { cookies: { get(name: string): { value: string } } }
  ).cookies.get(SESSION_COOKIE_NAME).value;
}

function post(session: string, payload: unknown) {
  const value = new NextRequest(`${ORIGIN}/api/work-route-under-test`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: ORIGIN },
    body: JSON.stringify(payload),
  });
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

type Sent = { readonly url: string; readonly document: Record<string, unknown> };

/** Every gateway call, answered with the committed Python success for its capability. */
function stubGateway(impl?: (url: string) => Response) {
  const sent: Sent[] = [];
  const inner = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    const href = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
    sent.push({ url: href, document: JSON.parse(String(init?.body)) as Record<string, unknown> });
    return impl ? impl(href) : success(href.slice(GATEWAY.length));
  });
  vi.stubGlobal("fetch", withSessionServiceFetch(inner as never));
  return { sent };
}

beforeEach(() => {
  resetSessionRegistry();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubGlobal(
    "fetch",
    withSessionServiceFetch(() => {
      throw new Error("no gateway stub was installed for this test");
    }),
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A Draft create carrying `bic`, the simplest map with a PartyRef array. */
async function createDraft(bic: unknown) {
  const session = await cookie();
  const gateway = stubGateway();
  const response = await workPost(
    post(session, { bic, idempotencyKey: "key-00000001" }),
    "work-route-test",
    "constraints.create",
    CONSTRAINT_CREATE_DRAFT_FIELDS,
    { project_id: PROJECT },
  );
  return { response, ...gateway };
}

async function expectRefused(response: NextResponse, sent: readonly Sent[]) {
  expect(response.status).toBe(400);
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect((await response.json()).error.code).toBe("invalid_request");
  expect(sent).toEqual([]);
}

describe("party-ref-array", () => {
  it("serializes each admitted kind to the gateway spelling, in order, duplicates kept", async () => {
    const { response, sent } = await createDraft([
      { kind: "unresolved", label: "  Steel  sub " },
      { kind: "principal" },
      { kind: "entity", entityId: "ent_aaaaaaaa11111111" },
      { kind: "entity", entityId: "ent_aaaaaaaa11111111", label: "Acme" },
      { kind: "entity", entityId: "ent_bbbbbbbb22222222", label: null },
      { kind: "principal", entityId: null, label: null },
      { kind: "unresolved", label: "  Steel  sub " },
    ]);
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toBe(`${GATEWAY}constraints.create`);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      idempotency_key: "key-00000001",
      bic: [
        // The label is the one that arrived, whitespace and all: trim() is
        // consulted only to refuse an all-whitespace label, never to rewrite.
        { kind: "unresolved", entity_id: null, label: "  Steel  sub " },
        { kind: "principal", entity_id: null, label: null },
        { kind: "entity", entity_id: "ent_aaaaaaaa11111111", label: null },
        { kind: "entity", entity_id: "ent_aaaaaaaa11111111", label: "Acme" },
        { kind: "entity", entity_id: "ent_bbbbbbbb22222222", label: null },
        { kind: "principal", entity_id: null, label: null },
        { kind: "unresolved", entity_id: null, label: "  Steel  sub " },
      ],
    });
  });

  it("admits an empty array and exactly 32 parties", async () => {
    const empty = await createDraft([]);
    expect(empty.response.status).toBe(200);
    expect(empty.sent[0].document.payload).toMatchObject({ bic: [] });
    const full = await createDraft(Array.from({ length: 32 }, () => ({ kind: "principal" })));
    expect(full.response.status).toBe(200);
    expect((full.sent[0].document.payload as { bic: unknown[] }).bic).toHaveLength(32);
  });

  it.each([
    ["an unknown key", [{ kind: "principal", role: "owner" }]],
    ["the gateway spelling of a key", [{ kind: "entity", entity_id: "ent_aaaaaaaa11111111" }]],
    ["a principal with a label", [{ kind: "principal", label: "Me" }]],
    ["a principal with an entityId", [{ kind: "principal", entityId: "ent_aaaaaaaa11111111" }]],
    ["an entity without an entityId", [{ kind: "entity", label: "Acme" }]],
    ["an entity with a blank entityId", [{ kind: "entity", entityId: "   " }]],
    ["an entity with a numeric entityId", [{ kind: "entity", entityId: 7 }]],
    [
      "an entity with a whitespace label",
      [{ kind: "entity", entityId: "ent_aaaaaaaa11111111", label: " \t " }],
    ],
    ["an unresolved party without a label", [{ kind: "unresolved" }]],
    ["an unresolved party with a whitespace label", [{ kind: "unresolved", label: "   " }]],
    ["an unresolved party with an empty label", [{ kind: "unresolved", label: "" }]],
    [
      "an unresolved party with an entityId",
      [{ kind: "unresolved", entityId: "ent_aaaaaaaa11111111", label: "Acme" }],
    ],
    ["an unknown kind", [{ kind: "team", label: "Acme" }]],
    ["a missing kind", [{ label: "Acme" }]],
    ["a non-object member", ["principal"]],
    ["an array member", [[{ kind: "principal" }]]],
    ["a non-array value", { kind: "principal" }],
    ["33 parties", Array.from({ length: 33 }, () => ({ kind: "principal" }))],
  ])("refuses %s with 400 and no gateway call", async (_label, bic) => {
    const { response, sent } = await createDraft(bic);
    await expectRefused(response, sent);
  });
});

describe("integer-array and the reorder cross-field check", () => {
  async function reorder(body: Record<string, unknown>) {
    const session = await cookie();
    const gateway = stubGateway();
    const response = await workPost(
      post(session, { idempotencyKey: "key-00000001", ...body }),
      "work-route-test",
      "constraint_categories.reorder",
      CATEGORY_REORDER_FIELDS,
      { project_id: PROJECT },
      { validate: validateCategoryReorder },
    );
    return { response, ...gateway };
  }

  it("forwards both arrays in order, with repeated versions kept", async () => {
    const { response, sent } = await reorder({
      orderedCategoryIds: [CATEGORY_C, CATEGORY_A, CATEGORY_B],
      expectedVersions: [3, 0, 3],
    });
    expect(response.status).toBe(200);
    expect(sent[0].url).toBe(`${GATEWAY}constraint_categories.reorder`);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      ordered_category_ids: [CATEGORY_C, CATEGORY_A, CATEGORY_B],
      expected_versions: [3, 0, 3],
      idempotency_key: "key-00000001",
    });
  });

  it("admits 64 members", async () => {
    const ids = Array.from({ length: 64 }, (_, index) => `ccat_${String(index).padStart(8, "0")}`);
    const { response } = await reorder({
      orderedCategoryIds: ids,
      expectedVersions: ids.map(() => 1),
    });
    expect(response.status).toBe(200);
  });

  it.each([
    ["a negative version", [CATEGORY_A], [-1]],
    ["a fractional version", [CATEGORY_A], [1.5]],
    ["a string version", [CATEGORY_A], ["1"]],
    ["a null version", [CATEGORY_A], [null]],
    ["an unsafe integer", [CATEGORY_A], [2 ** 53]],
    ["a non-array versions value", [CATEGORY_A], 1],
    [
      "65 versions",
      Array.from({ length: 65 }, (_, index) => `ccat_${String(index).padStart(8, "0")}`),
      Array.from({ length: 65 }, () => 1),
    ],
    ["an empty id list", [], []],
    ["a repeated id", [CATEGORY_A, CATEGORY_A], [1, 1]],
    ["an id that is not a Category id", [CONSTRAINT], [1]],
    ["fewer versions than ids", [CATEGORY_A, CATEGORY_B], [1]],
    ["more versions than ids", [CATEGORY_A], [1, 1]],
    ["absent versions", [CATEGORY_A], undefined],
  ])("refuses %s with 400 and no gateway call", async (_label, ids, versions) => {
    const { response, sent } = await reorder({
      orderedCategoryIds: ids,
      expectedVersions: versions,
    });
    await expectRefused(response, sent);
  });
});

describe("bounded scalars", () => {
  async function transition(body: Record<string, unknown>) {
    const session = await cookie();
    const gateway = stubGateway();
    const response = await workPost(
      post(session, body),
      "work-route-test",
      "constraints.transition",
      CONSTRAINT_TRANSITION_FIELDS,
      { constraint_id: CONSTRAINT },
    );
    return { response, ...gateway };
  }

  it("admits version 0 and a 128-character key", async () => {
    const key = "k".repeat(128);
    const { response, sent } = await transition({
      expectedVersion: 0,
      toState: "pending",
      idempotencyKey: key,
    });
    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({
      constraint_id: CONSTRAINT,
      expected_version: 0,
      to_state: "pending",
      idempotency_key: key,
    });
  });

  it.each([
    ["a negative expectedVersion", { expectedVersion: -1 }],
    ["a fractional expectedVersion", { expectedVersion: 1.5 }],
    ["an unsafe expectedVersion", { expectedVersion: 2 ** 53 }],
    ["a string expectedVersion", { expectedVersion: "2" }],
    ["a 129-character key", { idempotencyKey: "k".repeat(129) }],
    ["a non-active target", { toState: "closed" }],
    ["an upper-case target", { toState: "PENDING" }],
    ["a body Project", { projectId: PROJECT }],
    ["a body gateway Project", { project_id: PROJECT }],
    ["a client context", { clientContext: "x" }],
    ["a correlation id", { correlationId: "x" }],
    ["a capability", { capability: "constraints.update" }],
  ])("refuses %s with 400 and no gateway call", async (_label, override) => {
    const { response, sent } = await transition({
      expectedVersion: 1,
      toState: "pending",
      ...override,
    });
    await expectRefused(response, sent);
  });

  it("refuses clearing project_id, which would detach a Draft from its Project", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await workPost(
      post(session, { expectedVersion: 1, clearFields: ["project_id"] }),
      "work-route-test",
      "constraints.update",
      CONSTRAINT_UPDATE_FIELDS,
      { constraint_id: CONSTRAINT },
    );
    await expectRefused(response, sent);
  });

  it("leaves a map that sets no minimum exactly as permissive as before", async () => {
    // The settings map predates `minimum` and does not set it, so a negative
    // version still travels and the backend remains the one to refuse it.
    const session = await cookie();
    const { sent } = stubGateway(() => success("project_controls.configure"));
    await workPost(
      post(session, { timezoneName: "America/New_York", expectedVersion: -1 }),
      "work-route-test",
      "project_controls.configure",
      SETTINGS_FIELDS,
      { project_id: PROJECT },
    );
    expect(sent).toHaveLength(1);
    expect(sent[0].document.payload).toMatchObject({ expected_version: -1 });
  });
});

describe("the pre-dispatch admit hook", () => {
  const BODY = { expectedVersion: 2, toState: "pending", idempotencyKey: "key-00000001" };

  async function transition(
    admit: (context: AdmissionContext) => Promise<NextResponse | null>,
    body: Record<string, unknown> = BODY,
  ) {
    const session = await cookie();
    const gateway = stubGateway();
    const response = await workPost(
      post(session, body),
      "work-route-test",
      "constraints.transition",
      CONSTRAINT_TRANSITION_FIELDS,
      { constraint_id: CONSTRAINT },
      { admit },
    );
    return { response, ...gateway };
  }

  it("short-circuits: a returned response is the answer and the mutation is never sent", async () => {
    const admit = vi.fn(async () =>
      NextResponse.json({ error: { code: "refused_by_admission" } }, { status: 418 }),
    );
    const { response, sent } = await transition(admit);
    expect(admit).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(418);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toEqual({ error: { code: "refused_by_admission" } });
    expect(sent).toEqual([]);
  });

  it("proceeds on null, handing the hook the final payload and the session Principal", async () => {
    let seen: AdmissionContext | undefined;
    const { response, sent } = await transition(async (context) => {
      seen = context;
      return null;
    });
    expect(response.status).toBe(200);
    expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraints.transition`]);
    expect(seen?.payload).toEqual({
      constraint_id: CONSTRAINT,
      expected_version: 2,
      to_state: "pending",
      idempotency_key: "key-00000001",
    });
    expect(seen?.principal).toBeDefined();
  });

  it("binds the hook's read to the mutation's own Principal", async () => {
    const { response, sent } = await transition(async (context) => {
      const read = await context.read("constraints.read", { constraint_id: CONSTRAINT });
      expect(read.ok).toBe(true);
      return null;
    });
    expect(response.status).toBe(200);
    expect(sent.map((call) => call.url)).toEqual([
      `${GATEWAY}constraints.read`,
      `${GATEWAY}constraints.transition`,
    ]);
    expect(sent[0].document.principal_id).toEqual(expect.any(String));
    expect(sent[0].document.principal_id).toBe(sent[1].document.principal_id);
  });

  it("renders a refusal through `refuse` exactly as the mutation's own refusal", async () => {
    const error = { errorClass: "not_found", code: "not_found", message: "x" } as const;
    const viaHook = await transition(async (context) => context.refuse(404, error));
    expect(viaHook.sent).toEqual([]);
    const session = await cookie();
    stubGateway(
      () =>
        new Response(
          JSON.stringify({ error: { code: "not_found", message: "x" } }),
          { status: 404, headers: { "content-type": "application/json" } },
        ),
    );
    const viaGateway = await workPost(
      post(session, BODY),
      "work-route-test",
      "constraints.transition",
      CONSTRAINT_TRANSITION_FIELDS,
      { constraint_id: CONSTRAINT },
    );
    expect(viaHook.response.status).toBe(viaGateway.status);
    expect(viaHook.response.headers.get("cache-control")).toBe(
      viaGateway.headers.get("cache-control"),
    );
    const hookAnswer = await viaHook.response.json();
    const gatewayAnswer = await viaGateway.json();
    expect(Object.keys(hookAnswer).sort()).toEqual(Object.keys(gatewayAnswer).sort());
    expect(hookAnswer.state).toBe(gatewayAnswer.state);
    expect(hookAnswer.error).toEqual(gatewayAnswer.error);
    expect(hookAnswer.disclosure).toEqual(gatewayAnswer.disclosure);
  });

  it("is never called for a body that fails field validation", async () => {
    const admit = vi.fn(async () => null);
    const { response, sent } = await transition(admit, { ...BODY, expectedVersion: -1 });
    await expectRefused(response, sent);
    expect(admit).not.toHaveBeenCalled();
  });

  it("is never called for a body that fails the cross-field check", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const admit = vi.fn(async () => null);
    const response = await workPost(
      post(session, { orderedCategoryIds: [CATEGORY_A], expectedVersions: [] }),
      "work-route-test",
      "constraint_categories.reorder",
      CATEGORY_REORDER_FIELDS,
      { project_id: PROJECT },
      { validate: validateCategoryReorder, admit },
    );
    await expectRefused(response, sent);
    expect(admit).not.toHaveBeenCalled();
  });

  it("is never called when this build will not dispatch to the backend", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const admit = vi.fn(async () => null);
    const { response, sent } = await transition(admit);
    expect(response.status).toBe(501);
    expect(admit).not.toHaveBeenCalled();
    expect(sent).toEqual([]);
  });
});

describe("WP03B closed shared request validation", () => {
  it.each([
    [{}, { text: { gateway: "text", type: "string", required: true } }],
    [{ toString: "untrusted" }, {}],
    [{ text: null }, { text: { gateway: "text", type: "string" } }],
    [{ text: " " }, { text: { gateway: "text", type: "string", nonBlank: true } }],
    [{ key: "short" }, { key: { gateway: "idempotency_key", type: "string", minLength: 8 } }],
    [{ version: Number.MAX_SAFE_INTEGER + 1 }, { version: { gateway: "expected_version", type: "integer" } }],
    [{ version: 101 }, { version: { gateway: "expected_version", type: "integer", maximum: 100 } }],
    [{ enabled: "true" }, { enabled: { gateway: "enabled", type: "boolean" } }],
    [{ at: "2026-02-30T12:00:00Z" }, { at: { gateway: "start_at", type: "string", format: "timestamp" } }],
    [{ at: "2026-01-01T12:00:00" }, { at: { gateway: "start_at", type: "string", format: "timestamp" } }],
    [{ id: "cap_aaaaaaaa11111111" }, { id: { gateway: "project_id", type: "string", pattern: /^prj_[A-Za-z0-9]{8,64}$/ } }],
    [{ ids: ["mdoc_aaaaaaaa11111111", "mdoc_aaaaaaaa11111111"] }, { ids: { gateway: "ids", type: "string-array", uniqueItems: true } }],
  ] as const)("refuses invalid closed input before dispatch (%j)", async (payload, fields) => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await workPost(post(session, payload), "validation", "capture.create", fields);
    await expectRefused(response, sent);
  });

  it.each([
    [{ displayName: "Synthetic", unexpected: true }],
    [{ displayName: "   " }],
    [{ email: "one@example.invalid", isOrganizer: "true" }],
    [{ entityId: "prj_aaaaaaaa11111111" }],
    [{ displayName: "Same" }, { displayName: " Same " }],
    [{ email: "STRASSE@example.invalid" }, { email: "straße@example.invalid" }],
    [{ email: "οσ@example.invalid" }, { email: "ος@example.invalid" }],
    [{ displayName: "One", isOrganizer: true }, { displayName: "Two", isOrganizer: true }],
    [{ entityId: "ent_aaaaaaaa11111111" }, { entityId: "ent_aaaaaaaa11111111" }],
  ])("refuses invalid nested/set-level attendees (%j)", async (...members) => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await workPost(post(session, { attendees: members }), "attendees", "meetings.update", {
      attendees: { gateway: "attendees_replace", type: "attendee-array", maxItems: 100 },
    });
    await expectRefused(response, sent);
  });

  it("rejects query input on strict writes before dispatch", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const request = new NextRequest(`${ORIGIN}/api/capture?principalId=untrusted`, {
      method: "POST", headers: { origin: ORIGIN, "content-type": "application/json" }, body: "{}",
    });
    request.cookies.set(SESSION_COOKIE_NAME, session);
    await expectRefused(await workPost(request, "strict", "capture.create", {}, {}, { strictQuery: true }), sent);
  });

  it("preserves omission and explicit nullable values separately", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const fields = {
      text: { gateway: "text", type: "string", required: true },
      idempotencyKey: { gateway: "idempotency_key", type: "string", required: true },
      occurredAt: { gateway: "occurred_at", type: "string", nullable: true, format: "timestamp" },
    } as const;
    const response = await workPost(post(session, { text: "Synthetic", idempotencyKey: "key-00000001", occurredAt: null }), "nullable", "capture.create", fields);
    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({ text: "Synthetic", idempotency_key: "key-00000001", occurred_at: null });
    const omitted = await workPost(post(session, { text: "Synthetic", idempotencyKey: "key-00000002" }), "nullable", "capture.create", fields);
    expect(omitted.status).toBe(200);
    expect(sent[1].document.payload).not.toHaveProperty("occurred_at");
  });

  it("applies a safe request-bound result projection without changing canonical input", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await workPost(post(session, { text: "Synthetic", idempotencyKey: "key-00000001" }), "projection", "capture.create", {
      text: { gateway: "text", type: "string" }, idempotencyKey: { gateway: "idempotency_key", type: "string" },
    }, {}, { project: (result) => Object.fromEntries(Object.entries(result).filter(([key]) => key !== "idempotency_key")) });
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).not.toHaveProperty("idempotency_key");
    expect((sent[0].document.payload as Record<string, unknown>).idempotency_key).toBe("key-00000001");
  });
});


describe("WP03B scalar query and instant boundaries", () => {
  it.each(["2026-02-30T12:00:00Z", "2025-02-29T12:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z", "2026-01-01T00:00:60Z", "2026-01-01T00:00:00+24:00", "2026-01-01T00:00:00+01:60", "0000-01-01T00:00:00Z", "2026-01-01T12:00:00"])("rejects invalid instant %s", (value) => {
    expect(isAwareRfc3339(value)).toBe(false);
  });
  it.each(["2024-02-29T12:00:00Z", "2026-01-01T12:00:00.123456+05:30"])("accepts aware valid instant %s", (value) => {
    expect(isAwareRfc3339(value)).toBe(true);
  });
  it("uses exact identifier kind and suffix bounds", () => {
    expect(isCanonicalId("prj_aaaaaaaa11111111", "prj")).toBe(true);
    expect(isCanonicalId("cap_aaaaaaaa11111111", "prj")).toBe(false);
    expect(isCanonicalId("prj_short", "prj")).toBe(false);
    expect(isCanonicalId("prj_aaaaaaaa11111111\n", "prj")).toBe(false);
    expect(isCanonicalId("prj_aaaaaaaa_11111111", "prj")).toBe(false);
  });
  it.each(["pageSize=25&pageSize=25", "unknown=value", "pageSize=null", "pageSize=9007199254740992"])("rejects strict query %s", async (query) => {
    const session = await cookie();
    const { sent } = stubGateway();
    const request = new NextRequest(`${ORIGIN}/api/capture?${query}`);
    request.cookies.set(SESSION_COOKIE_NAME, session);
    const response = await workGet(request, "query", "capture.list", {
      pageSize: { gateway: "page_size", type: "integer", minimum: 1, maximum: 100 },
    }, {}, { strictQuery: true });
    await expectRefused(response, sent);
  });
});


describe("WP03B canonical timezone key boundary", () => {
  it.each(["UTC", "Factory", "posix/UTC", "America/New_York", "Etc/GMT+5", "Well_Shaped/Unknown_Zone"])("admits safe host-dependent key %s", (value) => {
    expect(isCanonicalTimezoneKey(value)).toBe(true);
  });
  it.each([null, 1, "", " UTC", "UTC\n", "\u0085UTC", "UTC\u001c", "/UTC", "../UTC", "posix/../UTC", "./UTC", "posix//UTC", "UTC/", "posix\\\\UTC", "UTC\u0000", "a".repeat(65)])("rejects malformed key %j", (value) => {
    expect(isCanonicalTimezoneKey(value)).toBe(false);
  });
  it("counts Python code points and does not consult an Intl semantic registry", () => {
    expect(isCanonicalTimezoneKey("😀".repeat(64))).toBe(true);
    expect(isCanonicalTimezoneKey("😀".repeat(65))).toBe(false);
  });
  it.each(["Factory", "posix/UTC", "Well_Shaped/Unknown_Zone"])("forwards %s unchanged for canonical backend validation", async (timezoneName) => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await workPost(post(session, { timezoneName }), "timezone", "meetings.update", {
      timezoneName: { gateway: "timezone_name", type: "string", format: "timezone" },
    });
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect((sent[0].document.payload as Record<string, unknown>).timezone_name).toBe(timezoneName);
  });
});
