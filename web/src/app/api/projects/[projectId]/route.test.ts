// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";

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
vi.mock("@/lib/api/gateway", () => ({
  invokeGateway,
  backendDisclosure,
  transportLimitations,
}));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));

import { GET } from "./route";

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

const PROJECT_ID = "prj_aaaaaaaa11111111";
const PROJECT = {
  project_id: PROJECT_ID,
  name: "North slab",
  state: "active",
  description: null,
  participants: [],
  canonical_participations: [],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 2,
} as const;

function request(projectId: string, query = ""): NextRequest {
  return new NextRequest(`http://localhost:3000/api/projects/${projectId}${query}`);
}

async function read(projectId: string, query = "") {
  return GET(request(projectId, query), { params: Promise.resolve({ projectId }) });
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
});

describe("GET /api/projects/[projectId]", () => {
  it("requires the authenticated server Principal and sends no caller Principal", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: PROJECT, disclosure: {} });
    const response = await read(PROJECT_ID, "?principal_id=prn_ffffffffffffffffffffffffffffffff");
    expect(response.status).toBe(200);
    expect(requirePrincipal).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "continuity.projects.read", {
      project_id: PROJECT_ID,
    });
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principal_id");
    expect((await response.json()).project).toEqual(PROJECT);
  });

  it("returns 400 for malformed identity without consulting serving or the gateway", async () => {
    const response = await read("prj_short");
    expect(response.status).toBe(400);
    expect(resolveServing).not.toHaveBeenCalled();
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it.each([
    ["missing", 404, "not_found"],
    ["foreign", 403, "authorization"],
  ])("makes %s Projects the same generic 404", async (_label, status, errorClass) => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status,
      error: { errorClass, code: "redacted", message: "sensitive upstream detail" },
    });
    const response = await read(PROJECT_ID);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: {
        errorClass: "not_found",
        code: "not_found",
        message: "the Project could not be read",
      },
    });
  });

  it("makes a closed Project indistinguishable from the generic not-found answer", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { ...PROJECT, state: "closed", closed_at: "2026-01-04T00:00:00Z" },
      disclosure: {},
    });
    const response = await read(PROJECT_ID);
    expect(response.status).toBe(404);
    expect((await response.json()).error.code).toBe("not_found");
  });

  it("returns 503 for transient or decoder-invalid upstream outcomes", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: {
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
        message: "the gateway result did not match the capability contract",
      },
    });
    const response = await read(PROJECT_ID);
    expect(response.status).toBe(503);
    expect(gatewayRefusal).toHaveBeenCalledOnce();
  });

  it("does not cross from explicitly synthetic serving into the canonical gateway", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    const response = await read(PROJECT_ID);
    expect(response.status).toBe(404);
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("returns the authentication guard response unchanged", async () => {
    requirePrincipal.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ error: { code: "authentication_required" } }, { status: 401 }),
    });
    const response = await read(PROJECT_ID);
    expect(response.status).toBe(401);
    expect(invokeGateway).not.toHaveBeenCalled();
  });
});
