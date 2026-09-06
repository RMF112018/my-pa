// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as searchGet } from "@/app/api/search/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";
import { ENTITY_SUMMARY } from "@/lib/api/decode/capabilities/_entity-fixtures";
import { TASK_LIST_ENTRY } from "@/lib/api/decode/capabilities/tasks.list.test";

const ORIGIN = "http://localhost:3000";
const ENROLLMENT_ID = "enr_aaaaaaaa11111111";
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-21T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

const REPORT_MATCH = {
  report_id: "rpt_aaaaaaaa11111111",
  title: "E2E morning brief collector",
  snippet: "morning brief",
  cycle_run_id: "micr_aaaaaaaa11111111",
  stage: "collector",
  artifact_kind: "collector_candidates",
};

const GOODNOTES_PAGE_HIT = {
  kind: "page",
  id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  title: "Synthetic page",
  snippet: "synthetic page transcription must not leak into href",
  notebook_id: "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa",
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  freshness: "2026-08-09T12:00:00.000Z",
};

const EMPTY = {
  "tasks.search": { tasks: [] },
  "commitments.search": {
    commitments: [],
    counterparty_options: [],
    counterparty_options_truncated: false,
  },
  "capture.search": { matches: [], searchable_versions: 0, stored_versions: 0 },
  "reports.search": { items: [] },
  "entities.search": { entities: [] },
  "knowledge.search": { matches: [] },
  "goodnotes.search": { hits: [] },
} as const;

function gatewayOk(result: unknown, coverageState = "not_enrolled") {
  return new Response(
    JSON.stringify({
      result,
      disclosure: { ...DISCLOSURE, coverage: { state: coverageState } },
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

function capabilityOf(url: string | URL | Request): string {
  const href = String(url);
  const match = href.match(/\/v1\/([A-Za-z0-9_.]+)$/);
  return match?.[1] ?? href;
}

async function cookie() {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
    }),
  );
  return (response as unknown as { cookies: { get(name: string): { value: string } } }).cookies.get(
    SESSION_COOKIE_NAME,
  ).value;
}

function request(session: string, path: string) {
  const value = new NextRequest(`${ORIGIN}${path}`);
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function stubSearchGateway(impl?: (url: string | URL | Request, init?: RequestInit) => unknown) {
  const gateway = impl ? vi.fn(impl) : vi.fn();
  vi.stubGlobal("fetch", withSessionServiceFetch(gateway));
  return gateway;
}

function emptyFanout(
  overrides: Partial<Record<keyof typeof EMPTY, unknown>> = {},
  coverage: Partial<Record<keyof typeof EMPTY, string>> = {},
) {
  return stubSearchGateway(async (url) => {
    const capability = capabilityOf(url) as keyof typeof EMPTY;
    const result = capability in overrides ? overrides[capability] : EMPTY[capability];
    return gatewayOk(result ?? {}, coverage[capability]);
  });
}

function searchUrls(gateway: ReturnType<typeof vi.fn>) {
  return gateway.mock.calls.map((call) => String(call[0]));
}

function payloadOf(gateway: ReturnType<typeof vi.fn>, capability: string) {
  const call = gateway.mock.calls.find((entry) => String(entry[0]).includes(`/v1/${capability}`));
  const body = call?.[1]?.body;
  return typeof body === "string" ? (JSON.parse(body) as { payload?: Record<string, unknown> }) : {};
}

beforeEach(() => {
  resetSessionRegistry();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Federated Search BFF", () => {
  it("refuses a missing q before any gateway search", async () => {
    const gateway = stubSearchGateway();
    const response = await searchGet(request(await cookie(), "/api/search"));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "invalid_request" },
    });
    expect(searchUrls(gateway).some((url) => /\/v1\/.+\.search$/.test(url))).toBe(false);
    expect(gateway).not.toHaveBeenCalled();
  });

  it("fans out to the six admitted search capabilities and does not call knowledge.search", async () => {
    const gateway = emptyFanout();
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const urls = searchUrls(gateway);
    expect(urls.filter((url) => url.includes("/v1/tasks.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/v1/commitments.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/v1/capture.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/v1/reports.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/v1/entities.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/v1/goodnotes.search"))).toHaveLength(1);
    expect(urls.some((url) => url.includes("/v1/knowledge.search"))).toBe(false);
    expect(urls.some((url) => url.includes("/v1/entities.resolve"))).toBe(false);
    expect(urls.some((url) => url.includes("/v1/entities.list"))).toBe(false);
    expect(urls.some((url) => url.includes("/v1/tasks.list"))).toBe(false);
    expect(urls.some((url) => url.includes("/v1/capture.list"))).toBe(false);
    expect(payloadOf(gateway, "goodnotes.search").payload).toEqual({
      query: "morning brief",
      page_size: 10,
    });
  });

  it("adds knowledge.search with enrollment_id when enrollmentId is well-formed", async () => {
    const gateway = emptyFanout();
    const response = await searchGet(
      request(await cookie(), `/api/search?q=morning%20brief&enrollmentId=${ENROLLMENT_ID}`),
    );
    expect(response.status).toBe(200);
    const urls = searchUrls(gateway);
    expect(urls.filter((url) => url.endsWith("/v1/knowledge.search"))).toHaveLength(1);
    expect(urls.filter((url) => url.endsWith("/v1/goodnotes.search"))).toHaveLength(1);
    expect(urls).toHaveLength(7);
    expect(payloadOf(gateway, "knowledge.search").payload).toMatchObject({
      enrollment_id: ENROLLMENT_ID,
      query: "morning brief",
    });
  });

  it("refuses a malformed enrollmentId before any gateway call", async () => {
    const gateway = stubSearchGateway();
    const response = await searchGet(
      request(await cookie(), "/api/search?q=morning%20brief&enrollmentId=not-an-id"),
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "invalid_identifier" },
    });
    expect(gateway).not.toHaveBeenCalled();
  });

  it("returns searched hitCount 0 for empty complete domains and omits inactive planes", async () => {
    emptyFanout();
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const body = await response.json();
    expect(body.shape).toBe("backend");
    expect(body.hits).toEqual([]);
    expect(body.disclosure.coverage).toBe("partial");
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    for (const domain of ["tasks", "commitments", "capture", "reports", "entities", "goodnotes"]) {
      expect(byDomain[domain]).toMatchObject({ state: "searched", hitCount: 0 });
    }
    expect(byDomain.knowledge).toMatchObject({ state: "knowledge_not_enrolled", hitCount: 0 });
    expect(byDomain.goodnotes).not.toMatchObject({
      state: "omitted",
      reason: "goodnotes_not_activated",
    });
    expect(byDomain.meetings).toMatchObject({ state: "omitted", reason: "no_search_capability" });
    expect(byDomain.projects).toMatchObject({ state: "omitted", reason: "no_search_capability" });
    expect(byDomain.canvas).toMatchObject({ state: "omitted", reason: "no_search_capability" });
    expect(byDomain.relationship_memory).toMatchObject({
      state: "omitted",
      reason: "not_browser_admitted",
    });
    for (const domain of ["meetings", "projects", "canvas", "relationship_memory"]) {
      expect(byDomain[domain].state).not.toBe("searched");
    }
  });

  it("treats backend coverage unavailable as unavailable, not searched hitCount 0", async () => {
    emptyFanout({}, { "reports.search": "unavailable" });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.reports).toMatchObject({ state: "unavailable", hitCount: 0 });
    expect(byDomain.reports.state).not.toBe("searched");
    expect(byDomain.tasks).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.commitments).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.capture).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.entities).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.goodnotes).toMatchObject({ state: "searched", hitCount: 0 });
    expect(body.hits).toEqual([]);
  });

  it("returns searched GoodNotes hits without substituting knowledge.search", async () => {
    const gateway = emptyFanout({ "goodnotes.search": { hits: [GOODNOTES_PAGE_HIT] } });
    const response = await searchGet(request(await cookie(), "/api/search?q=synthetic%20page"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.goodnotes).toMatchObject({
      state: "searched",
      hitCount: 1,
      capability: "goodnotes.search",
    });
    expect(byDomain.goodnotes.state).not.toBe("omitted");
    const goodnotesHits = (body.hits as Array<{ domain: string; capability?: string; item: unknown }>).filter(
      (hit) => hit.domain === "goodnotes",
    );
    expect(goodnotesHits).toHaveLength(1);
    expect(goodnotesHits[0]?.capability).toBe("goodnotes.search");
    expect(goodnotesHits[0]?.item).toEqual(GOODNOTES_PAGE_HIT);
    expect(searchUrls(gateway).some((url) => url.includes("/v1/knowledge.search"))).toBe(false);
  });

  it("keeps other domains usable when GoodNotes is unavailable, and never uses searched hitCount 0 as failure", async () => {
    emptyFanout({}, { "goodnotes.search": "unavailable" });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.goodnotes).toMatchObject({ state: "unavailable", hitCount: 0 });
    expect(byDomain.goodnotes.state).not.toBe("searched");
    expect(byDomain.goodnotes).not.toEqual(expect.objectContaining({ state: "searched", hitCount: 0 }));
    expect(byDomain.tasks).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.commitments).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.capture).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.reports).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.entities).toMatchObject({ state: "searched", hitCount: 0 });
    expect(body.disclosure.coverage).toBe("partial");
    expect((body.hits as Array<{ domain: string }>).some((hit) => hit.domain === "goodnotes")).toBe(false);
  });

  it("treats a GoodNotes contract failure as unavailable without blanking other domains", async () => {
    emptyFanout({ "goodnotes.search": { leaked: "must-not-dump" } });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(JSON.stringify(body)).not.toContain("must-not-dump");
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.goodnotes).toMatchObject({
      state: "unavailable",
      reason: "upstream_contract_invalid",
      hitCount: 0,
    });
    expect(byDomain.goodnotes).not.toEqual(expect.objectContaining({ state: "searched", hitCount: 0 }));
    expect(byDomain.tasks).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.entities).toMatchObject({ state: "searched", hitCount: 0 });
  });

  it("counts a successful empty GoodNotes result as searched hitCount 0", async () => {
    emptyFanout({ "goodnotes.search": { hits: [] } });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.goodnotes).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.goodnotes.reason).toBeUndefined();
  });

  it("fails closed on an omitted tasks array without blanking other domains or leaking extras", async () => {
    emptyFanout({ "tasks.search": { leaked: "must-not-dump" } });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain("must-not-dump");
    expect(body).not.toHaveProperty("leaked");
    const byDomain = Object.fromEntries(
      (body.coverage as Array<{ domain: string; state: string; hitCount?: number; reason?: string }>).map(
        (row) => [row.domain, row],
      ),
    );
    expect(byDomain.tasks).toMatchObject({
      state: "unavailable",
      reason: "upstream_contract_invalid",
      hitCount: 0,
    });
    expect(byDomain.commitments).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.capture).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.reports).toMatchObject({ state: "searched", hitCount: 0 });
    expect(byDomain.entities).toMatchObject({ state: "searched", hitCount: 0 });
  });

  it("answers not_implemented for the whole route under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const gateway = stubSearchGateway();
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({
      error: { code: "not_implemented" },
    });
    expect(gateway).not.toHaveBeenCalled();
  });

  it("keeps entity hits as EntitySummary without resolution", async () => {
    emptyFanout({ "entities.search": { entities: [ENTITY_SUMMARY] } });
    const response = await searchGet(request(await cookie(), "/api/search?q=Pat%20Synthetic"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const entityHits = (body.hits as Array<{ domain: string; item: unknown }>).filter(
      (hit) => hit.domain === "entities",
    );
    expect(entityHits).toHaveLength(1);
    expect(entityHits[0]?.item).toEqual(ENTITY_SUMMARY);
    expect(JSON.stringify(body)).not.toContain("resolution");
    expect(body).not.toHaveProperty("resolution");
  });

  it("keeps report hits as ReportSearchMatch, not Brief items", async () => {
    emptyFanout({ "reports.search": { items: [REPORT_MATCH] } });
    const response = await searchGet(request(await cookie(), "/api/search?q=morning%20brief"));
    expect(response.status).toBe(200);
    const body = await response.json();
    const reportHits = (
      body.hits as Array<{ domain: string; item: { report_id?: string; artifact_kind?: string } }>
    ).filter((hit) => hit.domain === "reports");
    expect(reportHits).toHaveLength(1);
    expect(reportHits[0]?.item.report_id).toBe(REPORT_MATCH.report_id);
    expect(reportHits[0]?.item.artifact_kind).toBe("collector_candidates");
    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain("brief-item");
    expect(serialized).not.toContain("BriefSection");
    expect(serialized).not.toContain("BriefItem");
    expect(serialized).not.toContain("data-testid");
  });
});
