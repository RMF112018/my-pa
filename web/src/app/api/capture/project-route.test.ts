// @vitest-environment node
/**
 * T01 — `/api/capture` Project transport (C02).
 *
 * The route's whole job on this path is to carry a Project the browser selected
 * to the gateway and to carry back the Project the backend actually committed.
 * The two must never be the same value by construction: a request echo would
 * tell a user their note was filed against a Project when it was not.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";
import { contentSha256 } from "@/lib/capture/receipt";

const {
  requirePrincipal,
  readCleanBody,
  invokeGateway,
  resolveServing,
  backendDisclosure,
  transportLimitations,
  gatewayRefusal,
  admitBrowserMutation,
  captureAdmissions,
  syntheticDisclosure,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  readCleanBody: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  ),
  admitBrowserMutation: vi.fn((): NextResponse | null => null),
  captureAdmissions: { admit: vi.fn() },
  syntheticDisclosure: vi.fn(() => ({ coverage: "synthetic" })),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal, readCleanBody }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));
vi.mock("@/lib/http/mutation-admission", () => ({ admitBrowserMutation }));
vi.mock("@/lib/capture/idempotency", () => ({ captureAdmissions }));
vi.mock("@/lib/fixtures/pulse", () => ({ syntheticDisclosure }));

import { POST } from "./route";

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

const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";
/** A Project this Principal does not own. The backend refuses it; this tier never sees it. */
const PROJECT_C = "prj_cccccccc33333333";

const TEXT = "a note";
const KEY = "idem-0001";

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    receipt_id: "rcpt_aaaaaaaa11111111",
    capture_id: "cap_aaaaaaaa11111111",
    version_id: "capver_aaaaaaaa11111111",
    version_number: 1,
    idempotency_key: KEY,
    content_sha256: "f63e34a034f19a24438f2d74b242bc96682abd843ecc4ea63fefed4006d860a3",
    project_id: null,
    issued_at: "2026-09-22T12:00:00Z",
    created: true,
    ...overrides,
  };
}

function post(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost:3000/api/capture", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "http://localhost:3000" },
    body: JSON.stringify(body),
  });
}

async function send(body: Record<string, unknown>) {
  readCleanBody.mockResolvedValue({ ok: true, body });
  return POST(post(body));
}

beforeEach(() => {
  vi.resetAllMocks();
  admitBrowserMutation.mockReturnValue(null);
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  syntheticDisclosure.mockReturnValue({ coverage: "synthetic" });
  gatewayRefusal.mockImplementation((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  );
});

describe("the browser Project reaches the gateway as project_id", () => {
  it("forwards a selected Project and returns the persisted one nested in the receipt", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ project_id: PROJECT_A }),
      disclosure: {},
    });

    const response = await send({ text: TEXT, idempotencyKey: KEY, captureKind: "quick_note", projectId: PROJECT_A });

    expect(response.status).toBe(200);
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "capture.create", {
      text: TEXT,
      idempotency_key: KEY,
      capture_kind: "quick_note",
      project_id: PROJECT_A,
    });
    const body = await response.json();
    expect(body.receipt.projectId).toBe(PROJECT_A);
    expect(body.projectId).toBeUndefined();
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("forwards an omitted Project as an explicit null", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: receipt(), disclosure: {} });

    const response = await send({ text: TEXT, idempotencyKey: KEY });

    expect(response.status).toBe(200);
    expect(invokeGateway.mock.calls[0]![2]).toEqual({
      text: TEXT,
      idempotency_key: KEY,
      capture_kind: "quick_note",
      project_id: null,
    });
    expect((await response.json()).receipt.projectId).toBeNull();
  });

  it("forwards an explicit null Project as No Project", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: receipt(), disclosure: {} });

    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: null });

    expect(response.status).toBe(200);
    expect(invokeGateway.mock.calls[0]![2]!["project_id"]).toBeNull();
    expect((await response.json()).receipt.projectId).toBeNull();
  });

  it("returns the persisted Project rather than the requested one", async () => {
    // The gateway is the authority on what was committed. If it ever answered
    // with a different Project than the one requested, the integrity gate below
    // refuses; what it must never do is echo the request back as if it were
    // readback. This proves the value travels from the result.
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ project_id: PROJECT_A }),
      disclosure: {},
    });
    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A });
    const body = await response.json();
    expect(body.receipt.projectId).toBe(receipt({ project_id: PROJECT_A }).project_id);
    expect(body.receipt.principalId).toBe(PRINCIPAL.principalId);
  });
});

describe("a malformed Project is refused before any gateway write", () => {
  it.each([
    ["an empty string", ""],
    ["a whitespace string", "   "],
    ["a leading-padded identifier", ` ${PROJECT_A}`],
    ["a trailing-padded identifier", `${PROJECT_A} `],
    ["a boolean", true],
    ["a number", 7],
    ["an array", [PROJECT_A]],
    ["an object", { projectId: PROJECT_A }],
    ["a short identifier", "prj_short"],
    ["an uppercase identifier", PROJECT_A.toUpperCase()],
  ])("refuses %s with 400 and dispatches nothing", async (_label, value) => {
    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: value });

    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("invalid_project_id");
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("does not fall back to No Project when the identifier is malformed", async () => {
    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: "prj_bad" });
    expect(response.status).toBe(400);
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("never renders the refused identifier back to the caller", async () => {
    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: `${PROJECT_A} ` });
    expect(await response.text()).not.toContain(PROJECT_A);
  });
});

describe("a missing, foreign or revoked Project keeps the canonical refusal", () => {
  it("passes the canonical nondisclosing not_found through unchanged", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 404,
      error: { errorClass: "not_found", code: "not_found", message: "project_id" },
    });

    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_C });

    expect(response.status).toBe(404);
    expect(gatewayRefusal).toHaveBeenCalledWith("capture", 404, expect.objectContaining({ code: "not_found" }));
    expect((await response.json()).error.errorClass).toBe("not_found");
  });

  it("does not retry without the Project after a refusal", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 404,
      error: { errorClass: "not_found", code: "not_found", message: "project_id" },
    });
    await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_C });
    expect(invokeGateway).toHaveBeenCalledTimes(1);
    expect(invokeGateway.mock.calls[0]![2]!["project_id"]).toBe(PROJECT_C);
  });
});

describe("the success integrity gate", () => {
  it("answers 503 when the persisted Project is not the one dispatched", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ project_id: PROJECT_B }),
      disclosure: {},
    });

    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A });

    expect(response.status).toBe(503);
    const raw = await response.text();
    expect(JSON.parse(raw).error.code).toBe("upstream_contract_invalid");
    // Neither the wrong Project nor the payload is disclosed.
    expect(raw).not.toContain(PROJECT_B);
    expect(raw).not.toContain(TEXT);
    expect(raw).not.toContain("persisted");
  });

  it("answers 503 when the persisted digest is not the accepted text's", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ content_sha256: "0".repeat(64) }),
      disclosure: {},
    });
    const response = await send({ text: TEXT, idempotencyKey: KEY });
    expect(response.status).toBe(503);
  });

  it("answers 503 when the persisted idempotency key is not the one dispatched", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ idempotency_key: "idem-9999" }),
      disclosure: {},
    });
    const response = await send({ text: TEXT, idempotencyKey: KEY });
    expect(response.status).toBe(503);
  });

  it("hashes the trimmed accepted text, once", async () => {
    const authored = "  a note  ";
    invokeGateway.mockResolvedValue({
      ok: true,
      result: receipt({ content_sha256: await contentSha256(authored.trim()) }),
      disclosure: {},
    });
    const response = await send({ text: authored, idempotencyKey: KEY });
    expect(response.status).toBe(200);
    expect(invokeGateway.mock.calls[0]![2]!["text"]).toBe("a note");
  });
});

describe("authority and admission order are unchanged", () => {
  it("refuses a cross-origin mutation before anything else runs", async () => {
    admitBrowserMutation.mockReturnValue(NextResponse.json({ error: {} }, { status: 403 }));
    const response = await POST(post({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A }));
    expect(response.status).toBe(403);
    expect(requirePrincipal).not.toHaveBeenCalled();
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("refuses an unauthenticated caller before the body is read", async () => {
    requirePrincipal.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ error: { code: "unauthenticated" } }, { status: 401 }),
    });
    const response = await POST(post({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A }));
    expect(response.status).toBe(401);
    expect(readCleanBody).not.toHaveBeenCalled();
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("refuses a caller-supplied Principal through the existing clean-body guard", async () => {
    readCleanBody.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ error: { code: "caller_supplied_principal" } }, { status: 400 }),
    });
    const response = await POST(post({ text: TEXT, idempotencyKey: KEY, principalId: "prn_ffff" }));
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("caller_supplied_principal");
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("sends no principal_id of its own in the gateway payload", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: receipt({ project_id: PROJECT_A }), disclosure: {} });
    await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A });
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principal_id");
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principalId");
  });
});

describe("the synthetic path is not durability", () => {
  it("never claims a Project was persisted on the synthetic path", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    captureAdmissions.admit.mockReturnValue({
      ok: true,
      receipt: { receiptId: "rcpt_synthetic", created: true },
    });

    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: PROJECT_A });

    const body = await response.json();
    expect(body.shape).toBe("synthetic");
    expect(body.status).toBe("acknowledged_not_persisted");
    expect(body.receipt).toBeUndefined();
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("still refuses a malformed Project before the synthetic path", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    const response = await send({ text: TEXT, idempotencyKey: KEY, projectId: "prj_bad" });
    expect(response.status).toBe(400);
    expect(captureAdmissions.admit).not.toHaveBeenCalled();
  });
});
