// @vitest-environment node
/**
 * T08-05 / T08-06 / T08-11: the five Constraint read routes as HTTP.
 *
 * What is proved here is transport, not UI: which requests are built, which are
 * refused before a capability is spent, what a malformed success becomes, and
 * that every answer is `private, no-store` and carries a Principal the browser
 * never supplied.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as register } from "@/app/api/project-controls/projects/[projectId]/constraints/route";
import { GET as detail } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/route";
import { GET as history } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/history/route";
import { GET as overview } from "@/app/api/project-controls/projects/[projectId]/constraints/overview/route";
import { GET as categories } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const PROJECT = "prj_aaaaaaaa11111111";
const CONSTRAINT = "cst_aaaaaaaa11111111";
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

function success(capability: string, disclosure: unknown = DISCLOSURE) {
  return new Response(JSON.stringify({ result: PYTHON[capability], disclosure }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function body(result: unknown, disclosure: unknown = DISCLOSURE) {
  return new Response(JSON.stringify({ result, disclosure }), {
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

function get(session: string | null, path: string) {
  const value = new NextRequest(`${ORIGIN}${path}`);
  if (session) value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

type Sent = { readonly url: string; readonly document: Record<string, unknown> };

function stubGateway(impl?: (url: string, init?: RequestInit) => unknown) {
  const sent: Sent[] = [];
  const inner = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    const href = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
    sent.push({ url: href, document: JSON.parse(String(init?.body)) as Record<string, unknown> });
    return impl ? impl(href, init) : body({});
  });
  vi.stubGlobal("fetch", withSessionServiceFetch(inner as never));
  return { sent, inner };
}

/**
 * The resolved route parameters, shaped for whichever handler is under test.
 *
 * The cast is to the widest of the five handlers' parameter types; a handler
 * that names fewer segments simply ignores the extra one, exactly as Next.js
 * does.
 */
const params = (extra: Record<string, string> = {}) =>
  Promise.resolve({ projectId: PROJECT, ...extra }) as Promise<{
    projectId: string;
    constraintId: string;
  }>;

beforeEach(() => {
  resetSessionRegistry();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  // Sign-in itself reaches the Python session service over the same global
  // `fetch`, so one is installed before any test asks for a cookie.
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

describe("route to capability mapping", () => {
  it("answers the five canonical routes from the six read capabilities", async () => {
    const session = await cookie();
    const { sent } = stubGateway((url) => {
      const capability = url.split("/v1/")[1];
      return success(capability);
    });
    const answers = [
      await register(get(session, `/api/project-controls/projects/${PROJECT}/constraints`), {
        params: params(),
      }),
      await register(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints?q=steel`),
        { params: params() },
      ),
      await detail(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}`),
        { params: params({ constraintId: CONSTRAINT }) },
      ),
      await history(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}/history`),
        { params: params({ constraintId: CONSTRAINT }) },
      ),
      await overview(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints/overview`),
        { params: params() },
      ),
      await categories(
        get(session, `/api/project-controls/projects/${PROJECT}/constraint-categories`),
        { params: params() },
      ),
    ];
    expect(answers.map((response) => response.status)).toEqual([200, 200, 200, 200, 200, 200]);
    expect(sent.map((call) => call.url)).toEqual([
      "http://127.0.0.1:8000/v1/constraints.list",
      "http://127.0.0.1:8000/v1/constraints.search",
      "http://127.0.0.1:8000/v1/constraints.read",
      "http://127.0.0.1:8000/v1/constraints.read",
      "http://127.0.0.1:8000/v1/constraints.history",
      "http://127.0.0.1:8000/v1/constraints.overview",
      "http://127.0.0.1:8000/v1/constraint_categories.list",
    ]);
    for (const response of answers) {
      expect(response.headers.get("cache-control")).toBe("private, no-store");
    }
  });

  it("states the constraint_read purpose and a Principal the browser never sent", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.overview"));
    await overview(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints/overview`),
      { params: params() },
    );
    expect(sent[0].document.purpose).toBe("constraint_read");
    expect(sent[0].document.principal_id).toEqual(expect.any(String));
    expect(String(sent[0].document.principal_id)).not.toContain("syn-aaaa0001");
    expect(sent[0].document.payload).toEqual({ project_id: PROJECT });
  });

  it("sends the constraint id alone for a detail read, resolving the Project backend-side", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.read"));
    await detail(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}`),
      { params: params({ constraintId: CONSTRAINT }) },
    );
    expect(sent[0].document.payload).toEqual({ constraint_id: CONSTRAINT });
  });

  it("refuses same-Principal detail when the Constraint belongs to another Project", async () => {
    const session = await cookie();
    const foreignProject = "prj_bbbbbbbb22222222";
    const foreignDetail = structuredClone(PYTHON["constraints.read"]) as {
      constraint: Record<string, unknown>;
    };
    foreignDetail.constraint.project_id = foreignProject;
    const { sent } = stubGateway(() => body(foreignDetail));

    const response = await detail(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}`),
      { params: params({ constraintId: CONSTRAINT }) },
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const responseBody = await response.json();
    expect(responseBody).toEqual({
      error: {
        errorClass: "not_found",
        code: "not_found",
        message: "Constraint was not found",
      },
    });
    expect(sent.map((call) => call.url)).toEqual([
      "http://127.0.0.1:8000/v1/constraints.read",
    ]);
    const serialized = JSON.stringify(responseBody);
    expect(serialized).not.toContain(foreignProject);
    expect(serialized).not.toContain(CONSTRAINT);
    expect(serialized).not.toContain("relationships");
    expect(serialized).not.toContain("evidenceLinks");
  });
});

describe("route parameters are validated before a capability is spent", () => {
  it.each([
    ["not-an-id"],
    ["cst_aaaaaaaa11111111"],
    ["prj_short"],
    ["prj_aaaaaaaa1111!111"],
    ["PRJ_aaaaaaaa11111111"],
  ])("refuses the project segment %s with 400 and no gateway call", async (projectId) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await register(
      get(session, `/api/project-controls/projects/${projectId}/constraints`),
      { params: Promise.resolve({ projectId }) },
    );
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(["prj_aaaaaaaa11111111", "cst_short", "nope"])(
    "refuses the constraint segment %s with 400 and no gateway call",
    async (constraintId) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await detail(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints/${constraintId}`),
        { params: params({ constraintId }) },
      );
      expect(response.status).toBe(400);
      expect(inner).not.toHaveBeenCalled();
    },
  );
});

describe("the query allowlist is closed", () => {
  it("renames every Register filter to the command's own field name", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.list"));
    const query = [
      "scope=all",
      "status=identified",
      "status=on_hold",
      "category=ccat_aaaaaaaa11111111",
      "bic=principal",
      "responsible=unresolved",
      "sync=conflict",
      "quality=legacy_incomplete",
      "overdue=true",
      "dueSoon=false",
      "inMyCourt=true",
      "needsAttention=true",
      "recent=recently_changed",
      "sort=due_date",
      "dir=desc",
      "group=status",
      "pageSize=25",
      "cursor=opaque-cursor",
    ].join("&");
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints?${query}`),
      { params: params() },
    );
    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      scope: "all",
      statuses: ["identified", "on_hold"],
      category_ids: ["ccat_aaaaaaaa11111111"],
      bic_party_refs: ["principal"],
      responsible_party_refs: ["unresolved"],
      sync_states: ["conflict"],
      record_qualities: ["legacy_incomplete"],
      overdue: true,
      due_soon: false,
      my_court: true,
      needs_attention: true,
      recent: "recently_changed",
      sort: "due_date",
      // `sort_order`, deliberately not `direction`.
      sort_order: "desc",
      grouping: "status",
      limit: 25,
      cursor: "opaque-cursor",
    });
  });

  it.each([
    "direction=desc",
    "principal_id=syn-bbbb0002",
    "principalId=syn-bbbb0002",
    "project_id=prj_bbbbbbbb22222222",
    "limit=25",
    "statuses=open",
    "anything=1",
  ])("refuses the undeclared Register parameter %s", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints?${query}`),
      { params: params() },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([
    "scope=everything",
    "status=reopen",
    "sync=partial",
    "sync=workbook_unavailable",
    "quality=unknown",
    "recent=last_week",
    "sort=title",
    "dir=descending",
    "group=owner",
    "overdue=yes",
    "pageSize=1.5",
    "pageSize=ten",
  ])("refuses the out-of-vocabulary Register value %s", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints?${query}`),
      { params: params() },
    );
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it("applies the narrower search allowlist on the q branch", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.search"));
    const response = await register(
      get(
        session,
        `/api/project-controls/projects/${PROJECT}/constraints?q=steel&scope=closed&pageSize=10&cursor=c1`,
      ),
      { params: params() },
    );
    expect(response.status).toBe(200);
    expect(sent[0].url).toBe("http://127.0.0.1:8000/v1/constraints.search");
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      query: "steel",
      scope: "closed",
      limit: 10,
      cursor: "c1",
    });
  });

  it.each([
    "status=identified",
    "category=ccat_aaaaaaaa11111111",
    "bic=principal",
    "responsible=unresolved",
    "sync=in_sync",
    "quality=normal",
    "overdue=true",
    "dueSoon=true",
    "inMyCourt=true",
    "needsAttention=true",
    "recent=recently_closed",
    "sort=code",
    "dir=asc",
    "group=category",
  ])("refuses %s alongside a search term rather than dropping it", async (filter) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints?q=steel&${filter}`),
      { params: params() },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it("treats an empty q as no term, which then refuses q as undeclared", async () => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints?q=`),
      { params: params() },
    );
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it("admits only pageSize and cursor on history, renaming pageSize to page_size", async () => {
    const session = await cookie();
    const { sent } = stubGateway((url) => success(url.split("/v1/")[1]));
    const response = await history(
      get(
        session,
        `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}/history?pageSize=5&cursor=h1`,
      ),
      { params: params({ constraintId: CONSTRAINT }) },
    );
    expect(response.status).toBe(200);
    expect(sent.map((call) => call.document.payload)).toEqual([
      { constraint_id: CONSTRAINT },
      {
      constraint_id: CONSTRAINT,
      page_size: 5,
      cursor: "h1",
      },
    ]);
  });

  it("refuses same-Principal history when the Constraint belongs to another Project", async () => {
    const session = await cookie();
    const foreignProject = "prj_bbbbbbbb22222222";
    const foreignDetail = structuredClone(PYTHON["constraints.read"]) as {
      constraint: Record<string, unknown>;
    };
    foreignDetail.constraint.project_id = foreignProject;
    const { sent } = stubGateway((url) => {
      const capability = url.split("/v1/")[1];
      return capability === "constraints.read"
        ? body(foreignDetail)
        : success(capability);
    });
    const response = await history(
      get(
        session,
        `/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}/history?pageSize=5`,
      ),
      { params: params({ constraintId: CONSTRAINT }) },
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const responseBody = await response.json();
    expect(responseBody).toMatchObject({ error: { code: "not_found" } });
    expect(sent.map((call) => call.url)).toEqual([
      "http://127.0.0.1:8000/v1/constraints.read",
    ]);
    expect(JSON.stringify(responseBody)).not.toContain(foreignProject);
  });

  it("admits only the closed state filter on categories, renaming state to states", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraint_categories.list"));
    const response = await categories(
      get(
        session,
        `/api/project-controls/projects/${PROJECT}/constraint-categories?state=active&state=inactive`,
      ),
      { params: params() },
    );
    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      states: ["active", "inactive"],
    });
  });

  it.each(["state=deleted", "states=active", "pageSize=5"])(
    "refuses the categories parameter %s",
    async (query) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await categories(
        get(session, `/api/project-controls/projects/${PROJECT}/constraint-categories?${query}`),
        { params: params() },
      );
      expect(response.status).toBe(400);
      expect(inner).not.toHaveBeenCalled();
    },
  );

  it.each(["scope=open", "pageSize=5", "q=steel"])(
    "refuses %s on the Overview, which takes no query at all",
    async (query) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await overview(
        get(session, `/api/project-controls/projects/${PROJECT}/constraints/overview?${query}`),
        { params: params() },
      );
      expect(response.status).toBe(400);
      expect(inner).not.toHaveBeenCalled();
    },
  );
});

describe("session behaviour is 401 or 503, never a silent empty page", () => {
  it("answers 401 without a session and never reaches the gateway", async () => {
    const { inner } = stubGateway();
    const response = await register(
      get(null, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: params() },
    );
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it("answers 503 authority_unavailable when the session authority cannot answer", async () => {
    const session = await cookie();
    stubGateway();
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const response = await overview(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints/overview`),
      { params: params() },
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: { code: "authority_unavailable" } });
  });
});

describe("malformed Constraint success fails closed at the route", () => {
  const MALFORMED: readonly (readonly [string, string, unknown])[] = [
    ["a missing authoritative boolean", "constraints.list", { constraints: [{}] }],
    [
      "a boolean sent as a string",
      "constraints.list",
      { constraints: [{ ...(structuredClone(PYTHON["constraints.list"]) as { constraints: Record<string, unknown>[] }).constraints[0], is_overdue: "false" }] },
    ],
    ["an unknown status", "constraints.list", { constraints: [{ ...(structuredClone(PYTHON["constraints.list"]) as { constraints: Record<string, unknown>[] }).constraints[0], status: "reopen" }] }],
    ["a malformed party array", "constraints.list", { constraints: [{ ...(structuredClone(PYTHON["constraints.list"]) as { constraints: Record<string, unknown>[] }).constraints[0], bic: ["principal"] }] }],
    ["an unknown sync state", "constraints.list", { constraints: [{ ...(structuredClone(PYTHON["constraints.list"]) as { constraints: Record<string, unknown>[] }).constraints[0], sync_state: "partial" }] }],
    ["a missing version", "constraints.list", { constraints: [{ ...(structuredClone(PYTHON["constraints.list"]) as { constraints: Record<string, unknown>[] }).constraints[0], version: undefined }] }],
    ["an empty result object", "constraints.list", {}],
  ];

  it.each(MALFORMED)("turns %s into 503 unavailable / upstream_contract_invalid", async (_name, _capability, result) => {
    const session = await cookie();
    stubGateway(() => body(result));
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: params() },
    );
    expect(response.status).toBe(503);
    const answer = await response.json();
    expect(answer).toMatchObject({
      state: "unavailable",
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
    expect(JSON.stringify(answer)).not.toContain("constraints");
  });

  it.each([
    ["averageOpenAge", { averageOpenAge: 4 }],
    ["synchronizationHealth", { synchronizationHealth: { state: "in_sync" } }],
  ])("turns the forbidden Overview alias %s into 503 upstream_contract_invalid", async (_name, alias) => {
    const session = await cookie();
    const original = structuredClone(PYTHON["constraints.overview"]) as {
      overview: Record<string, unknown>;
    };
    stubGateway(() => body({ overview: { ...original.overview, ...alias } }));
    const response = await overview(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints/overview`),
      { params: params() },
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
  });

  it("turns a malformed continuation cursor into 503 upstream_contract_invalid", async () => {
    const session = await cookie();
    stubGateway(() =>
      success("constraints.list", {
        ...DISCLOSURE,
        truncation: { is_truncated: true, next_cursor: 7 },
      }),
    );
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: params() },
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
  });

  it("does not convert an unavailable capability into an empty Register", async () => {
    const session = await cookie();
    stubGateway(
      () =>
        new Response(
          JSON.stringify({ error: { code: "unsupported", message: "capability unavailable" } }),
          { status: 503, headers: { "content-type": "application/json" } },
        ),
    );
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: params() },
    );
    expect(response.status).toBeGreaterThanOrEqual(500);
    const answer = await response.json();
    expect(answer.constraints).toBeUndefined();
    expect(answer.state).not.toBe("ok");
  });
});
