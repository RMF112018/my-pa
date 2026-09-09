// @vitest-environment node
/**
 * T08-07 / T08-10: the trust boundary and the fixture boundary, structurally.
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
import { GET as register } from "@/app/api/project-controls/projects/[projectId]/constraints/route";
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

describe("the Constraint BFF surface is read-only", () => {
  it("ships five routes and no more", () => {
    const routes = PROJECT_CONTROL_SOURCES.filter((path) => path.endsWith("route.ts"));
    expect(routes.map((path) => path.slice(PROJECT_CONTROLS.length + 1)).sort()).toEqual([
      "projects/[projectId]/constraint-categories/route.ts",
      "projects/[projectId]/constraints/[constraintId]/history/route.ts",
      "projects/[projectId]/constraints/[constraintId]/route.ts",
      "projects/[projectId]/constraints/overview/route.ts",
      "projects/[projectId]/constraints/route.ts",
    ]);
  });

  it("exports no mutation handler and reaches no mutation helper", () => {
    for (const path of PROJECT_CONTROL_SOURCES) {
      const source = text(path);
      expect(source, path).not.toMatch(/export\s+(async\s+)?function\s+(POST|PATCH|PUT|DELETE)\b/);
      expect(source, path).not.toMatch(/export\s+const\s+(POST|PATCH|PUT|DELETE)\b/);
      expect(source, path).not.toMatch(/\bworkPost\b/);
      expect(source, path).not.toMatch(/\badmitBrowserMutation\b/);
    }
  });

  it("addresses only the six admitted read capabilities and no mutation or sync name", () => {
    const addressed = new Set<string>();
    for (const path of PROJECT_CONTROL_SOURCES) {
      for (const match of text(path).matchAll(/"(constraints?[_.][a-z_.]+)"/g)) {
        addressed.add(match[1]);
      }
    }
    expect([...addressed].sort()).toEqual([
      "constraint_categories.list",
      "constraints.history",
      "constraints.list",
      "constraints.overview",
      "constraints.read",
      "constraints.search",
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
  ])("no Constraint source mentions %s (%s)", (pattern) => {
    for (const path of CONSTRAINT_SOURCES) {
      expect(code(path), path).not.toMatch(pattern);
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
