// @vitest-environment node
/**
 * T08-05 / T08-06 / T08-11: the five Constraint read routes as HTTP.
 * R01-WP09: the thirteen Constraint and Category authoring routes as HTTP.
 *
 * What is proved here is transport, not UI: which requests are built, which are
 * refused before a capability is spent, what a malformed success becomes, and
 * that every answer is `private, no-store` and carries a Principal the browser
 * never supplied. The trust-boundary cases for the authoring routes (Origin,
 * session, Principal injection, exact-Project admission) live in
 * `constraint-security.test.ts`.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as register } from "@/app/api/project-controls/projects/[projectId]/constraints/route";
import { GET as detail } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/route";
import { GET as history } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/history/route";
import { GET as overview } from "@/app/api/project-controls/projects/[projectId]/constraints/overview/route";
import {
  GET as categories,
  POST as createCategory,
} from "@/app/api/project-controls/projects/[projectId]/constraint-categories/route";
import { POST as createPublished } from "@/app/api/project-controls/projects/[projectId]/constraints/route";
import { POST as createDraft } from "@/app/api/project-controls/projects/[projectId]/constraints/drafts/route";
import { PATCH as updateConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/route";
import { POST as publishConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/publish/route";
import { POST as transitionConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/transition/route";
import { POST as closeConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/close/route";
import { POST as closeFollowUp } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/close-follow-up/route";
import { POST as voidConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/void/route";
import { POST as reopenConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/reopen/route";
import { PATCH as updateCategory } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/[categoryId]/route";
import { POST as deactivateCategory } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/[categoryId]/deactivate/route";
import { POST as reorderCategories } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/reorder/route";
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

// --- R01-WP09: the thirteen authoring routes ---------------------------------

const CATEGORY = "ccat_aaaaaaaa11111111";
const CATEGORY_2 = "ccat_bbbbbbbb22222222";
const KEY = "idk_aaaaaaaa11111111";
const GATEWAY = "http://127.0.0.1:8000/v1/";
const BASE = `/api/project-controls/projects/${PROJECT}`;

type Handler = (request: NextRequest, context: { params: Promise<never> }) => Promise<Response>;

/** One authoring route: how it is asked, and exactly what it must send onward. */
type AuthoringRoute = {
  readonly method: "POST" | "PATCH";
  readonly path: string;
  readonly handler: Handler;
  readonly params: Record<string, string>;
  readonly capability: string;
  readonly admission: "constraint" | "category" | null;
  readonly body: Record<string, unknown>;
  readonly payload: Record<string, unknown>;
};

/** Browser parties, and the gateway document each serializes to. */
const BIC = [{ kind: "principal" }];
const BIC_OUT = [{ kind: "principal", entity_id: null, label: null }];
const RESPONSIBLE = [
  { kind: "entity", entityId: "ent_aaaaaaaa11111111", label: "Pat" },
  { kind: "unresolved", label: "  Steel subcontractor " },
];
const RESPONSIBLE_OUT = [
  { kind: "entity", entity_id: "ent_aaaaaaaa11111111", label: "Pat" },
  // Wording travels byte for byte: nothing trims it.
  { kind: "unresolved", entity_id: null, label: "  Steel subcontractor " },
];

const AUTHORED = {
  categoryId: CATEGORY,
  description: "Steel delivery access",
  dateIdentified: "2026-09-01",
  dueDate: "2026-09-15",
  reference: "RFI-014",
  currentUpdate: "Gate keys issued",
  bic: BIC,
  responsible: RESPONSIBLE,
};
const AUTHORED_OUT = {
  category_id: CATEGORY,
  description: "Steel delivery access",
  date_identified: "2026-09-01",
  due_date: "2026-09-15",
  reference: "RFI-014",
  current_update: "Gate keys issued",
  bic: BIC_OUT,
  responsible: RESPONSIBLE_OUT,
};

function route(
  method: AuthoringRoute["method"],
  suffix: string,
  handler: unknown,
  params: Record<string, string>,
  capability: string,
  admission: AuthoringRoute["admission"],
  body: Record<string, unknown>,
  payload: Record<string, unknown>,
): AuthoringRoute {
  return {
    method,
    path: `${BASE}${suffix}`,
    handler: handler as Handler,
    params: { projectId: PROJECT, ...params },
    capability,
    admission,
    body: { ...body, idempotencyKey: KEY },
    payload: { ...payload, idempotency_key: KEY },
  };
}

const C = { constraintId: CONSTRAINT };
const G = { categoryId: CATEGORY };

/** Artifact 17 §5, one row per route. */
const AUTHORING: readonly AuthoringRoute[] = [
  route("POST", "/constraints", createPublished, {}, "constraints.create_published", null,
    { ...AUTHORED, toState: "pending" },
    { project_id: PROJECT, ...AUTHORED_OUT, to_state: "pending" }),
  route("POST", "/constraints/drafts", createDraft, {}, "constraints.create", null,
    AUTHORED,
    { project_id: PROJECT, ...AUTHORED_OUT }),
  route("PATCH", `/constraints/${CONSTRAINT}`, updateConstraint, C, "constraints.update", "constraint",
    { expectedVersion: 3, description: "Revised", bic: BIC, clearFields: ["due_date", "reference"] },
    { constraint_id: CONSTRAINT, expected_version: 3, description: "Revised", bic: BIC_OUT, clear_fields: ["due_date", "reference"] }),
  route("POST", `/constraints/${CONSTRAINT}/publish`, publishConstraint, C, "constraints.publish", "constraint",
    { expectedVersion: 1, toState: "identified", categoryId: CATEGORY, dateIdentified: "2026-09-01", dueDate: "2026-09-15", bic: BIC, responsible: RESPONSIBLE },
    { constraint_id: CONSTRAINT, expected_version: 1, to_state: "identified", category_id: CATEGORY, date_identified: "2026-09-01", due_date: "2026-09-15", bic: BIC_OUT, responsible: RESPONSIBLE_OUT }),
  route("POST", `/constraints/${CONSTRAINT}/transition`, transitionConstraint, C, "constraints.transition", "constraint",
    { expectedVersion: 2, toState: "in_progress" },
    { constraint_id: CONSTRAINT, expected_version: 2, to_state: "in_progress" }),
  route("POST", `/constraints/${CONSTRAINT}/close`, closeConstraint, C, "constraints.close", "constraint",
    { expectedVersion: 2, completionDate: "2026-09-20", closureCommentary: "Delivered" },
    { constraint_id: CONSTRAINT, expected_version: 2, completion_date: "2026-09-20", closure_commentary: "Delivered" }),
  route("POST", `/constraints/${CONSTRAINT}/close-follow-up`, closeFollowUp, C, "constraints.close_follow_up", "constraint",
    {
      expectedVersion: 2, successorDescription: "Crane access", completionDate: "2026-09-20",
      closureCommentary: "Delivered", successorCategoryId: CATEGORY, successorDueDate: "2026-10-01",
      successorState: "identified", successorBic: BIC, successorResponsible: RESPONSIBLE,
    },
    {
      constraint_id: CONSTRAINT, expected_version: 2, successor_description: "Crane access",
      completion_date: "2026-09-20", closure_commentary: "Delivered", successor_category_id: CATEGORY,
      successor_due_date: "2026-10-01", successor_state: "identified", successor_bic: BIC_OUT,
      successor_responsible: RESPONSIBLE_OUT,
    }),
  route("POST", `/constraints/${CONSTRAINT}/void`, voidConstraint, C, "constraints.void", "constraint",
    { expectedVersion: 2, voidReason: "Duplicate", voidedDate: "2026-09-20" },
    { constraint_id: CONSTRAINT, expected_version: 2, void_reason: "Duplicate", voided_date: "2026-09-20" }),
  route("POST", `/constraints/${CONSTRAINT}/reopen`, reopenConstraint, C, "constraints.reopen", "constraint",
    { expectedVersion: 4, toState: "pending", reason: "Recurred" },
    { constraint_id: CONSTRAINT, expected_version: 4, to_state: "pending", reason: "Recurred" }),
  route("POST", "/constraint-categories", createCategory, {}, "constraint_categories.create", null,
    { prefix: "7", title: "Logistics", description: "Deliveries", displayOrder: 3, state: "active" },
    { project_id: PROJECT, code_segment: "7", title: "Logistics", description: "Deliveries", display_order: 3, state: "active" }),
  route("PATCH", `/constraint-categories/${CATEGORY}`, updateCategory, G, "constraint_categories.update", "category",
    { expectedVersion: 1, prefix: "8", title: "Logistics and access", description: "Gates", displayOrder: 0 },
    { category_id: CATEGORY, expected_version: 1, code_segment: "8", title: "Logistics and access", description: "Gates", display_order: 0 }),
  route("POST", `/constraint-categories/${CATEGORY}/deactivate`, deactivateCategory, G, "constraint_categories.deactivate", "category",
    { expectedVersion: 1 },
    { category_id: CATEGORY, expected_version: 1 }),
  route("POST", "/constraint-categories/reorder", reorderCategories, {}, "constraint_categories.reorder", null,
    { orderedCategoryIds: [CATEGORY_2, CATEGORY], expectedVersions: [1, 1] },
    { project_id: PROJECT, ordered_category_ids: [CATEGORY_2, CATEGORY], expected_versions: [1, 1] }),
];

const PREFLIGHT = { constraint: "constraints.read", category: "constraint_categories.list" } as const;

function send(
  session: string | null,
  target: AuthoringRoute,
  payload: unknown,
  path: string = target.path,
) {
  const value = new NextRequest(`${ORIGIN}${path}`, {
    method: target.method,
    headers: { "content-type": "application/json", origin: ORIGIN },
    body: JSON.stringify(payload),
  });
  if (session) value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function call(target: AuthoringRoute, request: NextRequest, params = target.params) {
  return target.handler(request, { params: Promise.resolve(params) as Promise<never> });
}

/** A Python `ProblemDetail` at the status `app.py` would answer it with. */
function problem(status: number, code: string) {
  return new Response(JSON.stringify({ error: { code, message: "refused upstream" } }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * The preflight succeeds from the committed Python fixture (whose record and
 * Category are in `PROJECT`); the mutation answers with `mutation`, else its own
 * committed Python success.
 */
function stubAuthoring(mutation?: () => Response) {
  return stubGateway((url) => {
    const capability = url.slice(GATEWAY.length);
    if (capability === "constraints.read" || capability === "constraint_categories.list") {
      return success(capability);
    }
    return mutation ? mutation() : success(capability);
  });
}

function capabilities(sent: readonly Sent[]) {
  return sent.map((entry) => entry.url.slice(GATEWAY.length));
}

/** Every object key anywhere in a decoded answer. */
function keysOf(value: unknown, into: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) keysOf(item, into);
  } else if (value !== null && typeof value === "object") {
    for (const [key, entry] of Object.entries(value)) {
      into.push(key);
      keysOf(entry, into);
    }
  }
  return into;
}

const label = (target: AuthoringRoute) => `${target.method} ${target.path.slice(BASE.length)}`;
const ROWS = AUTHORING.map((target) => [label(target), target] as const);

describe("R01-WP09: each authoring route sends exactly its capability and payload", () => {
  it("covers thirteen distinct routes and thirteen distinct capabilities", () => {
    expect(new Set(AUTHORING.map(label)).size).toBe(13);
    expect(new Set(AUTHORING.map((target) => target.capability)).size).toBe(13);
    expect(AUTHORING.filter((target) => target.method === "PATCH")).toHaveLength(2);
  });

  it.each(ROWS)("%s", async (_name, target) => {
    const session = await cookie();
    const { sent } = stubAuthoring();
    const response = await call(target, send(session, target, target.body));

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const expected = target.admission
      ? [PREFLIGHT[target.admission], target.capability]
      : [target.capability];
    expect(capabilities(sent)).toEqual(expected);
    const mutation = sent[sent.length - 1].document;
    expect(mutation.payload).toEqual(target.payload);
    expect(mutation.purpose).toEqual(expect.any(String));

    const answer = (await response.json()) as Record<string, unknown>;
    expect(answer.shape).toBe("backend");
    // The decoded answer is the safe projection: no identity, idempotency,
    // digest, telemetry or recording-time field reaches the browser.
    const result = { ...answer };
    delete result.disclosure;
    const leaked = keysOf(result).filter((key) =>
      /principal|idempotency|digest|client_?context|correlation|recorded/i.test(key),
    );
    expect(leaked).toEqual([]);
    expect(JSON.stringify(result)).not.toContain(KEY);
  });

  it("sends no project_id on update, so no update is a Project move (plan D6)", async () => {
    const session = await cookie();
    const target = AUTHORING.find((entry) => entry.capability === "constraints.update")!;
    const { sent } = stubAuthoring();
    await call(target, send(session, target, target.body));
    const payload = sent[sent.length - 1].document.payload as Record<string, unknown>;
    expect(Object.keys(payload)).not.toContain("project_id");
  });

  it.each(ROWS)("%s passes idempotencyKey unchanged and never synthesizes one", async (_name, target) => {
    const session = await cookie();
    const { sent } = stubAuthoring();
    const withoutKey = { ...target.body };
    delete withoutKey.idempotencyKey;
    await call(target, send(session, target, target.body));
    await call(target, send(session, target, withoutKey));
    const mutations = sent.filter((entry) => entry.url === `${GATEWAY}${target.capability}`);
    expect(mutations).toHaveLength(2);
    expect((mutations[0].document.payload as Record<string, unknown>).idempotency_key).toBe(KEY);
    expect(mutations[1].document.payload).not.toHaveProperty("idempotency_key");
  });
});

describe("R01-WP09: authoring requests are refused locally before a capability is spent", () => {
  it.each(ROWS)("%s refuses an unknown field and a gateway spelling with 400", async (_name, target) => {
    const session = await cookie();
    const { inner } = stubAuthoring();
    for (const extra of [{ anything: 1 }, { idempotency_key: KEY }, { expected_version: 1 }]) {
      const response = await call(target, send(session, target, { ...target.body, ...extra }));
      expect(response.status).toBe(400);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    }
    expect(inner).not.toHaveBeenCalled();
  });

  /** Every well-formed-looking path id of the wrong kind, per segment. */
  const WRONG: Record<string, readonly string[]> = {
    projectId: ["not-an-id", "prj_short", CONSTRAINT, CATEGORY, "PRJ_aaaaaaaa11111111"],
    constraintId: ["cst_short", PROJECT, CATEGORY, "drafts"],
    categoryId: ["ccat_short", CONSTRAINT, PROJECT, "reorder"],
  };

  it.each(ROWS)("%s refuses every malformed path id with 400", async (_name, target) => {
    const session = await cookie();
    const { inner } = stubAuthoring();
    for (const [segment, bad] of Object.entries(WRONG)) {
      if (!(segment in target.params)) continue;
      for (const value of bad) {
        const response = await call(target, send(session, target, target.body), {
          ...target.params,
          [segment]: value,
        });
        expect(response.status, `${segment}=${value}`).toBe(400);
        expect(response.headers.get("cache-control")).toBe("private, no-store");
        expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
      }
    }
    expect(inner).not.toHaveBeenCalled();
  });

  const reorder = AUTHORING.find((entry) => entry.capability === "constraint_categories.reorder")!;

  it.each([
    ["mismatched lengths", { orderedCategoryIds: [CATEGORY, CATEGORY_2], expectedVersions: [1] }],
    ["a repeated Category", { orderedCategoryIds: [CATEGORY, CATEGORY], expectedVersions: [1, 1] }],
    ["an empty order", { orderedCategoryIds: [], expectedVersions: [] }],
    ["a Constraint id in the order", { orderedCategoryIds: [CONSTRAINT], expectedVersions: [1] }],
    ["no versions", { orderedCategoryIds: [CATEGORY] }],
    ["no order", { expectedVersions: [1] }],
    ["a negative version", { orderedCategoryIds: [CATEGORY], expectedVersions: [-1] }],
    ["a fractional version", { orderedCategoryIds: [CATEGORY], expectedVersions: [1.5] }],
    ["a string version", { orderedCategoryIds: [CATEGORY], expectedVersions: ["1"] }],
    [
      "sixty-five Categories",
      {
        orderedCategoryIds: Array.from({ length: 65 }, (_, i) => `ccat_${String(i).padStart(8, "a")}`),
        expectedVersions: Array.from({ length: 65 }, () => 1),
      },
    ],
  ])("reorder refuses %s with 400", async (_name, payload) => {
    const session = await cookie();
    const { inner } = stubAuthoring();
    const response = await call(reorder, send(session, reorder, { ...payload, idempotencyKey: KEY }));
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    expect(inner).not.toHaveBeenCalled();
  });

  const draft = AUTHORING.find((entry) => entry.capability === "constraints.create")!;
  const transition = AUTHORING.find((entry) => entry.capability === "constraints.transition")!;

  it.each([
    ["a gateway-spelled party key", { bic: [{ kind: "entity", entity_id: "ent_aaaaaaaa11111111" }] }],
    ["an unknown party key", { bic: [{ kind: "principal", principalId: "x" }] }],
    ["a labelled principal", { bic: [{ kind: "principal", label: "Me" }] }],
    ["an entity without an id", { responsible: [{ kind: "entity", label: "Pat" }] }],
    ["an unresolved party with an id", { responsible: [{ kind: "unresolved", entityId: "ent_x", label: "x" }] }],
    ["an unresolved party without a label", { responsible: [{ kind: "unresolved" }] }],
    ["a whitespace-only label", { responsible: [{ kind: "unresolved", label: "   " }] }],
    ["an unknown party kind", { bic: [{ kind: "team" }] }],
    ["a bare string party", { bic: ["principal"] }],
    ["thirty-three parties", { bic: Array.from({ length: 33 }, () => ({ kind: "principal" })) }],
    ["a non-draft lifecycle vocabulary field", { toState: "pending" }],
  ])("create draft refuses %s with 400", async (_name, extra) => {
    const session = await cookie();
    const { inner } = stubAuthoring();
    const response = await call(draft, send(session, draft, { ...draft.body, ...extra }));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([
    ["a negative expected version", { expectedVersion: -1 }],
    ["a string expected version", { expectedVersion: "2" }],
    ["a terminal target", { toState: "closed" }],
    ["a draft target", { toState: "draft" }],
    ["an uppercase target", { toState: "PENDING" }],
    ["an over-long idempotency key", { idempotencyKey: "k".repeat(129) }],
  ])("transition refuses %s with 400", async (_name, extra) => {
    const session = await cookie();
    const { inner } = stubAuthoring();
    const response = await call(transition, send(session, transition, { ...transition.body, ...extra }));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });
});

describe("R01-WP09: the mutation's own refusals reach the browser typed", () => {
  const REFUSALS: readonly (readonly [string, () => Response, number, string, string])[] = [
    ["a stale-version conflict", () => problem(409, "conflict"), 409, "conflict", "conflict"],
    ["a rate limit", () => problem(429, "rate_limited"), 429, "unavailable", "rate_limited"],
    // `unsupported` is an `unavailable`-class Python problem; the shared refusal
    // mapping (`lib/api/gateway.ts`) answers every `unavailable` code with 503,
    // so the code, not the status, is what distinguishes it.
    ["an unsupported capability", () => problem(501, "unsupported"), 503, "unavailable", "unsupported"],
    ["a degraded gateway", () => problem(503, "unavailable"), 503, "unavailable", "unavailable"],
    [
      "a network failure",
      () => {
        throw new TypeError("fetch failed");
      },
      503,
      "unavailable",
      "gateway_unreachable",
    ],
    [
      "a malformed success",
      () => body({ disposition: "applied" }),
      503,
      "unavailable",
      "upstream_contract_invalid",
    ],
  ];

  const MATRIX = ROWS.flatMap(([name, target]) =>
    REFUSALS.map(([what, answer, status, errorClass, code]) =>
      [name, what, target, answer, status, errorClass, code] as const,
    ),
  );

  it.each(MATRIX)(
    "%s answers %s as typed",
    async (_name, _what, target, answer, status, errorClass, code) => {
      const session = await cookie();
      const { sent } = stubAuthoring(answer);
      const response = await call(target, send(session, target, target.body));
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      const refusal = await response.json();
      expect(refusal.error).toMatchObject({ errorClass, code });
      expect(refusal.state).not.toBe("ok");
      expect(JSON.stringify(refusal)).not.toContain(KEY);
      // Exactly one mutation attempt: nothing here retries a refused write.
      expect(sent.filter((entry) => entry.url === `${GATEWAY}${target.capability}`)).toHaveLength(1);
    },
  );

  it.each(ROWS)(
    "%s answers 503 authority_unavailable when the session authority cannot answer",
    async (_name, target) => {
      const session = await cookie();
      const { inner } = stubAuthoring();
      vi.stubEnv("MYPA_GATEWAY_URL", "");
      const response = await call(target, send(session, target, target.body));
      expect(response.status).toBe(503);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toMatchObject({ error: { code: "authority_unavailable" } });
      expect(inner).not.toHaveBeenCalled();
    },
  );
});

describe("R01-WP09: the static reorder segment is not a Category", () => {
  const ROOT = join(process.cwd(), "src/app/api/project-controls/projects/[projectId]/constraint-categories");

  it("ships reorder as a static sibling of [categoryId], which Next.js resolves first", () => {
    // Next.js matches a static segment ahead of a dynamic one at the same
    // level, so `…/constraint-categories/reorder` is served by this handler.
    expect(existsSync(join(ROOT, "reorder/route.ts"))).toBe(true);
    expect(existsSync(join(ROOT, "[categoryId]/route.ts"))).toBe(true);
    expect(existsSync(join(ROOT, "[categoryId]/reorder"))).toBe(false);
  });

  it("POST …/constraint-categories/reorder reaches the reorder capability", async () => {
    const session = await cookie();
    const target = AUTHORING.find((entry) => entry.capability === "constraint_categories.reorder")!;
    const { sent } = stubAuthoring();
    const response = await call(target, send(session, target, target.body));
    expect(response.status).toBe(200);
    expect(capabilities(sent)).toEqual(["constraint_categories.reorder"]);
  });

  it.each(ROWS.filter(([, target]) => target.admission === "category"))(
    "%s refuses a categoryId of \"reorder\" as malformed, with no gateway call",
    async (_name, target) => {
      const session = await cookie();
      const { inner } = stubAuthoring();
      const response = await call(
        target,
        send(session, target, target.body, target.path.replace(CATEGORY, "reorder")),
        { ...target.params, categoryId: "reorder" },
      );
      expect(response.status).toBe(400);
      expect(await response.json()).toMatchObject({
        error: { code: "invalid_request", message: "categoryId is not a well-formed identifier" },
      });
      expect(inner).not.toHaveBeenCalled();
    },
  );
});
