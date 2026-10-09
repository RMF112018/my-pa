// @vitest-environment node
/** WP03B actual BFF admission pipeline. Only session resolution and gateway HTTP
 * transport are mocked. Canonical successes come from the Python fixture.
 * Replay/lifecycle HTTP traces below prove forwarding, not database execution. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { readFileSync } from "node:fs";
import type { PrincipalSession } from "@/contracts/identity";
import type { PythonDisclosure } from "@/lib/api/gateway";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { POST as projectCreate, GET as projectList } from "./projects/route";
import { PATCH as projectUpdate, GET as projectRead } from "./projects/[projectId]/route";
import { POST as projectClose } from "./projects/[projectId]/close/route";
import { PATCH as captureRevise } from "./capture/[captureId]/route";
import { GET as meetingRead, PATCH as meetingUpdate } from "./meetings/[meetingId]/route";
import { GET as meetingList } from "./meetings/route";
import { GET as meetingSearch } from "./meetings/search/route";
import { PATCH as seriesUpdate } from "./meetings/series/[meetingSeriesId]/route";
import { GET as documentRead } from "./documents/[documentId]/route";
import { POST as documentArchive } from "./documents/[documentId]/archive/route";
import { POST as documentRestore } from "./documents/[documentId]/restore/route";

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
const suffix = "aaaaaaaa11111111";
const projectId = `prj_${suffix}`, captureId = `cap_${suffix}`, meetingId = `mtg_${suffix}`;
const meetingSeriesId = `mser_${suffix}`, documentId = `mdoc_${suffix}`;
const keyed = { expectedVersion: 1, idempotencyKey: "wp03b-key-1" };
const DISCLOSURE: PythonDisclosure = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false }, limitations: [], partial_result: false,
};
type Capability = keyof typeof fixtures;
type Scenario = {
  capability: Capability; method: string; path: string; body?: Record<string, unknown>;
  required?: string[]; pathId?: string; scalar?: string;
  run: (request: NextRequest, id?: string) => Promise<Response>;
};
const scenarios: Scenario[] = [
  { capability: "continuity.projects.create", method: "POST", path: "/api/projects", body: { name: "Synthetic project", idempotencyKey: "wp03b-key-1" }, required: ["name", "idempotencyKey"], run: projectCreate },
  { capability: "continuity.projects.update", method: "PATCH", path: `/api/projects/${projectId}`, pathId: projectId, body: { ...keyed, name: "Synthetic project" }, required: ["expectedVersion", "idempotencyKey"], run: (r, id = projectId) => projectUpdate(r, { params: Promise.resolve({ projectId: id }) }) },
  { capability: "continuity.projects.close", method: "POST", path: `/api/projects/${projectId}/close`, pathId: projectId, body: keyed, required: ["expectedVersion", "idempotencyKey"], run: (r, id = projectId) => projectClose(r, { params: Promise.resolve({ projectId: id }) }) },
  { capability: "capture.revise", method: "PATCH", path: `/api/capture/${captureId}`, pathId: captureId, body: { text: "Synthetic revision", idempotencyKey: "wp03b-revise-1" }, required: ["text", "idempotencyKey"], run: (r, id = captureId) => captureRevise(r, { params: Promise.resolve({ captureId: id }) }) },
  { capability: "meetings.read", method: "GET", path: `/api/meetings/${meetingId}`, pathId: meetingId, run: (r, id = meetingId) => meetingRead(r, { params: Promise.resolve({ meetingId: id }) }) },
  { capability: "meetings.list", method: "GET", path: "/api/meetings", scalar: "pageSize", run: meetingList },
  { capability: "meetings.search", method: "GET", path: "/api/meetings/search?q=synthetic", scalar: "q", run: meetingSearch },
  { capability: "meetings.update", method: "PATCH", path: `/api/meetings/${meetingId}`, pathId: meetingId, body: { ...keyed, title: "Synthetic occurrence" }, required: ["expectedVersion", "idempotencyKey"], run: (r, id = meetingId) => meetingUpdate(r, { params: Promise.resolve({ meetingId: id }) }) },
  { capability: "meetings.series.update", method: "PATCH", path: `/api/meetings/series/${meetingSeriesId}`, pathId: meetingSeriesId, body: { ...keyed, title: "Synthetic series" }, required: ["expectedVersion", "idempotencyKey", "title"], run: (r, id = meetingSeriesId) => seriesUpdate(r, { params: Promise.resolve({ meetingSeriesId: id }) }) },
  { capability: "documents.read", method: "GET", path: `/api/documents/${documentId}`, pathId: documentId, scalar: "includeBytes", run: (r, id = documentId) => documentRead(r, { params: Promise.resolve({ documentId: id }) }) },
  { capability: "documents.archive", method: "POST", path: `/api/documents/${documentId}/archive`, pathId: documentId, body: {}, run: (r, id = documentId) => documentArchive(r, { params: Promise.resolve({ documentId: id }) }) },
  { capability: "documents.restore", method: "POST", path: `/api/documents/${documentId}/restore`, pathId: documentId, body: {}, run: (r, id = documentId) => documentRestore(r, { params: Promise.resolve({ documentId: id }) }) },
];
const fetchStub = vi.fn<typeof fetch>();
function scenario(capability: Capability) { return scenarios.find((s) => s.capability === capability)!; }
function canonical(capability: Capability): Record<string, unknown> { return structuredClone(fixtures[capability]); }
function transport(body: unknown, status = 200) {
  fetchStub.mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}
function success(s: Scenario, result = canonical(s.capability), disclosure: PythonDisclosure = DISCLOSURE) {
  // A fresh Response is required for deliberately repeated calls (the HTTP body is consumed).
  fetchStub.mockImplementation(async () => new Response(JSON.stringify({ result, disclosure }), { status: 200, headers: { "content-type": "application/json" } }));
}
function request(s: Scenario, body: unknown = s.body, query?: string, origin = "http://localhost:3000") {
  const url = new URL(s.path, "http://localhost:3000");
  if (query !== undefined) url.search = query;
  return new NextRequest(url, {
    method: s.method, headers: { "content-type": "application/json", origin, "x-test-context": "preserved" },
    ...(s.method === "GET" || body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
function dispatched() {
  expect(fetchStub).toHaveBeenCalledTimes(1);
  return JSON.parse(String(fetchStub.mock.calls[0]![1]!.body)).payload as Record<string, unknown>;
}
async function answer(response: Response, status: number) {
  expect(response.status).toBe(status);
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  return response.json();
}
async function invalid(s: Scenario, body: unknown = s.body, query?: string, id?: string) {
  const result = await answer(await s.run(request(s, body, query), id), 400);
  expect(result.shape).toBeUndefined();
  expect(fetchStub).not.toHaveBeenCalled();
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
  resolveSessionPrincipal.mockResolvedValue(PRINCIPAL);
  vi.stubGlobal("fetch", fetchStub);
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

describe.each(scenarios)("$capability actual BFF pipeline", (s) => {
  it("roundtrips its canonical Python success with safe projection and session authority", async () => {
    success(s);
    const body = await answer(await s.run(request(s)), 200);
    const expected = canonical(s.capability);
    if (s.capability === "capture.revise") delete expected.idempotency_key;
    expect(body).toMatchObject({ shape: "backend", ...expected });
    const payload = dispatched();
    expect(payload).not.toHaveProperty("principal_id");
    expect(payload).not.toHaveProperty("principalId");
    expect(fetchStub.mock.calls[0]![0]).toBe(`http://127.0.0.1:8000/v1/${s.capability}`);
    expect(JSON.stringify(body)).not.toContain(PRINCIPAL.principalId);
    expect(JSON.stringify(body)).not.toContain("request_digest");
  });
  it("rejects unknown query before dispatch", async () => { await invalid(s, s.body, "unknown=private"); });
  it("rejects browser Principal before dispatch", async () => {
    if (s.method === "GET") await invalid(s, undefined, "principalId=browser-supplied");
    else await invalid(s, { ...s.body, principalId: "browser-supplied" });
  });
  it("refuses missing server identity without dispatch", async () => {
    resolveSessionPrincipal.mockResolvedValue(null);
    const body = await answer(await s.run(request(s)), 401);
    expect(body.error.code).toBe("unauthenticated"); expect(fetchStub).not.toHaveBeenCalled();
  });
  if (s.method !== "GET") {
    it("rejects unknown body, JSON null and wrong scalar types before dispatch", async () => {
      await invalid(s, { ...s.body, unknown: true });
      await invalid(s, null);
      for (const key of s.required ?? []) await invalid(s, { ...s.body, [key]: {} });
    });
    it("enforces real same-origin denial before principal or dispatch", async () => {
      const body = await answer(await s.run(request(s, s.body, undefined, "https://other.invalid")), 403);
      expect(body.error.code).toBe("cross_site_request");
      expect(resolveSessionPrincipal).not.toHaveBeenCalled();
      expect(fetchStub).not.toHaveBeenCalled();
    });
    for (const required of s.required ?? []) it(`requires ${required}`, async () => {
      const body = { ...s.body }; delete body[required]; await invalid(s, body);
    });
  }
  if (s.pathId) it("rejects malformed and wrong-kind path IDs before dispatch", async () => {
    for (const id of ["bad", "tsk_aaaaaaaa11111111", `${s.pathId}\n`, `${s.pathId} `]) await invalid(s, s.body, undefined, id);
  });
  if (s.scalar) it("rejects repeated scalar query before dispatch", async () => {
    await invalid(s, s.body, `${s.scalar}=1&${s.scalar}=2`);
  });
  it.each([
    ["invalid_request", 400, "validation"], ["denied", 403, "authorization"],
    ["not_found", 404, "not_found"], ["conflict", 409, "conflict"],
    ["internal_error", 500, "internal"], ["unavailable", 503, "unavailable"],
  ])("preserves safe %s refusal without retries or false success", async (code, status, errorClass) => {
    transport({ error: { code, message: "safe_field", safe_details: { request_digest: "private-marker", exception: "private-marker" } } }, Number(status));
    const body = await answer(await s.run(request(s)), Number(status));
    expect(body.error).toMatchObject({ code, errorClass });
    expect(body.shape).toBeUndefined();
    expect(body.meetings).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("private-marker");
    dispatched();
  });
  it("refuses malformed decoded success and unknown private fields", async () => {
    success(s, { ...canonical(s.capability), owner_principal_id: "private-marker" });
    const body = await answer(await s.run(request(s)), 503);
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(JSON.stringify(body)).not.toContain("private-marker");
    dispatched();
  });
  it("rejects missing required or wrongly typed canonical success field", async () => {
    const result = canonical(s.capability), key = Object.keys(result)[0]!;
    const missing = { ...result }; delete missing[key];
    for (const invalidResult of [missing, { ...result, [key]: false }]) {
      fetchStub.mockClear(); success(s, invalidResult);
      expect((await answer(await s.run(request(s)), 503)).shape).toBeUndefined(); dispatched();
    }
  });
  it("refuses mixed upstream envelope", async () => {
    transport({ result: canonical(s.capability), disclosure: DISCLOSURE, error: { code: "conflict" } });
    const body = await answer(await s.run(request(s)), 503);
    expect(body.shape).toBeUndefined(); dispatched();
  });
  it("does not turn unreachable first-load or ambiguous write into success", async () => {
    fetchStub.mockRejectedValue(new TypeError("private-marker"));
    const body = await answer(await s.run(request(s)), 503);
    expect(body.shape).toBeUndefined(); expect(body.meetings).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("private-marker"); dispatched();
  });
});

describe("versioned and key-bearing mutation HTTP replay proofs (mock backend)", () => {
  for (const s of scenarios.filter((s) => s.body?.idempotencyKey)) {
    it(`${s.capability} preserves exact replay fields and response identities`, async () => {
      const replay = canonical(s.capability);
      if (s.capability === "capture.revise") replay.created = false;
      else replay.replayed = true;
      success(s, replay);
      const body = await answer(await s.run(request(s)), 200);
      expect(body[s.capability === "capture.revise" ? "created" : "replayed"]).toBe(s.capability !== "capture.revise");
      const payload = dispatched();
      expect(payload.idempotency_key).toBe(s.body!.idempotencyKey);
      if (s.body!.expectedVersion) expect(payload.expected_version).toBe(1);
      if (s.capability === "capture.revise") {
        expect(body.capture_id).toBe(replay.capture_id); expect(body.version_id).toBe(replay.version_id);
        expect(body.version_number).toBe(replay.version_number); expect(body.idempotency_key).toBeUndefined();
      }
    });
  }
});

describe("Project bounded authoring", () => {
  it.each(["continuity.projects.create", "continuity.projects.update", "continuity.projects.close"] as const)("%s enforces Project key grammar", async (cap) => {
    const s = scenario(cap);
    for (const key of ["", "short", "a".repeat(129), "with space", "☃".repeat(8)]) await invalid(s, { ...s.body, idempotencyKey: key });
  });
  it("rejects no material update and reopen/closed state requests", async () => {
    const s = scenario("continuity.projects.update");
    await invalid(s, keyed); await invalid(s, { ...keyed, name: null, description: null, state: null });
    for (const state of ["closed", "reopen", "unknown"]) await invalid(s, { ...s.body, state });
    await invalid(scenario("continuity.projects.close"), { ...keyed, reopen: true });
  });
  it.each(["continuity.projects.update", "continuity.projects.close", "meetings.update", "meetings.series.update"] as const)("%s rejects unsafe, fractional, Boolean and nonpositive versions", async (cap) => {
    const s = scenario(cap);
    for (const expectedVersion of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, true, "1", null]) await invalid(s, { ...s.body, expectedVersion });
  });
  it("retains existing Project GET fixed list and active-detail projections", async () => {
    const s = { ...scenario("continuity.projects.create"), method: "GET", body: undefined };
    success(s, canonical("continuity.projects"));
    expect((await projectList(request(s))).status).toBe(200);
    expect(dispatched()).toEqual({ page_size: 25 });
    fetchStub.mockClear(); success(s, canonical("continuity.projects.read"));
    const response = await projectRead(request(s), { params: Promise.resolve({ projectId }) });
    expect(response.status).toBe(200); expect((await response.json()).project.project_id).toBe(fixtures["continuity.projects.read"].project_id);
    expect(dispatched()).toEqual({ project_id: projectId });
  });
});

describe("Meeting exact filters, normalization and disclosure", () => {
  for (const cap of ["meetings.list", "meetings.search"] as const) {
    const s = scenario(cap);
    const prefix = cap === "meetings.search" ? "q=synthetic&" : "";
    it(`${cap} maps every filter and preserves partial result and cursor`, async () => {
      success(s, canonical(cap), { ...DISCLOSURE, partial_result: true, truncation: { is_truncated: true, next_cursor: meetingId } });
      const filters = new URLSearchParams({ meetingSeriesId, projectId, startAtFrom: "2026-08-09T12:00:00.000001Z", startAtBefore: "2026-08-09T12:00:00.000002Z", attendeeEntityId: `ent_${suffix}`, attendeeEmail: "synthetic@example.invalid", status: "scheduled", timeScope: "all", sortDirection: "asc", pageSize: "10", after: meetingId });
      const body = await answer(await s.run(request(s, undefined, prefix + filters)), 200);
      expect(body.meetings).toEqual(fixtures[cap].meetings);
      expect(body.disclosure).toMatchObject({ coverage: "partial", truncated: true, nextCursor: meetingId, freshnessAt: DISCLOSURE.freshness.observed_at, authority: "accepted" });
      expect(dispatched()).toMatchObject({ meeting_series_id: meetingSeriesId, project_id: projectId, attendee_entity_id: `ent_${suffix}`, attendee_email: "synthetic@example.invalid", page_size: 10, after: meetingId, status: "scheduled", time_scope: "all", sort_direction: "asc" });
    });
    it(`${cap} refuses each malformed/wrong-kind filter, unsafe page and enum before dispatch`, async () => {
      for (const [name, values] of Object.entries({ meetingSeriesId: [meetingId, "bad"], projectId: [meetingId, "bad"], attendeeEntityId: [projectId, "bad"], after: [projectId, "bad"], pageSize: ["0", "101", "1.5", "9007199254740992", "true", "null"], status: ["active", "null"], timeScope: ["future"], sortDirection: ["ascending"], attendeeEmail: ["bad", "two@@example.invalid"], startAtFrom: ["2026-02-30T12:00:00Z", "2026-01-01T12:00:00"] })) {
        for (const value of values) await invalid(s, undefined, prefix + new URLSearchParams({ [name]: value }));
      }
    });
    it(`${cap} rejects every repeated filter and submillisecond reversed/equal ranges`, async () => {
      for (const name of ["meetingSeriesId", "projectId", "startAtFrom", "startAtBefore", "attendeeEntityId", "attendeeEmail", "status", "timeScope", "sortDirection", "pageSize", "after"]) await invalid(s, undefined, `${prefix}${name}=a&${name}=b`);
      for (const before of ["2026-08-09T12:00:00.000001Z", "2026-08-09T12:00:00.000002Z"]) await invalid(s, undefined, prefix + new URLSearchParams({ startAtFrom: "2026-08-09T12:00:00.000002Z", startAtBefore: before }));
    });
  }
  it("search normalizes NFC and Python whitespace with headers/context retained, and admits raw padding beyond512", async () => {
    const s = scenario("meetings.search"); success(s);
    for (const [raw, expected] of [[" ".repeat(600) + "a", "a"], [" e\u0301\u0085one\u001c two ", "é one two"], ["😀".repeat(512), "😀".repeat(512)]]) {
      fetchStub.mockClear(); resolveSessionPrincipal.mockClear();
      await answer(await s.run(request(s, undefined, new URLSearchParams({ q: raw }).toString())), 200);
      expect(dispatched().query).toBe(expected);
      const rewritten = resolveSessionPrincipal.mock.calls[0]![1] as NextRequest;
      expect(rewritten.headers.get("x-test-context")).toBe("preserved");
      expect(rewritten.headers.get("origin")).toBe("http://localhost:3000");
    }
  });
  it("search rejects missing/empty/too-long q, query alias, duplicate and unknown before rewrite", async () => {
    const s = scenario("meetings.search");
    for (const query of ["", "q=", "q=+", "query=synthetic", "q=a&q=b", "q=a&query=b", new URLSearchParams({ q: "a".repeat(513) }).toString(), "q=a&unknown=b"]) await invalid(s, undefined, query);
    expect(resolveSessionPrincipal).not.toHaveBeenCalled();
  });
});

describe("Meeting aggregate command admission", () => {
  const s = scenario("meetings.update");
  it.each(["meetings.update", "meetings.series.update"] as const)("%s key bound counts codepoints and rejects empty/overlong keys", async (cap) => {
    const route = scenario(cap); success(route);
    await answer(await route.run(request(route, { ...route.body, idempotencyKey: "😀".repeat(128) })), 200);
    expect(dispatched().idempotency_key).toBe("😀".repeat(128)); fetchStub.mockClear();
    await invalid(route, { ...route.body, idempotencyKey: "" }); await invalid(route, { ...route.body, idempotencyKey: "😀".repeat(129) });
  });
  it("null scalars mean unchanged and [] attendees is a material replace, not a clear", async () => {
    success(s);
    const nulls = { title: null, startAt: null, endAt: null, timezoneName: null, status: null, locationText: null, virtualMeetingUrl: null, description: null, projectId: null, notesMode: null, notesMarkdown: null };
    await answer(await s.run(request(s, { ...keyed, ...nulls, attendeesReplace: [] })), 200);
    expect(dispatched()).toMatchObject({ attendees_replace: [], title: null, project_id: null });
    fetchStub.mockClear(); await invalid(s, { ...keyed, ...nulls, attendeesReplace: null });
    await invalid(s, { ...keyed, attachmentAddDocumentIds: [], attachmentRemoveIds: [] });
  });
  it("accepts supported clear-wins pairs, forbids project set+clear and requires notes pairing", async () => {
    success(s);
    await answer(await s.run(request(s, { ...keyed, endAt: "2026-08-09T13:00:00Z", locationText: "Room", virtualMeetingUrl: "https://example.invalid/meeting", description: "Note", clearFields: ["endAt", "locationText", "virtualMeetingUrl", "description"] })), 200);
    expect(dispatched().clear_fields).toEqual(["end_at", "location_text", "virtual_meeting_url", "description"]);
    fetchStub.mockClear();
    for (const patch of [{ projectId, clearFields: ["projectId"] }, { notesMode: "append" }, { notesMarkdown: "Note" }, { notesMode: "other", notesMarkdown: "Note" }, { clearFields: ["title"] }, { clearFields: ["endAt", "endAt"] }, { clearFields: null }]) await invalid(s, { ...keyed, ...patch });
    await answer(await s.run(request(s, { ...keyed, notesMode: "replace", notesMarkdown: "Note" })), 200);
    expect(dispatched()).toMatchObject({ notes_mode: "replace", notes_markdown: "Note" });
  });
  it("rejects timestamp, scalar type, enum, URL, ID and bound violations", async () => {
    for (const patch of [{ startAt: "2026-02-30T12:00:00Z" }, { endAt: "2026-01-01T12:00:00" }, { startAt: "2026-08-09T12:00:00.000002Z", endAt: "2026-08-09T12:00:00.000001Z" }, { status: "active" }, { title: 1 }, { title: " " }, { title: "x".repeat(201) }, { locationText: "x".repeat(501) }, { description: "x".repeat(100001) }, { virtualMeetingUrl: "http://example.invalid" }, { projectId: meetingId }, { timezoneName: "../UTC" }, { timezoneName: "/UTC" }, { timezoneName: " UTC" }]) await invalid(s, { ...s.body, ...patch });
  });
  it("series selector forwards an id or explicit null and never sends an omitted key", async () => {
    success(s);
    await answer(await s.run(request(s)), 200);
    expect(dispatched()).not.toHaveProperty("meeting_series_id");
    fetchStub.mockClear(); await answer(await s.run(request(s, { ...s.body, meetingSeriesId })), 200);
    expect(dispatched()).toMatchObject({ meeting_series_id: meetingSeriesId, title: "Synthetic occurrence" });
    // Alone, a series id or a detach is the one material mutation the request needs.
    fetchStub.mockClear(); await answer(await s.run(request(s, { ...keyed, meetingSeriesId })), 200);
    expect(dispatched()).toEqual({ meeting_id: meetingId, expected_version: 1, idempotency_key: "wp03b-key-1", meeting_series_id: meetingSeriesId });
    fetchStub.mockClear(); await answer(await s.run(request(s, { ...keyed, meetingSeriesId: null })), 200);
    const detach = dispatched();
    expect(detach).toEqual({ meeting_id: meetingId, expected_version: 1, idempotency_key: "wp03b-key-1", meeting_series_id: null });
    expect(Object.hasOwn(detach, "meeting_series_id")).toBe(true);
    fetchStub.mockClear();
    for (const meetingSeriesId of [meetingId, "mser_short", `mser_${suffix}!`, ` mser_${suffix}`, `mser_${"a".repeat(65)}`, "", 1, false, [`mser_${suffix}`], {}]) await invalid(s, { ...s.body, meetingSeriesId });
    await invalid(s, { ...s.body, meeting_series_id: `mser_${suffix}` });
    await invalid(s, { ...s.body, seriesTitle: "Synthetic series" });
  });
  it("passes Factory, posix/UTC and UTC and preserves backend semantic invalid-zone400", async () => {
    success(s);
    for (const timezoneName of ["Factory", "posix/UTC", "UTC"]) {
      fetchStub.mockClear(); await answer(await s.run(request(s, { ...s.body, timezoneName })), 200);
      expect(dispatched().timezone_name).toBe(timezoneName);
    }
    fetchStub.mockClear(); transport({ error: { code: "invalid_request", message: "timezone_name", safe_details: { exception: "private-marker" } } }, 400);
    const body = await answer(await s.run(request(s, { ...s.body, timezoneName: "NoSuch/Zone" })), 400);
    expect(dispatched().timezone_name).toBe("NoSuch/Zone"); expect(JSON.stringify(body)).not.toContain("private-marker");
  });
  it("closed attendees reject wrong nested keys/types, duplicate normalized emails/entities and organizers", async () => {
    const entityId = `ent_${suffix}`;
    const invalidAttendees = [
      [{}], [{ displayName: "A", unknown: true }], [{ displayName: "A", principalId: "browser" }], [{ entityId: projectId }],
      [{ displayName: "A", isOrganizer: "true" }], [{ displayName: "A", isOrganizer: null }], [{ displayName: "A", responseStatus: "active" }],
      [{ displayName: "A", email: "bad" }], [{ displayName: "x".repeat(201) }],
      [{ email: " A@example.invalid " }, { email: "a@EXAMPLE.invalid" }],
      [{ email: "straße@example.invalid" }, { email: "STRASSE@example.invalid" }],
      [{ entityId }, { entityId }], [{ displayName: "A" }, { displayName: "A" }],
      [{ displayName: "A", isOrganizer: true }, { displayName: "B", isOrganizer: true }],
      Array.from({ length: 101 }, (_, n) => ({ displayName: `A${n}` })),
    ];
    for (const attendeesReplace of invalidAttendees) await invalid(s, { ...s.body, attendeesReplace });
    success(s); await answer(await s.run(request(s, { ...keyed, attendeesReplace: [{ displayName: "Synthetic", email: " A@EXAMPLE.invalid ", isOrganizer: true, responseStatus: "accepted" }] })), 200);
    // Validation uses canonical normalization; transport preserves authored fields
    // and omission for the backend command's normalization rather than coercing.
    expect(dispatched().attendees_replace).toEqual([{ display_name: "Synthetic", email: " A@EXAMPLE.invalid ", is_organizer: true, response_status: "accepted" }]);
  });
  it("attachment collections enforce unique distinct ID kinds, max50 and null rejection", async () => {
    for (const [field, prefix, wrong] of [["attachmentAddDocumentIds", "mdoc", "matc"], ["attachmentRemoveIds", "matc", "mdoc"]]) {
      for (const value of [null, [`${wrong}_${suffix}`], [`${prefix}_${suffix}`, `${prefix}_${suffix}`], Array.from({ length: 51 }, (_, n) => `${prefix}_${String(n).padStart(8, "0")}`)]) await invalid(s, { ...s.body, [field!]: value });
      success(s); await answer(await s.run(request(s, { ...keyed, [field!]: Array.from({ length: 50 }, (_, n) => `${prefix}_${String(n).padStart(8, "0")}`) })), 200);
      dispatched(); fetchStub.mockClear();
    }
  });
  it("series retitle dispatches only its series command, never occurrence-title rewrites", async () => {
    const route = scenario("meetings.series.update"); success(route);
    await answer(await route.run(request(route)), 200);
    expect(dispatched()).toEqual({ meeting_series_id: meetingSeriesId, expected_version: 1, idempotency_key: "wp03b-key-1", title: "Synthetic series" });
  });
  it.each(["meetings.update", "meetings.series.update"] as const)("%s accepts canonical no_op history without inventing version progress", async (cap) => {
    const route = scenario(cap), result = canonical(cap);
    const history = result.history as Record<string, unknown>;
    history.outcome = "no_op"; history.before_version = 2; history.after_version = 2;
    success(route, result);
    const body = await answer(await route.run(request(route)), 200);
    expect(body.history).toMatchObject({ outcome: "no_op", before_version: 2, after_version: 2 }); dispatched();
  });
});

describe("Document byte and target-state boundaries", () => {
  const s = scenario("documents.read");
  it("maps specific version and explicit byte Boolean, with omission remaining absent", async () => {
    success(s);
    await answer(await s.run(request(s, undefined, `versionId=mdver_${suffix}&includeBytes=true`)), 200);
    expect(dispatched()).toEqual({ document_id: documentId, version_id: `mdver_${suffix}`, include_bytes: true });
    fetchStub.mockClear(); await answer(await s.run(request(s)), 200);
    expect(dispatched()).toEqual({ document_id: documentId });
  });
  it("bytes require includeBytes true; malformed bytes and private upstream fields fail closed", async () => {
    const result = canonical(s.capability);
    const version = result.version as Record<string, unknown>;
    version.content_base64 = "c3ludGhldGlj";
    success(s, result);
    const body = await answer(await s.run(request(s, undefined, "includeBytes=true")), 200);
    expect(body.version.content_base64).toBe("c3ludGhldGlj"); dispatched();
    for (const query of ["", "includeBytes=false"]) {
      fetchStub.mockClear(); await answer(await s.run(request(s, undefined, query)), 503); dispatched();
    }
    fetchStub.mockClear(); version.content_base64 = "bad%%"; success(s, result);
    const refused = await answer(await s.run(request(s, undefined, "includeBytes=true")), 503);
    expect(JSON.stringify(refused)).not.toContain("bad%%"); dispatched();
  });
  it("rejects Boolean encodings/nulls and wrong-kind/version duplicate queries", async () => {
    for (const query of ["includeBytes=True", "includeBytes=1", "includeBytes=null", "versionId=null", `versionId=${documentId}`, `versionId=mdver_${suffix}&versionId=mdver_${suffix}`]) await invalid(s, undefined, query);
  });
  it("foreign, absent and wrong-document version return the same nondisclosing404", async () => {
    const bodies = [];
    for (const query of ["", `versionId=mdver_${suffix}`, "versionId=mdver_bbbbbbbb22222222"]) {
      fetchStub.mockClear(); transport({ error: { code: "not_found", message: "document_id" } }, 404);
      bodies.push(await answer(await s.run(request(s, undefined, query)), 404)); dispatched();
    }
    expect(bodies[0]).toEqual(bodies[1]); expect(bodies[1]).toEqual(bodies[2]);
  });
  for (const cap of ["documents.archive", "documents.restore"] as const) it(`${cap} accepts empty body/json{}, changed=false, rejects key/version/null/query`, async () => {
    const route = scenario(cap); success(route, { ...canonical(cap), changed: false });
    for (const body of [undefined, {}]) {
      fetchStub.mockClear();
      const empty = body === undefined ? new NextRequest(new URL(route.path, "http://localhost:3000"), { method: "POST", headers: { origin: "http://localhost:3000" } }) : request(route, body);
      expect((await answer(await route.run(empty), 200)).changed).toBe(false);
      expect(dispatched()).toEqual({ document_id: documentId });
    }
    fetchStub.mockClear();
    for (const body of [{ idempotencyKey: "key" }, { expectedVersion: 1 }, null]) await invalid(route, body);
    await invalid(route, {}, "includeBytes=true");
  });
});

describe("Capture revise admission and archived replay forwarding (mock backend, RC001–007)", () => {
  const s = scenario("capture.revise");
  it("accepts arbitrary nonempty Unicode keys of 1–128 codepoints and nullable timestamps", async () => {
    success(s);
    for (const key of [" ", "☃", "😀".repeat(128)]) {
      fetchStub.mockClear();
      await answer(await s.run(request(s, { ...s.body, idempotencyKey: key, clientCreatedAt: null, occurredAt: null })), 200);
      expect(dispatched()).toMatchObject({ idempotency_key: key, client_created_at: null, occurred_at: null });
    }
  });
  it("rejects empty/long keys, blank/long text, CAS and processing/lifecycle metadata", async () => {
    for (const patch of [{ idempotencyKey: "" }, { idempotencyKey: "😀".repeat(129) }, { text: "   " }, { text: "x".repeat(100001) }, { expectedVersion: 1 }, { processingState: "queued" }, { closeMetadata: {} }]) await invalid(s, { ...s.body, ...patch });
  });
  it("is online-only with no direct queue/storage/cache/lifecycle admission dependency (RC006)", () => {
    const route = readFileSync("src/app/api/capture/[captureId]/route.ts", "utf8");
    expect(route).not.toMatch(/@\/lib\/(offline|capture\/idempotency)|indexedDB|localStorage|captureAdmissions|\badmit\s*:/);
    // Runtime cases above also prove exactly one revise dispatch, no preflight read.
  });
  it.each(["2026-02-30T12:00:00Z", "2026-01-01T25:00:00Z", "2026-01-01T12:00:00", "bad"])("rejects malformed calendar/naive timestamp %s", async (value) => {
    await invalid(s, { ...s.body, occurredAt: value }); await invalid(s, { ...s.body, clientCreatedAt: value });
  });
  it("new archived intent stays denied, changed bound intent stays conflict, foreign/absent stay 404 without preflight", async () => {
    for (const [code, status] of [["denied", 403], ["conflict", 409], ["not_found", 404], ["not_found", 404]] as const) {
      fetchStub.mockClear();
      transport({ error: { code, message: "capture_id", safe_details: { lifecycle_state: "private-marker", request_digest: "private-marker" } } }, status);
      const body = await answer(await s.run(request(s)), status);
      expect(body.shape).toBeUndefined(); expect(body.created).toBeUndefined();
      expect(JSON.stringify(body)).not.toContain("private-marker");
      expect(dispatched()).toEqual({ capture_id: captureId, text: "Synthetic revision", idempotency_key: "wp03b-revise-1" });
    }
  });
  it("exact archived replay retains original receipt/version and restored ACTIVE success remains ordinary", async () => {
    const original = canonical(s.capability);
    success(s, { ...original, created: false });
    const replay = await answer(await s.run(request(s)), 200);
    expect(replay).toMatchObject({ receipt_id: original.receipt_id, capture_id: original.capture_id, version_id: original.version_id, version_number: original.version_number, created: false });
    expect(replay.idempotency_key).toBeUndefined(); dispatched();
    fetchStub.mockClear(); success(s);
    expect((await answer(await s.run(request(s)), 200)).created).toBe(true); dispatched();
  });
});
