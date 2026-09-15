// @vitest-environment node
/**
 * R01-WP05: the Project Controls settings route as HTTP.
 *
 * The first write this route family carries, so what is proved here is the
 * transport contract rather than a screen: which request is built from a route
 * segment and a three-name body, which requests are refused before a capability
 * is spent, that a Principal is never taken from the caller, that a foreign
 * Project is answered exactly as an unknown one is, and that a success whose
 * shape the decoder refuses becomes an unavailable rather than a half-trusted
 * answer.
 *
 * There is no settings UI at this work package and these cases assert none.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import {
  GET as status,
  POST as configure,
} from "@/app/api/project-controls/projects/[projectId]/settings/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const PROJECT = "prj_aaaaaaaa11111111";
const FOREIGN = "prj_bbbbbbbb22222222";
const ZONE = "America/New_York";
const KEY = "idk_aaaaaaaa11111111";

const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-09-02T15:00:00+00:00", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["principal_partition"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

/** The configured status payload, exactly as `_project_controls_status_payload` renders it. */
const CONFIGURED = {
  project_controls: {
    project_id: PROJECT,
    state: "configured",
    timezone_name: ZONE,
    settings_version: 3,
    settings_updated_at: "2026-09-02T15:00:00+00:00",
  },
};

/** The same five keys, with the four `configured`-only values null. */
const NOT_CONFIGURED = {
  project_controls: {
    project_id: PROJECT,
    state: "not_configured",
    timezone_name: null,
    settings_version: null,
    settings_updated_at: null,
  },
};

function configured(disposition: string, version = 1) {
  return {
    disposition,
    project_controls: {
      project_id: PROJECT,
      state: "configured",
      timezone_name: ZONE,
      settings_version: version,
      settings_updated_at: "2026-09-02T15:00:00+00:00",
    },
  };
}

function body(result: unknown, disclosure: unknown = DISCLOSURE) {
  return new Response(JSON.stringify({ result, disclosure }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/** A Python `ProblemDetail`, at the HTTP status `app.py` maps its code to. */
function problem(code: string, status: number, message = "refused") {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function cookie(principal = "synthetic-a") {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: principal }),
    }),
  );
  return (
    response as unknown as { cookies: { get(name: string): { value: string } } }
  ).cookies.get(SESSION_COOKIE_NAME).value;
}

function get(session: string | null, projectId = PROJECT) {
  const value = new NextRequest(
    `${ORIGIN}/api/project-controls/projects/${projectId}/settings`,
  );
  if (session) value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function post(
  session: string | null,
  payload: unknown,
  { projectId = PROJECT, origin = ORIGIN as string | null } = {},
) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin) headers.origin = origin;
  const value = new NextRequest(
    `${ORIGIN}/api/project-controls/projects/${projectId}/settings`,
    { method: "POST", headers, body: JSON.stringify(payload) },
  );
  if (session) value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

const params = (projectId = PROJECT) => Promise.resolve({ projectId });

type Sent = { readonly url: string; readonly document: Record<string, unknown> };

function stubGateway(impl?: (url: string) => unknown) {
  const sent: Sent[] = [];
  const inner = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    const href = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
    sent.push({ url: href, document: JSON.parse(String(init?.body)) as Record<string, unknown> });
    return impl ? impl(href) : body(CONFIGURED);
  });
  vi.stubGlobal("fetch", withSessionServiceFetch(inner as never));
  return { sent, inner };
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

describe("GET reports the Project's configuration state", () => {
  it("answers a configured Project with the five-key object and the read purpose", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => body(CONFIGURED));
    const response = await status(get(session), { params: params() });

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(sent[0].url).toBe("http://127.0.0.1:8000/v1/project_controls.status");
    expect(sent[0].document.purpose).toBe("constraint_read");
    expect(sent[0].document.payload).toEqual({ project_id: PROJECT });
    const answer = await response.json();
    expect(answer.projectControls).toEqual({
      projectId: PROJECT,
      state: "configured",
      timezoneName: ZONE,
      settingsVersion: 3,
      settingsUpdatedAt: "2026-09-02T15:00:00+00:00",
    });
  });

  it("answers an authorized Project with no settings row as a typed 200 not_configured", async () => {
    const session = await cookie();
    stubGateway(() => body(NOT_CONFIGURED));
    const response = await status(get(session), { params: params() });

    expect(response.status).toBe(200);
    const answer = await response.json();
    // An answer, not an absence: the state is named, and the four values it
    // governs are explicitly null rather than missing.
    expect(answer.projectControls).toEqual({
      projectId: PROJECT,
      state: "not_configured",
      timezoneName: null,
      settingsVersion: null,
      settingsUpdatedAt: null,
    });
  });

  it("derives the Principal from the session and never from the request", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => body(CONFIGURED));
    await status(get(session), { params: params() });
    expect(sent[0].document.principal_id).toEqual(expect.any(String));
    expect(sent[0].document.payload).toEqual({ project_id: PROJECT });
  });

  it("refuses every query parameter, because the status read takes none", async () => {
    const session = await cookie();
    const { inner } = stubGateway();
    for (const query of ["pageSize=5", "state=configured", "project_id=" + FOREIGN, "x=1"]) {
      const request = new NextRequest(
        `${ORIGIN}/api/project-controls/projects/${PROJECT}/settings?${query}`,
      );
      request.cookies.set(SESSION_COOKIE_NAME, session);
      const response = await status(request, { params: params() });
      expect(response.status, query).toBe(400);
      expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    }
    expect(inner).not.toHaveBeenCalled();
  });

  it("answers 401 without a session and never reaches the gateway", async () => {
    const { inner } = stubGateway();
    const response = await status(get(null), { params: params() });
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(inner).not.toHaveBeenCalled();
  });
});

describe("POST configures the Project's calendar", () => {
  it.each(["applied", "no_op", "replayed"])(
    "returns the %s disposition with the configured object",
    async (disposition) => {
      const session = await cookie();
      const { sent } = stubGateway(() => body(configured(disposition)));
      const response = await configure(
        post(session, { timezoneName: ZONE, idempotencyKey: KEY }),
        { params: params() },
      );

      expect(response.status).toBe(200);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(sent[0].url).toBe("http://127.0.0.1:8000/v1/project_controls.configure");
      expect(sent[0].document.purpose).toBe("constraint_authoring");
      const answer = await response.json();
      expect(answer.disposition).toBe(disposition);
      expect(answer.projectControls.state).toBe("configured");
      expect(answer.projectControls.timezoneName).toBe(ZONE);
    },
  );

  it("renames the three admitted fields and fixes project_id from the route", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => body(configured("applied", 2)));
    const response = await configure(
      post(session, { timezoneName: ZONE, idempotencyKey: KEY, expectedVersion: 1 }),
      { params: params() },
    );

    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      timezone_name: ZONE,
      idempotency_key: KEY,
      expected_version: 1,
    });
  });

  it("omits expected_version entirely when the caller does not send one", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => body(configured("applied")));
    await configure(post(session, { timezoneName: ZONE, idempotencyKey: KEY }), {
      params: params(),
    });
    // Omitted, not null: "I believe there is nothing here yet" is the absence of
    // the field, and a null would be a different request digest.
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      timezone_name: ZONE,
      idempotency_key: KEY,
    });
    expect(Object.keys(sent[0].document.payload as object)).not.toContain("expected_version");
  });

  it.each([
    ["a body Project that agrees with the URL", { project_id: PROJECT }],
    ["a body Project that disagrees with the URL", { project_id: FOREIGN }],
    ["the camelCase spelling", { projectId: FOREIGN }],
    ["a client context", { clientContext: "settings-screen" }],
    ["a correlation id", { correlationId: "corr_1" }],
    ["the gateway spelling of an admitted field", { timezone_name: ZONE }],
    ["an unrelated field", { anything: 1 }],
  ])("refuses %s as an unknown field, before a capability is spent", async (_name, extra) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await configure(
      post(session, { timezoneName: ZONE, idempotencyKey: KEY, ...extra }),
      { params: params() },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(["principal_id", "principalId", "tid", "oid"])(
    "rejects the caller-supplied identity field %s with 400 and no gateway call",
    async (field) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await configure(
        post(session, { timezoneName: ZONE, idempotencyKey: KEY, [field]: "syn-bbbb0002" }),
        { params: params() },
      );
      expect(response.status).toBe(400);
      expect(await response.json()).toMatchObject({
        error: { code: "caller_supplied_principal" },
      });
      expect(inner).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["a non-string timezone", { timezoneName: 5, idempotencyKey: KEY }],
    ["a non-integer expected version", { timezoneName: ZONE, idempotencyKey: KEY, expectedVersion: 1.5 }],
    ["a string expected version", { timezoneName: ZONE, idempotencyKey: KEY, expectedVersion: "1" }],
    ["a non-string idempotency key", { timezoneName: ZONE, idempotencyKey: 7 }],
  ])("refuses %s with 400 before a capability is spent", async (_name, payload) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await configure(post(session, payload), { params: params() });
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([
    ["a missing timezone", { idempotencyKey: KEY }],
    ["a missing idempotency key", { timezoneName: ZONE }],
  ])("invents no default for %s and lets the command refuse it", async (_name, payload) => {
    const session = await cookie();
    // The allowlist declares which names are admitted, not which are required.
    // `ConfigureProjectControls` is what requires a timezone and a key, and the
    // point of this case is that the BFF supplies neither on the caller's
    // behalf: a key this layer invented would make replay protection a property
    // of the transport rather than of the caller.
    const { sent } = stubGateway(() =>
      problem("invalid_request", 400, "a required field was missing"),
    );
    const response = await configure(post(session, payload), { params: params() });
    expect(response.status).toBe(400);
    const forwarded = sent[0].document.payload as Record<string, unknown>;
    expect(forwarded.project_id).toBe(PROJECT);
    expect(Object.keys(forwarded).sort()).toEqual(
      Object.keys({ project_id: PROJECT, ...("idempotencyKey" in payload ? { idempotency_key: KEY } : { timezone_name: ZONE }) }).sort(),
    );
  });

  it("refuses a cross-site POST with 403 before the session is read", async () => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await configure(
      post(session, { timezoneName: ZONE, idempotencyKey: KEY }, { origin: "https://evil.test" }),
      { params: params() },
    );
    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "cross_site_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it("refuses a cross-site POST even without a session, and reveals nothing else", async () => {
    const { inner } = stubGateway();
    const response = await configure(
      post(null, { timezoneName: ZONE, idempotencyKey: KEY }, { origin: "https://evil.test" }),
      { params: params() },
    );
    expect(response.status).toBe(403);
    expect(inner).not.toHaveBeenCalled();
  });

  it("answers 401 without a session and never reaches the gateway", async () => {
    const { inner } = stubGateway();
    const response = await configure(post(null, { timezoneName: ZONE, idempotencyKey: KEY }), {
      params: params(),
    });
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(inner).not.toHaveBeenCalled();
  });
});

describe("the route segment is validated before a capability is spent", () => {
  it.each([
    ["not-an-id"],
    ["cst_aaaaaaaa11111111"],
    ["prj_short"],
    ["prj_aaaaaaaa1111!111"],
    ["PRJ_aaaaaaaa11111111"],
  ])("refuses the project segment %s on GET with 400", async (projectId) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await status(get(session, projectId), { params: params(projectId) });
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const answer = await response.json();
    expect(answer).toMatchObject({ error: { code: "invalid_request" } });
    // Nothing about the rejected value is echoed back.
    expect(JSON.stringify(answer)).not.toContain(projectId);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([["not-an-id"], ["prj_short"], ["cst_aaaaaaaa11111111"]])(
    "refuses the project segment %s on POST with 400",
    async (projectId) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await configure(
        post(session, { timezoneName: ZONE, idempotencyKey: KEY }, { projectId }),
        { params: params(projectId) },
      );
      expect(response.status).toBe(400);
      expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
      expect(inner).not.toHaveBeenCalled();
    },
  );
});

describe("a Project the Principal may not see is answered as an unknown one", () => {
  /**
   * The landed Python maps unknown, deleted and foreign Projects to one code —
   * `unavailable` — which `adapters/http/app.py` serves as 503. The external
   * answer is therefore identical for all three, which is the nondisclosure
   * guarantee §14 requires: no status, body or error code distinguishes a
   * Project that never existed from one belonging to another Principal.
   *
   * Plan §15 requires exactly this. As amended on 2026-09-15 by
   * `PC-CM-D02-PLAN-REVISION-20260915-001`, it reads that foreign, unknown,
   * deleted and inaccessible Projects and transient failure alike answer with
   * a nondisclosing 503, per §14, and that the transport does not distinguish
   * them. Its earlier text asked for 404 here; the plan was corrected to match
   * this behavior rather than the behavior changed to match the plan. (That
   * artifact lives outside this repository and cannot be found by grepping the
   * tree.) The BFF could not produce a 404 anyway without telling a foreign
   * Project from a transient failure, and those are one code by design.
   */
  it.each([
    ["an unknown Project", PROJECT],
    ["a foreign Project", FOREIGN],
    ["a deleted Project", "prj_cccccccc33333333"],
  ])("answers %s identically and names nothing", async (_name, projectId) => {
    const session = await cookie();
    stubGateway(() => problem("unavailable", 503, "the Project is unavailable"));
    const response = await status(get(session, projectId), { params: params(projectId) });

    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const answer = await response.json();
    expect(answer).toMatchObject({
      state: "unavailable",
      error: { errorClass: "unavailable", code: "unavailable" },
    });
    const serialized = JSON.stringify(answer);
    expect(serialized).not.toContain(projectId);
    expect(serialized).not.toContain("timezone");
    expect(serialized).not.toContain("settings_version");
  });

  it("gives byte-identical answers for an unknown and a foreign Project", async () => {
    const session = await cookie();
    stubGateway(() => problem("unavailable", 503, "the Project is unavailable"));
    const first = await status(get(session, PROJECT), { params: params(PROJECT) });
    const second = await status(get(session, FOREIGN), { params: params(FOREIGN) });
    expect(first.status).toBe(second.status);
    expect(JSON.stringify(await first.json())).toBe(JSON.stringify(await second.json()));
  });

  it("refuses a configure against a Project the Principal may not see, the same way", async () => {
    const session = await cookie();
    stubGateway(() => problem("unavailable", 503, "the Project is unavailable"));
    const response = await configure(
      post(session, { timezoneName: ZONE, idempotencyKey: KEY }, { projectId: FOREIGN }),
      { params: params(FOREIGN) },
    );
    expect(response.status).toBe(503);
    expect(JSON.stringify(await response.json())).not.toContain(FOREIGN);
  });
});

describe("typed backend refusals reach the browser without disclosure", () => {
  it("passes an expectedVersion conflict through as 409", async () => {
    const session = await cookie();
    const response = await (async () => {
      stubGateway(() => problem("conflict", 409, "the expected version did not match"));
      return configure(
        post(session, { timezoneName: ZONE, idempotencyKey: KEY, expectedVersion: 1 }),
        { params: params() },
      );
    })();
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "conflict", code: "conflict" },
    });
  });

  it("passes an idempotency-key conflict through as 409 without echoing the key", async () => {
    const session = await cookie();
    stubGateway(() => problem("conflict", 409, "the idempotency key was reused"));
    const response = await configure(
      post(session, { timezoneName: ZONE, idempotencyKey: KEY }),
      { params: params() },
    );
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toContain(KEY);
  });

  it("passes an invalid IANA timezone through as 400 without echoing the name", async () => {
    const session = await cookie();
    const bad = "Mars/Olympus_Mons";
    stubGateway(() => problem("invalid_request", 400, "the timezone name was not accepted"));
    const response = await configure(
      post(session, { timezoneName: bad, idempotencyKey: KEY }),
      { params: params() },
    );
    expect(response.status).toBe(400);
    const answer = await response.json();
    expect(answer).toMatchObject({
      error: { errorClass: "validation", code: "invalid_request" },
    });
    expect(JSON.stringify(answer)).not.toContain(bad);
  });

  it("sends the same idempotency key onward unchanged, so a replay is the backend's to decide", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => body(configured("replayed", 4)));
    const first = await configure(post(session, { timezoneName: ZONE, idempotencyKey: KEY }), {
      params: params(),
    });
    const second = await configure(post(session, { timezoneName: ZONE, idempotencyKey: KEY }), {
      params: params(),
    });
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    // Two identical requests: the BFF neither deduplicates nor rewrites the key.
    expect(sent[0].document.payload).toEqual(sent[1].document.payload);
    expect((sent[0].document.payload as Record<string, unknown>).idempotency_key).toBe(KEY);
  });

  it("answers 503 authority_unavailable when the session authority cannot answer", async () => {
    const session = await cookie();
    stubGateway();
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const response = await status(get(session), { params: params() });
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: { code: "authority_unavailable" } });
  });
});

describe("a malformed settings success fails closed at the route", () => {
  const MALFORMED: readonly (readonly [string, unknown])[] = [
    ["an empty result object", {}],
    ["a missing project_controls object", { disposition: "applied" }],
    ["an unknown state", { project_controls: { ...CONFIGURED.project_controls, state: "enabled" } }],
    [
      "a configured row with a null timezone",
      { project_controls: { ...CONFIGURED.project_controls, timezone_name: null } },
    ],
    [
      "a not_configured row carrying a version",
      { project_controls: { ...NOT_CONFIGURED.project_controls, settings_version: 2 } },
    ],
    [
      "a version sent as a string",
      { project_controls: { ...CONFIGURED.project_controls, settings_version: "3" } },
    ],
    [
      "a missing settings_updated_at",
      { project_controls: { ...CONFIGURED.project_controls, settings_updated_at: undefined } },
    ],
    [
      "a missing project_id",
      { project_controls: { ...CONFIGURED.project_controls, project_id: undefined } },
    ],
  ];

  it.each(MALFORMED)("turns %s into 503 upstream_contract_invalid on GET", async (_name, result) => {
    const session = await cookie();
    stubGateway(() => body(result));
    const response = await status(get(session), { params: params() });
    expect(response.status).toBe(503);
    const answer = await response.json();
    expect(answer).toMatchObject({
      state: "unavailable",
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
    expect(JSON.stringify(answer)).not.toContain("timezoneName");
  });

  it.each([
    ["a missing disposition", { project_controls: CONFIGURED.project_controls }],
    [
      "the rejected disposition, which this capability never returns",
      { disposition: "rejected", project_controls: CONFIGURED.project_controls },
    ],
    [
      "an unknown disposition",
      { disposition: "updated", project_controls: CONFIGURED.project_controls },
    ],
    [
      "a not_configured state on a configure answer",
      { disposition: "applied", project_controls: NOT_CONFIGURED.project_controls },
    ],
    [
      "a null timezone on a configure answer",
      {
        disposition: "applied",
        project_controls: { ...CONFIGURED.project_controls, timezone_name: null },
      },
    ],
  ])("turns %s into 503 upstream_contract_invalid on POST", async (_name, result) => {
    const session = await cookie();
    stubGateway(() => body(result));
    const response = await configure(post(session, { timezoneName: ZONE, idempotencyKey: KEY }), {
      params: params(),
    });
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
  });

  it("strips a principal_id the backend should never have sent", async () => {
    const session = await cookie();
    stubGateway(() =>
      body({
        project_controls: { ...CONFIGURED.project_controls },
        principal_id: "syn-aaaa0001",
      }),
    );
    const response = await status(get(session), { params: params() });
    expect(response.status).toBe(200);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).not.toContain("principal_id");
    expect(serialized).not.toContain("syn-aaaa0001");
  });
});
