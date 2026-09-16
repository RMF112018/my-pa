// @vitest-environment node
/**
 * The two portfolio Constraint read routes as HTTP.
 *
 * Transport, not UI. Three properties are load-bearing here and each has its own
 * section below:
 *
 * 1. **One gateway call per request.** Plan section 15 says a portfolio BFF route
 *    calls the server portfolio capability once and that client fanout is
 *    prohibited. The tests count invocations and name them, so a route that
 *    enumerated Projects and called an exact-Project capability per Project would
 *    fail on both the count and the names.
 * 2. **No Project identifier is admitted.** A portfolio route that accepted one
 *    would answer differently for a Project the Principal owns than for one it
 *    does not, which is an ownership oracle. Every spelling is refused as an
 *    unknown field before a capability is spent.
 * 3. **Fail-closed decode and nondisclosing errors.** A malformed success is a
 *    `503 unavailable`, never a coerced page; a refusal echoes no identifier.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as portfolioRegister } from "@/app/api/project-controls/portfolio/constraints/route";
import { GET as portfolioOverview } from "@/app/api/project-controls/portfolio/constraints/overview/route";
import { GET as register } from "@/app/api/project-controls/projects/[projectId]/constraints/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const PORTFOLIO = "/api/project-controls/portfolio/constraints";
/** A well-formed Project identifier, used only as a value a caller might try to send. */
const PROJECT = "prj_aaaaaaaa11111111";
const FOREIGN_PROJECT = "prj_bbbbbbbb22222222";
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

/** Every call the route made that was a capability invocation rather than session work. */
function capabilities(sent: readonly Sent[]): readonly string[] {
  return sent.map((call) => call.url.split("/v1/")[1]).filter((name) => name !== undefined);
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

describe("portfolio route to capability mapping", () => {
  it("answers the two portfolio routes from the three portfolio capabilities", async () => {
    const session = await cookie();
    const { sent } = stubGateway((url) => success(url.split("/v1/")[1]));
    const answers = [
      await portfolioRegister(get(session, PORTFOLIO)),
      await portfolioRegister(get(session, `${PORTFOLIO}?q=steel`)),
      await portfolioOverview(get(session, `${PORTFOLIO}/overview`)),
    ];
    expect(answers.map((response) => response.status)).toEqual([200, 200, 200]);
    expect(capabilities(sent)).toEqual([
      "constraints.portfolio_list",
      "constraints.portfolio_search",
      "constraints.portfolio_overview",
    ]);
    for (const response of answers) {
      expect(response.headers.get("cache-control")).toBe("private, no-store");
    }
  });

  it("states the constraint_read purpose and a Principal the browser never sent", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.portfolio_list"));
    await portfolioRegister(get(session, PORTFOLIO));
    expect(sent[0].document.purpose).toBe("constraint_read");
    expect(sent[0].document.principal_id).toEqual(expect.any(String));
    expect(String(sent[0].document.principal_id)).not.toContain("syn-aaaa0001");
  });

  it("sends the empty payload for the overview, which has no fields at all", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.portfolio_overview"));
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview`));
    expect(response.status).toBe(200);
    expect(sent[0].document.payload).toEqual({});
  });

  it("decodes one entry per Project and publishes no portfolio-wide roll-up", async () => {
    const session = await cookie();
    stubGateway(() => success("constraints.portfolio_overview"));
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview`));
    expect(response.status).toBe(200);
    const answer = (await response.json()) as {
      overview: { projects: Record<string, unknown>[]; asOf: string };
    };
    expect(answer.overview.projects).toHaveLength(2);
    expect(answer.overview.projects.map((entry) => entry.projectId)).toEqual([
      "prj_aaaaaaaa11111111",
      "prj_cccccccc33333333",
    ]);
    // Each entry keeps its own calendar, and the canonical overview names.
    expect(answer.overview.projects.map((entry) => entry.projectTimezone)).toEqual([
      "America/New_York",
      "America/Chicago",
    ]);
    for (const entry of answer.overview.projects) {
      expect(entry).toHaveProperty("averageOpenAgeBusinessDays");
      expect(entry).toHaveProperty("syncHealth");
      expect(entry).not.toHaveProperty("averageOpenAge");
      expect(entry).not.toHaveProperty("synchronizationHealth");
    }
    expect(typeof answer.overview.asOf).toBe("string");
    for (const name of ["totalOpen", "overdue", "dueSoon", "needsAttention"]) {
      expect(answer.overview).not.toHaveProperty(name);
    }
  });
});

describe("a portfolio route spends exactly one capability invocation", () => {
  it.each([
    ["the portfolio Register", PORTFOLIO, "constraints.portfolio_list"],
    ["the portfolio search", `${PORTFOLIO}?q=steel`, "constraints.portfolio_search"],
    ["the portfolio overview", `${PORTFOLIO}/overview`, "constraints.portfolio_overview"],
  ])("%s calls the gateway once and calls no exact-Project capability", async (
    _name,
    path,
    capability,
  ) => {
    const session = await cookie();
    const { sent } = stubGateway((url) => success(url.split("/v1/")[1]));
    const route = path.includes("/overview") ? portfolioOverview : portfolioRegister;
    const response = await route(get(session, path));
    expect(response.status).toBe(200);
    // The count is the claim: a route that enumerated Projects and read each one
    // would be a fanout, and would show up here as more than one invocation.
    expect(capabilities(sent)).toEqual([capability]);
    expect(capabilities(sent)).not.toContain("constraints.list");
    expect(capabilities(sent)).not.toContain("constraints.search");
    expect(capabilities(sent)).not.toContain("constraints.overview");
    expect(capabilities(sent)).not.toContain("continuity.projects");
  });

  it("keeps the single call when every declared filter is supplied", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.portfolio_list"));
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
    const response = await portfolioRegister(get(session, `${PORTFOLIO}?${query}`));
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    // Exactly the Register payload minus the Project, renamed to the command's
    // own field names. `sort_order`, deliberately not `direction`.
    expect(sent[0].document.payload).toEqual({
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
      sort_order: "desc",
      grouping: "status",
      limit: 25,
      cursor: "opaque-cursor",
    });
    expect(Object.keys(sent[0].document.payload as Record<string, unknown>)).not.toContain(
      "project_id",
    );
  });

  it("applies the narrower search allowlist on the q branch, still in one call", async () => {
    const session = await cookie();
    const { sent } = stubGateway(() => success("constraints.portfolio_search"));
    const response = await portfolioRegister(
      get(session, `${PORTFOLIO}?q=steel&scope=closed&pageSize=10&cursor=c1`),
    );
    expect(response.status).toBe(200);
    expect(capabilities(sent)).toEqual(["constraints.portfolio_search"]);
    expect(sent[0].document.payload).toEqual({
      query: "steel",
      scope: "closed",
      limit: 10,
      cursor: "c1",
    });
  });
});

describe("no Project identifier is admitted on a portfolio route", () => {
  it.each([
    "project_id=prj_aaaaaaaa11111111",
    "projectId=prj_aaaaaaaa11111111",
    "project=prj_aaaaaaaa11111111",
    "projects=prj_aaaaaaaa11111111",
    "project_ids=prj_aaaaaaaa11111111",
    "projectIds=prj_aaaaaaaa11111111",
  ])("refuses %s on the portfolio Register with no gateway call", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await portfolioRegister(get(session, `${PORTFOLIO}?${query}`));
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const answer = await response.json();
    expect(answer).toMatchObject({ error: { code: "invalid_request" } });
    // The refusal is identical whether the Principal owns the named Project or
    // not, because no Project was ever consulted: nothing reached the gateway.
    expect(inner).not.toHaveBeenCalled();
    expect(JSON.stringify(answer)).not.toContain(PROJECT);
  });

  it.each([
    "project_id=prj_aaaaaaaa11111111",
    "projectId=prj_aaaaaaaa11111111",
  ])("refuses %s on the portfolio search branch with no gateway call", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await portfolioRegister(get(session, `${PORTFOLIO}?q=steel&${query}`));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([
    "project_id=prj_aaaaaaaa11111111",
    "projectId=prj_aaaaaaaa11111111",
    "scope=open",
    "pageSize=5",
    "q=steel",
  ])("refuses %s on the portfolio overview, which takes no query at all", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview?${query}`));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it("answers an owned and an unowned Project identifier identically", async () => {
    const session = await cookie();
    const { inner } = stubGateway();
    const answers = await Promise.all(
      [PROJECT, FOREIGN_PROJECT, "prj_zzzzzzzz99999999"].map(async (candidate) => {
        const response = await portfolioRegister(
          get(session, `${PORTFOLIO}?project_id=${candidate}`),
        );
        return { status: response.status, body: await response.json() };
      }),
    );
    // One answer, three times: the route cannot be used to learn whether any
    // Project exists or whom it belongs to, because it never asked.
    expect(answers.map((answer) => answer.status)).toEqual([400, 400, 400]);
    const messages = new Set(
      answers.map((answer) =>
        String((answer.body as { error: { message: string } }).error.message),
      ),
    );
    expect(messages.size).toBe(1);
    expect(inner).not.toHaveBeenCalled();
  });
});

describe("the portfolio query vocabulary is closed", () => {
  it.each([
    "direction=desc",
    "principal_id=syn-bbbb0002",
    "principalId=syn-bbbb0002",
    "limit=25",
    "statuses=open",
    "anything=1",
  ])("refuses the undeclared portfolio parameter %s", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await portfolioRegister(get(session, `${PORTFOLIO}?${query}`));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each([
    "scope=everything",
    "status=reopen",
    "sync=partial",
    "quality=unknown",
    "recent=last_week",
    "sort=title",
    "dir=descending",
    "group=owner",
    "overdue=yes",
    "pageSize=1.5",
  ])("refuses the out-of-vocabulary portfolio value %s", async (query) => {
    const session = await cookie();
    const { inner } = stubGateway();
    const response = await portfolioRegister(get(session, `${PORTFOLIO}?${query}`));
    expect(response.status).toBe(400);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(["sort=code", "group=category", "overdue=true", "status=identified"])(
    "refuses %s alongside a search term rather than dropping it",
    async (filter) => {
      const session = await cookie();
      const { inner } = stubGateway();
      const response = await portfolioRegister(get(session, `${PORTFOLIO}?q=steel&${filter}`));
      expect(response.status).toBe(400);
      expect(inner).not.toHaveBeenCalled();
    },
  );
});

describe("both truncation reasons are carried, and neither is interpreted", () => {
  it("passes an ordinary page-size truncation through with its continuation cursor", async () => {
    const session = await cookie();
    stubGateway(() =>
      success("constraints.portfolio_list", {
        ...DISCLOSURE,
        truncation: { is_truncated: true, reason: "page_size_reached", next_cursor: "c2" },
      }),
    );
    const response = await portfolioRegister(get(session, PORTFOLIO));
    expect(response.status).toBe(200);
    const answer = (await response.json()) as { disclosure: Record<string, unknown> };
    expect(answer.disclosure.truncated).toBe(true);
    expect(answer.disclosure.nextCursor).toBe("c2");
  });

  it("carries the owned-Project cap as a truncation with no continuation at all", async () => {
    const session = await cookie();
    stubGateway(() =>
      success("constraints.portfolio_list", {
        ...DISCLOSURE,
        truncation: { is_truncated: true, reason: "portfolio_project_limit_reached" },
        limitations: ["listing_has_no_continuation_cursor"],
      }),
    );
    const response = await portfolioRegister(get(session, PORTFOLIO));
    expect(response.status).toBe(200);
    const answer = (await response.json()) as { disclosure: Record<string, unknown> };
    expect(answer.disclosure.truncated).toBe(true);
    expect(answer.disclosure).not.toHaveProperty("nextCursor");
    expect(answer.disclosure.limitations).toContain("listing_has_no_continuation_cursor");
    expect(answer.disclosure.coverage).toBe("partial");
  });

  it("carries the cap on the overview, which issues no cursor even when whole", async () => {
    const session = await cookie();
    stubGateway(() =>
      success("constraints.portfolio_overview", {
        ...DISCLOSURE,
        truncation: { is_truncated: true, reason: "portfolio_project_limit_reached" },
        limitations: ["listing_has_no_continuation_cursor"],
      }),
    );
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview`));
    expect(response.status).toBe(200);
    const answer = (await response.json()) as { disclosure: Record<string, unknown> };
    expect(answer.disclosure.truncated).toBe(true);
    expect(answer.disclosure).not.toHaveProperty("nextCursor");
  });

  it("does not interpret a truncation reason it has never seen", async () => {
    const session = await cookie();
    stubGateway(() =>
      success("constraints.portfolio_list", {
        ...DISCLOSURE,
        truncation: { is_truncated: true, reason: "a_reason_from_a_later_package" },
      }),
    );
    const response = await portfolioRegister(get(session, PORTFOLIO));
    expect(response.status).toBe(200);
    const answer = (await response.json()) as { disclosure: Record<string, unknown> };
    expect(answer.disclosure.truncated).toBe(true);
  });
});

describe("session behaviour is 401 or 503, never a silent empty portfolio", () => {
  it("answers 401 without a session and never reaches the gateway", async () => {
    const { inner } = stubGateway();
    const response = await portfolioRegister(get(null, PORTFOLIO));
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({ error: { code: "unauthenticated" } });
    expect(inner).not.toHaveBeenCalled();
  });

  it("answers 503 authority_unavailable when the session authority cannot answer", async () => {
    const session = await cookie();
    stubGateway();
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview`));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: { code: "authority_unavailable" } });
  });
});

describe("a malformed portfolio success fails closed at the route", () => {
  const page = () =>
    structuredClone(PYTHON["constraints.portfolio_list"]) as {
      constraints: Record<string, unknown>[];
    };
  const overview = () =>
    structuredClone(PYTHON["constraints.portfolio_overview"]) as {
      overview: { projects: Record<string, unknown>[]; as_of: string };
    };

  it.each<readonly [string, unknown]>([
    ["an empty result object", {}],
    ["a row with no fields", { constraints: [{}] }],
    ["a boolean sent as a string", { constraints: [{ ...page().constraints[0], is_overdue: "false" }] }],
    ["an unknown status", { constraints: [{ ...page().constraints[0], status: "reopen" }] }],
    ["an unknown sync state", { constraints: [{ ...page().constraints[0], sync_state: "partial" }] }],
    ["a missing version", { constraints: [{ ...page().constraints[0], version: undefined }] }],
    ["the rows sent as an object", { constraints: { row: page().constraints[0] } }],
  ])("turns %s into 503 unavailable / upstream_contract_invalid", async (_name, result) => {
    const session = await cookie();
    stubGateway(() => body(result));
    const response = await portfolioRegister(get(session, PORTFOLIO));
    expect(response.status).toBe(503);
    const answer = await response.json();
    expect(answer).toMatchObject({
      state: "unavailable",
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
    expect(JSON.stringify(answer)).not.toContain("constraints");
  });

  it.each<readonly [string, unknown]>([
    ["an empty result object", {}],
    ["a missing projects array", { overview: { as_of: "2026-08-09T12:00:00Z" } }],
    ["a missing as_of", { overview: { projects: overview().overview.projects } }],
    [
      "an entry missing a required count",
      { overview: { ...overview().overview, projects: [{ ...overview().overview.projects[0], total_open: undefined }] } },
    ],
    [
      "the forbidden averageOpenAge alias on an entry",
      { overview: { ...overview().overview, projects: [{ ...overview().overview.projects[0], averageOpenAge: 4 }] } },
    ],
    [
      "the forbidden synchronizationHealth alias on an entry",
      {
        overview: {
          ...overview().overview,
          projects: [{ ...overview().overview.projects[0], synchronizationHealth: { state: "in_sync" } }],
        },
      },
    ],
    ["the projects array sent as an object", { overview: { projects: {}, as_of: "2026-08-09T12:00:00Z" } }],
  ])("turns %s on the overview into 503 upstream_contract_invalid", async (_name, result) => {
    const session = await cookie();
    stubGateway(() => body(result));
    const response = await portfolioOverview(get(session, `${PORTFOLIO}/overview`));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "unavailable", code: "upstream_contract_invalid" },
    });
  });

  it("does not convert an unavailable capability into an empty portfolio page", async () => {
    const session = await cookie();
    stubGateway(
      () =>
        new Response(
          JSON.stringify({ error: { code: "unsupported", message: "capability unavailable" } }),
          { status: 503, headers: { "content-type": "application/json" } },
        ),
    );
    const response = await portfolioRegister(get(session, PORTFOLIO));
    expect(response.status).toBeGreaterThanOrEqual(500);
    const answer = await response.json();
    expect(answer.constraints).toBeUndefined();
    expect(answer.state).not.toBe("ok");
    // A refusal names no Project, so it cannot report how many the Principal owns.
    expect(JSON.stringify(answer)).not.toContain("prj_");
  });
});

describe("the exact-Project Register is untouched by the portfolio routes", () => {
  it("still requires its path Project and still calls the exact-Project capability", async () => {
    const session = await cookie();
    const { sent } = stubGateway((url) => success(url.split("/v1/")[1]));
    const response = await register(
      get(session, `/api/project-controls/projects/${PROJECT}/constraints`),
      { params: Promise.resolve({ projectId: PROJECT }) },
    );
    expect(response.status).toBe(200);
    expect(capabilities(sent)).toEqual(["constraints.list"]);
    expect(sent[0].document.payload).toEqual({ project_id: PROJECT });
  });
});
