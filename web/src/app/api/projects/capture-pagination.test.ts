// @vitest-environment node
/**
 * T23 — the bounded Project selector pagination contract (C04).
 *
 * The Capture Project selector needs enough of the authorized Project list to
 * offer a choice, and nothing more. That means one fixed page size, one opaque
 * cursor forwarded unchanged, and a page that never claims to be the whole list
 * when the canonical disclosure says it was truncated.
 */
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
  syntheticProjects,
  syntheticDisclosure,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  ),
  syntheticProjects: vi.fn(() => []),
  syntheticDisclosure: vi.fn(() => ({ coverage: "synthetic" })),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));
vi.mock("@/lib/fixtures/situation", () => ({ syntheticProjects }));
vi.mock("@/lib/fixtures/pulse", () => ({ syntheticDisclosure }));

import { GET } from "./route";

const PRINCIPAL = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "synthetic:aaaa0001",
  tid: "tenant",
  oid: "object",
  upn: "operator@example.invalid",
  displayName: "Operator",
  lifecycleState: "active",
  synthetic: true,
} satisfies PrincipalSession;

const CURSOR = "eyJhZnRlciI6InByal9hYWFhYWFhYTExMTExMTExIn0";

function row(index: number) {
  const suffix = String(index).padStart(8, "0");
  return {
    project_id: `prj_aaaaaaaa${suffix}`,
    name: `Project ${index}`,
    state: "active" as const,
    description: null,
    participants: [],
    canonical_participations: [],
    opened_at: "2026-01-01T00:00:00Z",
    closed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    version: index + 1,
  };
}

function disclosure(truncation: Record<string, unknown>) {
  return { truncation };
}

function read(query = "") {
  return GET(new NextRequest(`http://localhost:3000/api/projects${query}`));
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  syntheticProjects.mockReturnValue([]);
  syntheticDisclosure.mockReturnValue({ coverage: "synthetic" });
  gatewayRefusal.mockImplementation((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  );
});

describe("the fixed page size", () => {
  it("asks the canonical list for exactly 25 rows and no cursor on a first page", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0), row(1)] },
      disclosure: disclosure({ is_truncated: false }),
    });

    const response = await read();

    expect(response.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "continuity.projects", {
      page_size: 25,
      after: undefined,
    });
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principal_id");
  });

  it("does not accept a caller-chosen page size", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [] },
      disclosure: disclosure({ is_truncated: false }),
    });
    await read("?page_size=500&pageSize=500&limit=500");
    expect(invokeGateway.mock.calls[0]![2]!["page_size"]).toBe(25);
  });
});

describe("the single opaque cursor", () => {
  it("forwards a nonempty after unchanged", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(25)] },
      disclosure: disclosure({ is_truncated: false }),
    });

    await read(`?after=${encodeURIComponent(CURSOR)}`);

    expect(invokeGateway.mock.calls[0]![2]).toEqual({ page_size: 25, after: CURSOR });
  });

  it("refuses a repeated after before invoking the gateway", async () => {
    const response = await read(`?after=${CURSOR}&after=${CURSOR}`);
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("invalid_cursor");
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("refuses an empty supplied cursor before invoking the gateway", async () => {
    const response = await read("?after=");
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("invalid_cursor");
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("does not mint, decode or rewrite a cursor of its own", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [] },
      disclosure: disclosure({ is_truncated: true, next_cursor: "OPAQUE::NEXT" }),
    });
    const body = await (await read(`?after=${encodeURIComponent(CURSOR)}`)).json();
    expect(body.nextCursor).toBe("OPAQUE::NEXT");
    expect(invokeGateway.mock.calls[0]![2]!["after"]).toBe(CURSOR);
  });
});

describe("version and nextCursor come from canonical truth", () => {
  it("carries each canonical row's version and preserves the existing field names", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0), row(1)] },
      disclosure: disclosure({ is_truncated: false }),
    });

    const body = await (await read()).json();

    expect(body.projects).toEqual([
      {
        projectId: "prj_aaaaaaaa00000000",
        name: "Project 0",
        state: "active",
        description: null,
        participants: [],
        openedAt: "2026-01-01T00:00:00Z",
        closedAt: null,
        version: 1,
      },
      {
        projectId: "prj_aaaaaaaa00000001",
        name: "Project 1",
        state: "active",
        description: null,
        participants: [],
        openedAt: "2026-01-01T00:00:00Z",
        closedAt: null,
        version: 2,
      },
    ]);
    expect(body.shape).toBe("backend");
  });

  it("takes nextCursor from the disclosure truncation and nowhere else", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0)] },
      disclosure: disclosure({ is_truncated: true, next_cursor: CURSOR }),
    });
    expect((await (await read()).json()).nextCursor).toBe(CURSOR);
  });

  it("reports a complete page as having no next cursor", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0)] },
      disclosure: disclosure({ is_truncated: false }),
    });
    expect((await (await read()).json()).nextCursor).toBeNull();
  });
});

describe("a malformed pagination disclosure fails closed", () => {
  it("refuses a truncated page with no cursor rather than calling it complete", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0)] },
      disclosure: disclosure({ is_truncated: true }),
    });

    const response = await read();

    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(body.projects).toBeUndefined();
  });

  it("refuses a truncated page whose cursor is empty", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0)] },
      disclosure: disclosure({ is_truncated: true, next_cursor: "" }),
    });
    expect((await read()).status).toBe(503);
  });
});

describe("authority and the existing exact read are untouched", () => {
  it("refuses an unauthenticated caller before any gateway call", async () => {
    requirePrincipal.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ error: { code: "unauthenticated" } }, { status: 401 }),
    });
    const response = await read(`?after=${CURSOR}`);
    expect(response.status).toBe(401);
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("makes exactly one canonical call and never fans out over pages", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [row(0)] },
      disclosure: disclosure({ is_truncated: true, next_cursor: CURSOR }),
    });
    await read();
    expect(invokeGateway).toHaveBeenCalledTimes(1);
  });

  it("passes a canonical refusal through unchanged", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: { errorClass: "unavailable", code: "gateway_unreachable", message: "no" },
    });
    const response = await read();
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("gateway_unreachable");
  });

  it("keeps the synthetic projection explicitly synthetic and uncursored", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    syntheticProjects.mockReturnValue([]);
    const body = await (await read()).json();
    expect(body.shape).toBe("synthetic");
    expect(body.nextCursor).toBeNull();
    expect(invokeGateway).not.toHaveBeenCalled();
  });
});
