// @vitest-environment node
/**
 * T08-07 / T08-10: the trust boundary and the fixture boundary, structurally.
 * R01-WP09: the thirteen authoring routes' trust boundary, behaviourally.
 *
 * These are static reads of the shipped source rather than behavioural cases,
 * because the properties they defend are absences — a route that does not
 * exist, an import nobody wrote, a fixture nothing reaches for. A behavioural
 * test can only fail once someone adds the thing; a source sweep fails the
 * moment they do.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import {
  GET as register,
  POST as createPublished,
} from "@/app/api/project-controls/projects/[projectId]/constraints/route";
import { POST as createDraft } from "@/app/api/project-controls/projects/[projectId]/constraints/drafts/route";
import {
  GET as detail,
  PATCH as updateConstraint,
} from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/route";
import { POST as publishConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/publish/route";
import { POST as transitionConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/transition/route";
import { POST as closeConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/close/route";
import { POST as closeFollowUp } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/close-follow-up/route";
import { POST as voidConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/void/route";
import { POST as reopenConstraint } from "@/app/api/project-controls/projects/[projectId]/constraints/[constraintId]/reopen/route";
import { POST as createCategory } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/route";
import { PATCH as updateCategory } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/[categoryId]/route";
import { POST as deactivateCategory } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/[categoryId]/deactivate/route";
import { POST as reorderCategories } from "@/app/api/project-controls/projects/[projectId]/constraint-categories/reorder/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const SRC = join(process.cwd(), "src");
const PROJECT_CONTROLS = join(SRC, "app/api/project-controls");
const CONSTRAINT_DECODERS = join(SRC, "lib/api/decode/capabilities");
const WP05_PAGE = join(SRC, "app/(app)/work/projects/[projectId]/constraints/page.tsx");
const ORIGIN = "http://localhost:3000";
const PROJECT = "prj_aaaaaaaa11111111";

function sources(directory: string, keep: (name: string) => boolean = () => true): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path, keep);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) && keep(entry) ? [path] : [];
  });
}

const PROJECT_CONTROL_SOURCES = sources(PROJECT_CONTROLS);
const CONSTRAINT_SOURCES = [
  ...PROJECT_CONTROL_SOURCES,
  ...sources(CONSTRAINT_DECODERS, (name) => /^_?constraint/.test(name)),
];

function text(path: string): string {
  return readFileSync(path, "utf8");
}

/**
 * The file with its comments removed.
 *
 * The foreign-integration sweep runs over this rather than the raw bytes: these
 * modules *explain* why a workbook read is not something a read plane may
 * assert, and a rule that forbade naming the thing would forbid documenting the
 * boundary it defends.
 */
function code(path: string): string {
  return text(path).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/**
 * The settings route, admitted to mutate by R01-WP05.
 *
 * R01-WP05 admitted Project Controls *settings* administration and nothing else;
 * R01-WP09 admits the thirteen authoring mutations below. Both exceptions are
 * named here, once, so admitting another is an edit to a constant rather than a
 * quietly widened regex.
 */
const SETTINGS_ROUTE = "projects/[projectId]/settings/route.ts";

/**
 * R01-WP09: every Constraint and Category mutation this family may export —
 * exactly the thirteen (method, route) pairs of artifact 17 §5 ("Browser route
 * contract freeze"), no more.
 *
 * The sweep below requires the family's mutating exports to be *exactly* these
 * plus the settings `POST`. A fourteenth handler (a `DELETE`, a second verb on
 * one of these files, a new sibling route) fails it until it is written here
 * and justified against a contract, which is the point: an authoring surface
 * that grows by accident is the defect this constant exists to stop.
 */
const AUTHORING_MUTATIONS: readonly (readonly ["POST" | "PATCH", string])[] = [
  ["POST", "projects/[projectId]/constraints/route.ts"],
  ["POST", "projects/[projectId]/constraints/drafts/route.ts"],
  ["PATCH", "projects/[projectId]/constraints/[constraintId]/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/publish/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/transition/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/close/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/close-follow-up/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/void/route.ts"],
  ["POST", "projects/[projectId]/constraints/[constraintId]/reopen/route.ts"],
  ["POST", "projects/[projectId]/constraint-categories/route.ts"],
  ["PATCH", "projects/[projectId]/constraint-categories/[categoryId]/route.ts"],
  ["POST", "projects/[projectId]/constraint-categories/[categoryId]/deactivate/route.ts"],
  ["POST", "projects/[projectId]/constraint-categories/reorder/route.ts"],
];

/** The thirteen authoring capabilities those routes address (artifact 17 §7). */
const AUTHORING_CAPABILITIES = [
  "constraint_categories.create",
  "constraint_categories.deactivate",
  "constraint_categories.reorder",
  "constraint_categories.update",
  "constraints.close",
  "constraints.close_follow_up",
  "constraints.create",
  "constraints.create_published",
  "constraints.publish",
  "constraints.reopen",
  "constraints.transition",
  "constraints.update",
  "constraints.void",
];

const MUTATING_EXPORT =
  /export\s+(?:async\s+)?function\s+(POST|PATCH|PUT|DELETE)\b|export\s+const\s+(POST|PATCH|PUT|DELETE)\b/g;

/** Every mutating export in the family, as sorted `"METHOD path"` strings. */
function mutatingExports(): string[] {
  return PROJECT_CONTROL_SOURCES.flatMap((path) =>
    [...text(path).matchAll(MUTATING_EXPORT)].map(
      (match) => `${match[1] ?? match[2]} ${path.slice(PROJECT_CONTROLS.length + 1)}`,
    ),
  ).sort();
}

describe("the Constraint BFF surface mutates only through its admitted routes", () => {
  it("ships exactly this set of routes and no more", () => {
    const routes = PROJECT_CONTROL_SOURCES.filter((path) => path.endsWith("route.ts"));
    // R01-WP06 adds the two portfolio reads. They live outside the
    // `projects/[projectId]/` tree deliberately: a portfolio read takes no
    // Project identifier, so there is no segment for one and no path that could
    // be used to ask whether a named Project answers for this Principal.
    expect(routes.map((path) => path.slice(PROJECT_CONTROLS.length + 1)).sort()).toEqual([
      "portfolio/constraints/overview/route.ts",
      "portfolio/constraints/route.ts",
      // R01-WP09 adds ten authoring route files; the other three authoring
      // handlers sit beside a read in files already listed here.
      "projects/[projectId]/constraint-categories/[categoryId]/deactivate/route.ts",
      "projects/[projectId]/constraint-categories/[categoryId]/route.ts",
      "projects/[projectId]/constraint-categories/reorder/route.ts",
      "projects/[projectId]/constraint-categories/route.ts",
      "projects/[projectId]/constraints/[constraintId]/close-follow-up/route.ts",
      "projects/[projectId]/constraints/[constraintId]/close/route.ts",
      "projects/[projectId]/constraints/[constraintId]/history/route.ts",
      "projects/[projectId]/constraints/[constraintId]/publish/route.ts",
      "projects/[projectId]/constraints/[constraintId]/reopen/route.ts",
      "projects/[projectId]/constraints/[constraintId]/route.ts",
      "projects/[projectId]/constraints/[constraintId]/transition/route.ts",
      "projects/[projectId]/constraints/[constraintId]/void/route.ts",
      "projects/[projectId]/constraints/drafts/route.ts",
      "projects/[projectId]/constraints/overview/route.ts",
      "projects/[projectId]/constraints/route.ts",
      SETTINGS_ROUTE,
    ].sort());
  });

  it("puts no Project segment on either portfolio route", () => {
    const portfolio = PROJECT_CONTROL_SOURCES.filter(
      (path) => path.endsWith("route.ts") && path.includes("/portfolio/"),
    );
    expect(portfolio).toHaveLength(2);
    for (const path of portfolio) {
      expect(path, path).not.toMatch(/\[projectId\]/);
      const source = code(path);
      // No path parameter is read, and no Project allowlist is imported: the
      // Project set is the server's answer about the Principal, never a request
      // field the browser could vary to probe ownership.
      expect(source, path).not.toMatch(/\bcontext\b/);
      expect(source, path).not.toMatch(/\bprojectId\b/);
      expect(source, path).not.toMatch(/\bproject_id\b/);
      expect(source, path).not.toMatch(/\bisProjectId\b/);
      expect(source, path).not.toMatch(/\bREGISTER_FIELDS\b/);
      expect(source, path).not.toMatch(/\bSEARCH_FIELDS\b/);
    }
  });

  it("gives each portfolio route a single gateway dispatch", () => {
    // Plan section 15: a portfolio BFF route calls the server portfolio
    // capability once per request and client fanout is prohibited. Behaviour is
    // counted in `portfolio-routes.test.ts`; what a source sweep adds is that
    // there is only one call site to count, so no loop over Projects can be
    // hiding behind a passing behavioural case.
    for (const path of PROJECT_CONTROL_SOURCES.filter(
      (candidate) => candidate.endsWith("route.ts") && candidate.includes("/portfolio/"),
    )) {
      const source = code(path);
      expect(source.match(/\bworkGet\(/g)?.length ?? 0, path).toBeLessThanOrEqual(2);
      expect(source, path).not.toMatch(/\bfor\b|\bwhile\b|\.map\(|Promise\.all/);
      expect(source, path).not.toMatch(/"constraints\.(list|search|overview)"/);
    }
  });

  it("exports exactly the thirteen authoring mutations and the settings POST, and no other", () => {
    expect(AUTHORING_MUTATIONS).toHaveLength(13);
    expect(mutatingExports()).toEqual(
      [
        `POST ${SETTINGS_ROUTE}`,
        ...AUTHORING_MUTATIONS.map(([method, path]) => `${method} ${path}`),
      ].sort(),
    );
    const settings = text(join(PROJECT_CONTROLS, SETTINGS_ROUTE));
    expect(settings).toMatch(/export\s+async\s+function\s+POST\b/);
    expect(settings).not.toMatch(/export\s+(async\s+)?function\s+(PATCH|PUT|DELETE)\b/);
  });

  it("reaches the write helper only from a mutating route, and never admits a mutation itself", () => {
    const writers = new Set([
      SETTINGS_ROUTE,
      ...AUTHORING_MUTATIONS.map(([, path]) => path),
    ]);
    for (const path of PROJECT_CONTROL_SOURCES) {
      const source = text(path);
      if (!writers.has(path.slice(PROJECT_CONTROLS.length + 1))) {
        expect(source, path).not.toMatch(/\bworkPost\b/);
      }
      // Origin admission is `workPost`'s, once; a route that called it too
      // would be a second, divergent copy of the policy.
      expect(source, path).not.toMatch(/\badmitBrowserMutation\b/);
    }
  });

  it("binds every existing-record authoring route to its URL Project with the shared preflight", () => {
    for (const [, path] of AUTHORING_MUTATIONS) {
      const source = code(join(PROJECT_CONTROLS, path));
      const calls = source.match(/\bworkPost\(/g) ?? [];
      // One write call per mutating export: no handler re-implements the pipeline.
      expect(calls.length, path).toBe(
        [...source.matchAll(MUTATING_EXPORT)].length,
      );
      if (path.includes("[constraintId]")) {
        expect(source, path).toMatch(/admit:\s*admitExistingConstraint\(projectId, constraintId\)/);
      } else if (path.includes("[categoryId]")) {
        expect(source, path).toMatch(/admit:\s*admitExistingCategory\(projectId, categoryId\)/);
      } else {
        expect(source, path).not.toMatch(/\badmitExisting/);
      }
    }
  });

  it("addresses only the admitted read and authoring capabilities and no sync name", () => {
    const addressed = new Set<string>();
    for (const path of PROJECT_CONTROL_SOURCES) {
      for (const match of text(path).matchAll(/"(constraints?[_.][a-z_.]+)"/g)) {
        addressed.add(match[1]);
      }
    }
    // R01-WP06 adds the portfolio reads, which are reads. R01-WP09 adds the
    // thirteen authoring capabilities, each reached by exactly its own route.
    // Nothing from the sync family is reachable from this surface.
    expect([...addressed].sort()).toEqual(
      [
        "constraint_categories.list",
        "constraints.history",
        "constraints.list",
        "constraints.overview",
        "constraints.portfolio_list",
        "constraints.portfolio_overview",
        "constraints.portfolio_search",
        "constraints.read",
        "constraints.search",
        ...AUTHORING_CAPABILITIES,
      ].sort(),
    );
  });

  it("addresses exactly two Project Controls capabilities and no other", () => {
    const addressed = new Set<string>();
    for (const path of PROJECT_CONTROL_SOURCES) {
      for (const match of text(path).matchAll(/"(project_controls\.[a-z_.]+)"/g)) {
        addressed.add(match[1]);
      }
    }
    expect([...addressed].sort()).toEqual([
      "project_controls.configure",
      "project_controls.status",
    ]);
  });
});

describe("the browser is not handed transport, identity, or a foreign integration", () => {
  it("no Constraint source imports the server-only gateway transport", () => {
    for (const path of CONSTRAINT_SOURCES) {
      expect(text(path), path).not.toMatch(/callGateway/);
      expect(text(path), path).not.toMatch(/from "@\/lib\/api\/gateway"/);
    }
  });

  it("no Constraint source reads a Principal from the request", () => {
    for (const path of CONSTRAINT_SOURCES) {
      const source = text(path);
      expect(source, path).not.toMatch(/principal_id/);
      expect(source, path).not.toMatch(/principalId/);
      expect(source, path).not.toMatch(/resolveSessionPrincipal/);
    }
  });

  it.each([
    [/\bmcp\b/i, "MCP"],
    [/chat_?llm/i, "ChatLLM"],
    [/sharepoint/i, "SharePoint"],
    [/\bexcel\b/i, "Excel"],
    [/workbook/i, "a workbook path"],
    [/openpyxl|xlsx/i, "a spreadsheet library"],
  ])("no Constraint source mentions %s (%s)", (pattern, label) => {
    for (const path of CONSTRAINT_SOURCES) {
      let source = code(path);
      if (label === "a workbook path") {
        // R01-WP09. `"legacy_workbook_import"` is a member of the closed
        // `ConstraintOrigin` provenance vocabulary, which the authoring
        // decoders must validate (artifact 17 §9). It names where a record
        // came from, not a workbook path or integration, so exactly that quoted
        // literal is removed before the sweep; any other mention still fails.
        source = source.replaceAll('"legacy_workbook_import"', "");
      }
      expect(source, path).not.toMatch(pattern);
    }
  });

  it("no Constraint source logs a payload, a record, or a caller's text", () => {
    for (const path of CONSTRAINT_SOURCES) {
      const source = text(path);
      expect(source, path).not.toMatch(/console\./);
      expect(source, path).not.toMatch(/JSON\.stringify\(/);
    }
  });

  it("hands no URLSearchParams onward and builds no generic case converter", () => {
    for (const path of CONSTRAINT_SOURCES) {
      const source = text(path);
      // Reading `q` off the URL to choose a capability is the one search-params
      // use; forwarding the bag itself is what is forbidden.
      expect(source.replace(/searchParams\.get\("q"\)/g, ""), path).not.toMatch(
        /searchParams(?!\.get\("q"\))/,
      );
      expect(source, path).not.toMatch(/replace\(\/\[A-Z\]\//);
      expect(source, path).not.toMatch(/toSnakeCase|snakeCase|camelize/);
    }
  });
});

describe("the fixture boundary holds", () => {
  it("no live Constraint route imports the synthetic corpus", () => {
    for (const path of PROJECT_CONTROL_SOURCES) {
      expect(text(path), path).not.toMatch(/lib\/fixtures/);
      expect(text(path), path).not.toMatch(/synthetic/i);
    }
  });

  it("keeps fixtures behind the explicit synthetic page branch", () => {
    const page = text(WP05_PAGE);
    expect(page).toMatch(/@\/lib\/fixtures\/constraints/);
    expect(page).not.toMatch(/project-controls/);
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it("wires live reads only through the same-origin Constraint BFF client", () => {
    const client = text(join(SRC, "app/(app)/work/projects/[projectId]/constraints/constraint-live.ts"));
    expect(client).toMatch(/\/api\/project-controls\/projects\//);
    expect(client).toMatch(/cache: "no-store"/);
    expect(client).not.toMatch(/lib\/fixtures/);
    expect(client).not.toMatch(/method: "POST"|method: "PATCH"|method: "DELETE"/);
  });
});

describe("a live route answers from the backend or refuses — never from a fixture", () => {
  function get(session: string, path: string) {
    const value = new NextRequest(`${ORIGIN}${path}`);
    value.cookies.set(SESSION_COOKIE_NAME, session);
    return value;
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

  it("with MYPA_DATA_PROVIDER unset, the Register still asks the gateway", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "");
    const session = await cookie();
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      withSessionServiceFetch((url: string | URL | Request) => {
        calls.push(String(url));
        return new Response(JSON.stringify({ result: { constraints: [] }, disclosure: null }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }) as never,
    );
    await register(get(session, `/api/project-controls/projects/${PROJECT}/constraints`), {
      params: Promise.resolve({ projectId: PROJECT }),
    });
    expect(calls).toContain("http://127.0.0.1:8000/v1/constraints.list");
  });

  it("with the synthetic switch on, the Register answers not_implemented rather than fixtures", async () => {
    const session = await cookie();
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: Promise.resolve({ projectId: PROJECT }) },
    );
    expect(response.status).toBe(501);
    const answer = await response.json();
    expect(answer.state).toBe("not_implemented");
    expect(answer.constraints).toBeUndefined();
    expect(JSON.stringify(answer)).not.toMatch(/cst_/);
  });
});

// --- R01-WP09: the authoring routes' trust boundary, behaviourally -------------

describe("R01-WP09: every authoring route holds the trust boundary", () => {
  const GATEWAY = "http://127.0.0.1:8000/v1/";
  const CONSTRAINT = "cst_aaaaaaaa11111111";
  const CATEGORY = "ccat_aaaaaaaa11111111";
  const OTHER_CATEGORY = "ccat_zzzzzzzz99999999";
  const FOREIGN_PROJECT = "prj_bbbbbbbb22222222";
  const KEY = "idk_aaaaaaaa11111111";
  const BASE = `/api/project-controls/projects/${PROJECT}`;
  const PYTHON = JSON.parse(
    readFileSync(join(SRC, "lib/api/decode/fixtures/python/success.json"), "utf8"),
  ) as Record<string, unknown>;
  const DISCLOSURE = {
    coverage: { state: "not_enrolled" },
    freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
    trust: { level: "source_original", basis: ["principal_partition"] },
    truncation: { is_truncated: false },
    limitations: [],
    partial_result: false,
  };

  type Handler = (request: NextRequest, context: { params: Promise<never> }) => Promise<Response>;
  type Target = {
    readonly method: "POST" | "PATCH";
    readonly path: string;
    readonly handler: Handler;
    readonly params: Record<string, string>;
    readonly capability: string;
    readonly admission: "constraints.read" | "constraint_categories.list" | null;
    readonly body: Record<string, unknown>;
  };

  const target = (
    method: Target["method"],
    suffix: string,
    handler: unknown,
    params: Record<string, string>,
    capability: string,
    admission: Target["admission"],
    body: Record<string, unknown>,
  ): Target => ({
    method,
    path: `${BASE}${suffix}`,
    handler: handler as Handler,
    params: { projectId: PROJECT, ...params },
    capability,
    admission,
    body: { ...body, idempotencyKey: KEY },
  });

  const C = { constraintId: CONSTRAINT };
  const G = { categoryId: CATEGORY };
  const READ = "constraints.read" as const;
  const LIST = "constraint_categories.list" as const;

  /** The thirteen routes of `AUTHORING_MUTATIONS`, each with a body it admits. */
  const TARGETS: readonly Target[] = [
    target("POST", "/constraints", createPublished, {}, "constraints.create_published", null, { description: "Access" }),
    target("POST", "/constraints/drafts", createDraft, {}, "constraints.create", null, { description: "Access" }),
    target("PATCH", `/constraints/${CONSTRAINT}`, updateConstraint, C, "constraints.update", READ, { expectedVersion: 3, description: "Revised" }),
    target("POST", `/constraints/${CONSTRAINT}/publish`, publishConstraint, C, "constraints.publish", READ, { expectedVersion: 1 }),
    target("POST", `/constraints/${CONSTRAINT}/transition`, transitionConstraint, C, "constraints.transition", READ, { expectedVersion: 2, toState: "pending" }),
    target("POST", `/constraints/${CONSTRAINT}/close`, closeConstraint, C, "constraints.close", READ, { expectedVersion: 2, completionDate: "2026-09-20" }),
    target("POST", `/constraints/${CONSTRAINT}/close-follow-up`, closeFollowUp, C, "constraints.close_follow_up", READ, { expectedVersion: 2, successorDescription: "Next" }),
    target("POST", `/constraints/${CONSTRAINT}/void`, voidConstraint, C, "constraints.void", READ, { expectedVersion: 2, voidReason: "Duplicate" }),
    target("POST", `/constraints/${CONSTRAINT}/reopen`, reopenConstraint, C, "constraints.reopen", READ, { expectedVersion: 4, toState: "identified" }),
    target("POST", "/constraint-categories", createCategory, {}, "constraint_categories.create", null, { prefix: "7", title: "Logistics" }),
    target("PATCH", `/constraint-categories/${CATEGORY}`, updateCategory, G, "constraint_categories.update", LIST, { expectedVersion: 1, title: "Renamed" }),
    target("POST", `/constraint-categories/${CATEGORY}/deactivate`, deactivateCategory, G, "constraint_categories.deactivate", LIST, { expectedVersion: 1 }),
    target("POST", "/constraint-categories/reorder", reorderCategories, {}, "constraint_categories.reorder", null, { orderedCategoryIds: [CATEGORY], expectedVersions: [1] }),
  ];

  const name = (entry: Target) => `${entry.method} ${entry.path.slice(BASE.length)}`;
  const ALL = TARGETS.map((entry) => [name(entry), entry] as const);
  const OF_CONSTRAINT = ALL.filter(([, entry]) => entry.admission === READ);
  const OF_CATEGORY = ALL.filter(([, entry]) => entry.admission === LIST);
  const ADMITTED = ALL.filter(([, entry]) => entry.admission !== null);

  function answer(result: unknown) {
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
    const read = structuredClone(PYTHON["constraints.read"]) as {
      constraint: Record<string, unknown>;
    };
    read.constraint.project_id = projectId;
    return read;
  }

  type Sent = { readonly capability: string; readonly document: Record<string, unknown> };

  /** Each capability from `answers`, else its committed Python success. */
  function stubGateway(answers: Record<string, () => Response> = {}) {
    const sent: Sent[] = [];
    const inner = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      const href = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      const capability = href.slice(GATEWAY.length);
      sent.push({ capability, document: JSON.parse(String(init?.body)) as Record<string, unknown> });
      return answers[capability]?.() ?? answer(PYTHON[capability]);
    });
    vi.stubGlobal("fetch", withSessionServiceFetch(inner as never));
    return { sent, inner };
  }

  function send(
    entry: Target,
    session: string | null,
    payload: unknown,
    { origin = ORIGIN as string | null, raw = false } = {},
  ) {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (origin) headers.origin = origin;
    const value = new NextRequest(`${ORIGIN}${entry.path}`, {
      method: entry.method,
      headers,
      body: raw ? String(payload) : JSON.stringify(payload),
    });
    if (session) value.cookies.set(SESSION_COOKIE_NAME, session);
    return entry.handler(value, { params: Promise.resolve(entry.params) as Promise<never> });
  }

  const mutated = (sent: readonly Sent[], entry: Target) =>
    sent.filter((call) => call.capability === entry.capability);

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

  it("drives exactly the routes AUTHORING_MUTATIONS names", () => {
    const routeFile = (entry: Target) =>
      `projects/[projectId]${entry.path
        .slice(BASE.length)
        .replace(CONSTRAINT, "[constraintId]")
        .replace(CATEGORY, "[categoryId]")}/route.ts`;
    expect(TARGETS.map((entry) => `${entry.method} ${routeFile(entry)}`)).toEqual(
      AUTHORING_MUTATIONS.map(([method, path]) => `${method} ${path}`),
    );
    expect(TARGETS.map((entry) => entry.capability).sort()).toEqual(AUTHORING_CAPABILITIES);
  });

  it.each(ALL)("%s refuses a cross-site Origin with 403 before the body or session is read", async (_name, entry) => {
    const session = await cookie();
    const { inner } = stubGateway();
    for (const [who, body] of [
      [session, entry.body],
      // No session and an unparseable body: Origin is still what answers.
      [null, "{not json"],
    ] as const) {
      const response = await send(entry, who, body, { origin: "https://evil.test", raw: typeof body === "string" });
      expect(response.status).toBe(403);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toMatchObject({ error: { code: "cross_site_request" } });
    }
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(ALL)("%s answers 401 without a session and never reaches the gateway", async (_name, entry) => {
    const { inner } = stubGateway();
    const response = await send(entry, null, entry.body);
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(ALL)("%s rejects a caller-supplied Principal with 400 caller_supplied_principal", async (_name, entry) => {
    const session = await cookie();
    const { inner } = stubGateway();
    for (const field of ["principal_id", "principalId"]) {
      const response = await send(entry, session, { ...entry.body, [field]: "syn-bbbb0002" });
      expect(response.status, field).toBe(400);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toMatchObject({ error: { code: "caller_supplied_principal" } });
    }
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(ALL)("%s refuses a body Project, telemetry field or capability name with 400", async (_name, entry) => {
    const session = await cookie();
    const { inner } = stubGateway();
    for (const extra of [
      { projectId: PROJECT },
      { projectId: FOREIGN_PROJECT },
      { project_id: FOREIGN_PROJECT },
      { clientContext: "web" },
      { client_context: "web" },
      { correlationId: "corr_aaaaaaaa11111111" },
      { correlation_id: "corr_aaaaaaaa11111111" },
      { capability: "constraints.void" },
    ]) {
      const response = await send(entry, session, { ...entry.body, ...extra });
      expect(response.status, JSON.stringify(extra)).toBe(400);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toMatchObject({ error: { code: "invalid_request" } });
    }
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(ALL.filter(([, entry]) => entry.admission === null))(
    "%s carries the path Project and needs no preflight",
    async (_name, entry) => {
      const session = await cookie();
      const { sent } = stubGateway();
      const response = await send(entry, session, entry.body);
      expect(response.status).toBe(200);
      expect(sent.map((call) => call.capability)).toEqual([entry.capability]);
      expect((sent[0].document.payload as Record<string, unknown>).project_id).toBe(PROJECT);
    },
  );

  it.each(OF_CONSTRAINT)(
    "%s answers another Project's Constraint with the detail read's own 404 and never mutates",
    async (_name, entry) => {
      const session = await cookie();
      const { sent } = stubGateway({ [READ]: () => answer(readIn(FOREIGN_PROJECT)) });
      const refused = await send(entry, session, entry.body);
      expect(sent.map((call) => call.capability)).toEqual([READ]);
      expect(mutated(sent, entry)).toEqual([]);

      stubGateway({ [READ]: () => answer(readIn(FOREIGN_PROJECT)) });
      const readRequest = new NextRequest(`${ORIGIN}${BASE}/constraints/${CONSTRAINT}`);
      readRequest.cookies.set(SESSION_COOKIE_NAME, session);
      const read = await detail(readRequest, {
        params: Promise.resolve({ projectId: PROJECT, constraintId: CONSTRAINT }),
      });

      expect(refused.status).toBe(404);
      expect(read.status).toBe(404);
      for (const header of ["cache-control", "content-type"]) {
        expect(refused.headers.get(header), header).toBe(read.headers.get(header));
      }
      const [refusedText, readText] = [await refused.text(), await read.text()];
      expect(refusedText).toBe(readText);
      expect(refusedText).not.toContain(FOREIGN_PROJECT);
      expect(refusedText).not.toContain(CONSTRAINT);
    },
  );

  it.each(OF_CATEGORY)(
    "%s answers a Category outside the URL's Project with 404 and never mutates",
    async (_name, entry) => {
      const session = await cookie();
      const { sent } = stubGateway();
      // The listed fixture's only Category is `CATEGORY`; ask for another one.
      const foreign = { ...entry, params: { ...entry.params, categoryId: OTHER_CATEGORY } };
      const refused = await send(foreign, session, entry.body);
      expect(sent.map((call) => call.capability)).toEqual([LIST]);
      expect(mutated(sent, entry)).toEqual([]);
      expect(refused.status).toBe(404);
      expect(refused.headers.get("cache-control")).toBe("private, no-store");
      expect(await refused.json()).toEqual({
        error: { errorClass: "not_found", code: "not_found", message: "Category was not found" },
      });
    },
  );

  it.each(OF_CATEGORY)(
    "%s answers a Category listed under another Project with 404 and never mutates",
    async (_name, entry) => {
      const session = await cookie();
      const list = structuredClone(PYTHON[LIST]) as { categories: Record<string, unknown>[] };
      for (const category of list.categories) category.project_id = FOREIGN_PROJECT;
      const { sent } = stubGateway({ [LIST]: () => answer(list) });
      const refused = await send(entry, session, entry.body);
      expect(mutated(sent, entry)).toEqual([]);
      expect(refused.status).toBe(404);
    },
  );

  const PREFLIGHT_REFUSALS = [
    [403, "denied", "authorization"],
    [404, "not_found", "not_found"],
    [429, "rate_limited", "unavailable"],
    [503, "unavailable", "unavailable"],
  ] as const;

  it.each(
    ADMITTED.flatMap(([label, entry]) =>
      PREFLIGHT_REFUSALS.map(([status, code, errorClass]) => [label, status, code, errorClass, entry] as const),
    ),
  )(
    "%s returns a %s %s preflight refusal typed and never mutates",
    async (_name, status, code, errorClass, entry) => {
      const session = await cookie();
      const { sent } = stubGateway({ [entry.admission!]: () => problem(status, code) });
      const response = await send(entry, session, entry.body);
      expect(sent.map((call) => call.capability)).toEqual([entry.admission]);
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      const refusal = await response.json();
      expect(refusal.error).toMatchObject({ code, errorClass });
    },
  );

  it.each(ADMITTED)("%s asks the preflight and the mutation as the same Principal", async (_name, entry) => {
    const session = await cookie();
    const { sent } = stubGateway();
    const response = await send(entry, session, entry.body);
    expect(response.status).toBe(200);
    expect(sent.map((call) => call.capability)).toEqual([entry.admission, entry.capability]);
    const [preflight, mutation] = sent;
    expect(preflight.document.principal_id).toEqual(expect.stringMatching(/^prn_[0-9a-f]{32}$/));
    expect(mutation.document.principal_id).toBe(preflight.document.principal_id);
    // The preflight is the URL Project's: its own Project, or the record alone.
    expect(preflight.document.payload).toEqual(
      entry.admission === READ
        ? { constraint_id: CONSTRAINT }
        : { project_id: PROJECT, states: ["active", "inactive", "archived"] },
    );
  });
});
