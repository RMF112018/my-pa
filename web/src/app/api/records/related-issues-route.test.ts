// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";

const {
  requirePrincipal,
  invokeGateway,
  resolveServing,
  backendDisclosure,
  transportLimitations,
  gatewayRefusal,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope, status, error) =>
    Response.json({ state: "unavailable", error }, { status }),
  ),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));

import { GET } from "./[family]/[recordId]/related-issues/route";

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

const TASK_ID = "tsk_aaaaaaaa11111111";
const LINEAGE = fixtures["records.lineage"];

async function read(family: string, recordId: string, query = "") {
  const request = new NextRequest(`http://localhost:3000/api/records/${family}/${recordId}/related-issues${query}`);
  return GET(request, { params: Promise.resolve({ family, recordId }) });
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  gatewayRefusal.mockImplementation((_scope, status, error) => Response.json({ state: "unavailable", error }, { status }));
});

describe("GET /api/records/[family]/[recordId]/related-issues", () => {
  it("calls records.lineage once with origin and max_depth 1", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: LINEAGE, disclosure: {} });
    const response = await read("task", TASK_ID);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "records.lineage", {
      origin: { family: "task", record_id: TASK_ID },
      max_depth: 1,
    });
    const body = await response.json();
    expect(body.shape).toBe("backend");
    expect(body.selected_issue_id).toBe(LINEAGE.selected_issue_id);
    expect(body.typed_edges).toEqual(LINEAGE.typed_edges);

    invokeGateway.mockClear();
    const chosen = await read("commitment", "cmt_aaaaaaaa11111111", "?issueId=sit_bbbbbbbb22222222");
    // The answer names another root, so it is not an answer to this request.
    expect(chosen.status).toBe(503);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "records.lineage", {
      issue_id: "sit_bbbbbbbb22222222",
      origin: { family: "commitment", record_id: "cmt_aaaaaaaa11111111" },
      max_depth: 1,
    });
  });

  it("refuses a family outside task, commitment and constraint without a gateway call", async () => {
    // S3 lockstep (S3 contract section 7.6): the Meeting view now carries the
    // panel, so `meeting` is admitted (proved by the test below) and left this list.
    for (const [family, recordId, field] of [
      ["meeting", "cmt_aaaaaaaa11111111", "recordId"],
      ["meeting_note_version", "mnote_aaaaaaaa11111111", "family"],
      ["situation", "sit_aaaaaaaa11111111", "family"],
      ["capture_version", "capver_aaaaaaaa11111111", "family"],
      ["constructor", TASK_ID, "family"],
      ["Task", TASK_ID, "family"],
      ["task", "cmt_aaaaaaaa11111111", "recordId"],
      ["constraint", "tsk_short", "recordId"],
    ] as const) {
      const response = await read(family, recordId);
      expect(response.status, family).toBe(400);
      const { error } = await response.json();
      expect(error).toMatchObject({ errorClass: "validation", code: "invalid_request" });
      // The family allow-list answers before, and apart from, the identifier check.
      expect(error.message, family).toMatch(new RegExp(`^${field} `));
    }
    expect(requirePrincipal).not.toHaveBeenCalled();
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("admits the Meeting view's family with its own prefix (S3 section 7.6)", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: { ...LINEAGE, root: { family: "meeting", record_id: "mtg_aaaaaaaa11111111" } }, disclosure: {} });
    const response = await read("meeting", "mtg_aaaaaaaa11111111");
    expect(response.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "records.lineage", {
      origin: { family: "meeting", record_id: "mtg_aaaaaaaa11111111" },
      max_depth: 1,
    });
  });

  it("refuses unknown query fields", async () => {
    for (const query of [
      "?maxDepth=4",
      "?max_depth=4",
      "?origin=cmt_aaaaaaaa11111111",
      "?issueId=sit_aaaaaaaa11111111&issueId=sit_bbbbbbbb22222222",
      "?issueId=prj_aaaaaaaa11111111",
      "?cursor=x",
      "?principal_id=prn_ffffffffffffffffffffffffffffffff",
    ]) {
      const response = await read("constraint", "cst_aaaaaaaa11111111", query);
      expect(response.status, query).toBe(400);
    }
    expect(invokeGateway).not.toHaveBeenCalled();
  });
});
