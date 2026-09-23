// @vitest-environment node
/**
 * R01-WP09 S4: exact-Project admission for existing-record writes.
 *
 * The two preflights are driven through the shared write helper exactly as the
 * routes will hand them over — as its `admit` hook — with a real session cookie
 * and the gateway stubbed at the Response level. What is proved: a record in
 * the URL's Project is admitted and the mutation is sent under the same
 * Principal; a record elsewhere is the detail read's own `404`, byte for byte,
 * and the mutation is never sent; a refused preflight stays the typed refusal
 * it was.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as detail } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/route";
import { workPost } from "@/lib/api/work-route";
import {
  CATEGORY_DEACTIVATE_FIELDS,
  CONSTRAINT_TRANSITION_FIELDS,
} from "@/app/api/project-controls/constraint-requests";
import {
  admitExistingCategory,
  admitExistingConstraint,
} from "@/app/api/project-controls/constraint-mutation-admission";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const GATEWAY = "http://127.0.0.1:8000/v1/";
const PYTHON = JSON.parse(
  readFileSync(join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json"), "utf8"),
) as Record<string, unknown>;

/** The committed Python fixtures place their record and Category in this Project. */
const PROJECT = "prj_aaaaaaaa11111111";
const FOREIGN_PROJECT = "prj_bbbbbbbb22222222";
const CONSTRAINT = "cst_aaaaaaaa11111111";
const CATEGORY = "ccat_aaaaaaaa11111111";
const OTHER_CATEGORY = "ccat_zzzzzzzz99999999";

const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["principal_partition"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

function body(result: unknown) {
  return new Response(JSON.stringify({ result, disclosure: DISCLOSURE }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function problem(status: number, code: string) {
  return new Response(JSON.stringify({ error: { code, message: "refused upstream" } }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** The Python `constraints.read` fixture with its record moved to `projectId`. */
function readIn(projectId: string) {
  const answer = structuredClone(PYTHON["constraints.read"]) as {
    constraint: Record<string, unknown>;
  };
  answer.constraint.project_id = projectId;
  return answer;
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

function post(session: string, path: string, payload: unknown) {
  const value = new NextRequest(`${ORIGIN}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: ORIGIN },
    body: JSON.stringify(payload),
  });
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

type Sent = { readonly url: string; readonly document: Record<string, unknown> };

/** Answers each capability from `answers`, else the committed Python success. */
function stubGateway(answers: Record<string, () => Response> = {}) {
  const sent: Sent[] = [];
  const inner = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    const href = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
    sent.push({ url: href, document: JSON.parse(String(init?.body)) as Record<string, unknown> });
    const capability = href.slice(GATEWAY.length);
    return answers[capability]?.() ?? body(PYTHON[capability]);
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

describe("admitExistingConstraint", () => {
  async function transition(session: string, urlProject: string) {
    return workPost(
      post(
        session,
        `/api/project-controls/projects/${urlProject}/constraints/${CONSTRAINT}/transition`,
        { expectedVersion: 2, toState: "pending", idempotencyKey: "key-00000001" },
      ),
      "constraint-transition",
      "constraints.transition",
      CONSTRAINT_TRANSITION_FIELDS,
      { constraint_id: CONSTRAINT },
      { admit: admitExistingConstraint(urlProject, CONSTRAINT) },
    );
  }

  it("admits a Constraint in the URL's Project and sends the mutation as the same Principal", async () => {
    const session = await cookie();
    const { sent } = stubGateway({ "constraints.read": () => body(readIn(PROJECT)) });
    const response = await transition(session, PROJECT);

    expect(response.status).toBe(200);
    expect(sent.map((call) => call.url)).toEqual([
      `${GATEWAY}constraints.read`,
      `${GATEWAY}constraints.transition`,
    ]);
    expect(sent[0].document.payload).toEqual({ constraint_id: CONSTRAINT });
    expect(sent[0].document.principal_id).toEqual(expect.any(String));
    expect(sent[1].document.principal_id).toBe(sent[0].document.principal_id);
  });

  it("answers another Project's Constraint with the detail read's own 404, byte for byte", async () => {
    const session = await cookie();
    const { sent } = stubGateway({ "constraints.read": () => body(readIn(FOREIGN_PROJECT)) });
    const refused = await transition(session, PROJECT);

    // The mutation capability is never invoked: the only call is the preflight.
    expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraints.read`]);

    stubGateway({ "constraints.read": () => body(readIn(FOREIGN_PROJECT)) });
    const read = await detail(
      new NextRequest(`${ORIGIN}/api/project-controls/projects/${PROJECT}/constraints/${CONSTRAINT}`, {
        headers: { cookie: `${SESSION_COOKIE_NAME}=${session}` },
      }),
      { params: Promise.resolve({ projectId: PROJECT, constraintId: CONSTRAINT }) },
    );

    expect(refused.status).toBe(404);
    expect(read.status).toBe(404);
    expect(refused.headers.get("cache-control")).toBe("private, no-store");
    expect(refused.headers.get("cache-control")).toBe(read.headers.get("cache-control"));
    expect(refused.headers.get("content-type")).toBe(read.headers.get("content-type"));
    const [refusedText, readText] = [await refused.text(), await read.text()];
    expect(refusedText).toBe(readText);
    expect(JSON.parse(refusedText)).toEqual({
      error: { errorClass: "not_found", code: "not_found", message: "Constraint was not found" },
    });
  });

  it.each([
    [404, "not_found", "not_found"],
    [403, "denied", "authorization"],
    [429, "rate_limited", "unavailable"],
    [503, "unavailable", "unavailable"],
  ])(
    "preserves a %s %s preflight refusal as typed and never sends the mutation",
    async (status, code, errorClass) => {
      const session = await cookie();
      const { sent } = stubGateway({ "constraints.read": () => problem(status, code) });
      const response = await transition(session, PROJECT);

      expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraints.read`]);
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      const answer = await response.json();
      expect(answer.error.code).toBe(code);
      expect(answer.error.errorClass).toBe(errorClass);
    },
  );

  it("refuses a malformed preflight success as upstream_contract_invalid, never as absence", async () => {
    const session = await cookie();
    const { sent } = stubGateway({ "constraints.read": () => body({ constraint: {} }) });
    const response = await transition(session, PROJECT);

    expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraints.read`]);
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });
});

describe("admitExistingCategory", () => {
  async function deactivate(session: string, categoryId: string) {
    return workPost(
      post(
        session,
        `/api/project-controls/projects/${PROJECT}/constraint-categories/${categoryId}/deactivate`,
        { expectedVersion: 1, idempotencyKey: "key-00000001" },
      ),
      "constraint-category-deactivate",
      "constraint_categories.deactivate",
      CATEGORY_DEACTIVATE_FIELDS,
      { category_id: categoryId },
      { admit: admitExistingCategory(PROJECT, categoryId) },
    );
  }

  it("lists every state of the URL's Project and admits a member Category", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await deactivate(session, CATEGORY);

    expect(response.status).toBe(200);
    expect(sent.map((call) => call.url)).toEqual([
      `${GATEWAY}constraint_categories.list`,
      `${GATEWAY}constraint_categories.deactivate`,
    ]);
    expect(sent[0].document.payload).toEqual({
      project_id: PROJECT,
      states: ["active", "inactive", "archived"],
    });
    expect(sent[1].document.principal_id).toBe(sent[0].document.principal_id);
  });

  it("answers a Category outside the Project with a nondisclosing 404 and no dispatch", async () => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await deactivate(session, OTHER_CATEGORY);

    expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraint_categories.list`]);
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.text()).toBe(
      JSON.stringify({
        error: { errorClass: "not_found", code: "not_found", message: "Category was not found" },
      }),
    );
  });

  it.each([
    [403, "denied", "authorization"],
    [429, "rate_limited", "unavailable"],
    [503, "unavailable", "unavailable"],
  ])(
    "preserves a %s %s preflight refusal as typed and never sends the mutation",
    async (status, code, errorClass) => {
      const session = await cookie();
      const { sent } = stubGateway({
        "constraint_categories.list": () => problem(status, code),
      });
      const response = await deactivate(session, CATEGORY);

      expect(sent.map((call) => call.url)).toEqual([`${GATEWAY}constraint_categories.list`]);
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      const answer = await response.json();
      expect(answer.error.code).toBe(code);
      expect(answer.error.errorClass).toBe(errorClass);
    },
  );
});
