// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";

/*
 * AT-024 (S3, routes): the Issue BFF routes (S3 contract section 7.6). One
 * gateway call per view and per page, strict queries, the S1 identifier
 * patterns, the cursor pattern, and the projection guard (an answer about
 * another Issue or origin is `upstream_contract_invalid`).
 */
const {
  requirePrincipal, invokeGateway, resolveServing, backendDisclosure, transportLimitations, gatewayRefusal,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope, status, error) => Response.json({ state: "unavailable", error }, { status })),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));

import { GET as listIssues } from "./route";
import { GET as readIssue } from "./[issueId]/route";
import { GET as readTimeline } from "./[issueId]/timeline/route";
import { GET as readLineage } from "./[issueId]/lineage/route";

const PRINCIPAL = {
  principalId: "aaaaaaaa-1111-1111-1111-111111111111",
  identityProvider: "synthetic",
  identitySubject: "synthetic:aaaaaaaa",
  tid: "tenant",
  oid: "object",
  upn: "operator@example.invalid",
  displayName: "Operator",
  lifecycleState: "active",
  synthetic: true,
} satisfies PrincipalSession;

const ISSUE_ID = "sit_aaaaaaaa11111111";
const CURSOR = "eyJ2IjoxfQ";
type Json = Record<string, unknown>;

function request(path: string): NextRequest {
  return new NextRequest(`http://localhost:3000${path}`);
}
function params(issueId = ISSUE_ID) {
  return { params: Promise.resolve({ issueId }) };
}
function issueLineage(): Json {
  const lineage = structuredClone(fixtures["records.lineage"]) as Json;
  // The Issue as origin: its root is the Issue itself.
  lineage.root = { family: "situation", record_id: ISSUE_ID };
  return lineage;
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  gatewayRefusal.mockImplementation((_scope, status, error) => Response.json({ state: "unavailable", error }, { status }));
});

describe("the Issue BFF routes", () => {
  it("calls issues.timeline once per page with only the cursor and page size", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: fixtures["issues.timeline"], disclosure: {} });
    const first = await readTimeline(request(`/api/issues/${ISSUE_ID}/timeline?pageSize=25`), params());
    expect(first.status).toBe(200);
    expect(first.headers.get("cache-control")).toContain("no-store");
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "issues.timeline", { issue_id: ISSUE_ID, page_size: 25 });
    const body = await first.json();
    expect(body.shape).toBe("backend");
    expect(body.next_cursor).toBe(fixtures["issues.timeline"].next_cursor);

    invokeGateway.mockClear();
    const next = await readTimeline(request(`/api/issues/${ISSUE_ID}/timeline?pageSize=25&cursor=${CURSOR}`), params());
    expect(next.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "issues.timeline", { issue_id: ISSUE_ID, page_size: 25, cursor: CURSOR });

    // An as-of first page states its knowledge time; nothing else is admitted.
    invokeGateway.mockClear();
    const asOf = await readTimeline(request(`/api/issues/${ISSUE_ID}/timeline?pageSize=10&knownAt=2026-08-09T12:00:00Z`), params());
    expect(asOf.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "issues.timeline", {
      issue_id: ISSUE_ID, page_size: 10, known_at: "2026-08-09T12:00:00Z",
    });

    // A page about another Issue is not an answer to this request.
    invokeGateway.mockClear();
    const foreign = await readTimeline(request(`/api/issues/sit_bbbbbbbb22222222/timeline?pageSize=25`), params("sit_bbbbbbbb22222222"));
    expect(foreign.status).toBe(503);
    expect(invokeGateway).toHaveBeenCalledOnce();
  });

  it("calls records.lineage once with the Issue as origin", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: issueLineage(), disclosure: {} });
    const first = await readLineage(request(`/api/issues/${ISSUE_ID}/lineage?pageSize=25`), params());
    expect(first.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "records.lineage", {
      origin: { family: "situation", record_id: ISSUE_ID }, issue_id: ISSUE_ID, page_size: 25,
    });
    invokeGateway.mockClear();
    const next = await readLineage(request(`/api/issues/${ISSUE_ID}/lineage?pageSize=25&cursor=${CURSOR}`), params());
    expect(next.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "records.lineage", {
      origin: { family: "situation", record_id: ISSUE_ID }, issue_id: ISSUE_ID, page_size: 25, cursor: CURSOR,
    });
    // An answer rooted elsewhere (the Task fixture) is refused.
    invokeGateway.mockClear();
    invokeGateway.mockResolvedValue({ ok: true, result: fixtures["records.lineage"], disclosure: {} });
    const elsewhere = await readLineage(request(`/api/issues/${ISSUE_ID}/lineage?pageSize=25`), params());
    expect(elsewhere.status).toBe(503);

    // The header and the index: one call each.
    invokeGateway.mockReset();
    invokeGateway.mockResolvedValue({ ok: true, result: fixtures["issues.read"], disclosure: {} });
    const header = await readIssue(request(`/api/issues/${ISSUE_ID}`), params());
    expect(header.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "issues.read", { issue_id: ISSUE_ID });
    invokeGateway.mockReset();
    invokeGateway.mockResolvedValue({ ok: true, result: fixtures["issues.list"], disclosure: {} });
    const index = await listIssues(request(`/api/issues?state=open&after=${ISSUE_ID}`));
    expect(index.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "issues.list", { state: "open", after: ISSUE_ID });
  });

  it("refuses unknown query fields and malformed cursors without a gateway call", async () => {
    for (const query of [
      "?pageSize=25&cursor=not%20base64url",
      `?pageSize=25&cursor=${"x".repeat(2049)}`,
      `?cursor=${CURSOR}`,
      "?pageSize=9",
      "?pageSize=101",
      "?pageSize=25&validAt=2026-08-09T12:00:00Z",
      "?pageSize=25&issueId=sit_bbbbbbbb22222222",
      "?pageSize=25&knownAt=yesterday",
      "?pageSize=25&pageSize=50",
      "?page_size=25",
      "?pageSize=25&principal_id=prn_ffffffffffffffffffffffffffffffff",
    ]) {
      for (const [name, route, suffix] of [["timeline", readTimeline, "timeline"], ["lineage", readLineage, "lineage"]] as const) {
        const response = await route(request(`/api/issues/${ISSUE_ID}/${suffix}${query}`), params());
        expect(response.status, `${name} ${query}`).toBe(400);
        const { error } = await response.json();
        expect(error).toMatchObject({ errorClass: "validation", code: "invalid_request" });
      }
    }
    for (const issueId of ["sit_short", "tsk_aaaaaaaa11111111", "SIT_aaaaaaaa11111111"]) {
      expect((await readIssue(request(`/api/issues/${issueId}`), params(issueId))).status, issueId).toBe(400);
      expect((await readTimeline(request(`/api/issues/${issueId}/timeline`), params(issueId))).status, issueId).toBe(400);
      expect((await readLineage(request(`/api/issues/${issueId}/lineage`), params(issueId))).status, issueId).toBe(400);
    }
    expect((await readIssue(request(`/api/issues/${ISSUE_ID}?includeMembers=true`), params())).status).toBe(400);
    for (const query of ["?state=contested", "?after=prj_aaaaaaaa11111111", "?pageSize=0", "?projectId=prj_aaaaaaaa11111111", "?cursor=x"]) {
      expect((await listIssues(request(`/api/issues${query}`))).status, query).toBe(400);
    }
    expect(invokeGateway).not.toHaveBeenCalled();
  });
});
