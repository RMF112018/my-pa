// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";
import { PROJECT_SCOPE_COOKIE } from "@/lib/project-scope/preference";

const { requirePrincipal, invokeGateway, resolveServing } = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
}));

vi.mock("@/lib/api/guard", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/guard")>();
  return { ...actual, requirePrincipal };
});
vi.mock("@/lib/api/gateway", () => ({ invokeGateway }));
vi.mock("@/lib/api/serving", () => ({ resolveServing }));

import * as route from "./route";

const { POST } = route;

const ORIGIN = "http://localhost:3000";

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
  name: "North Bridge",
  state: "active" as const,
  version: 4,
};

function request(
  body: unknown,
  init: { origin?: string | null; fetchSite?: string | null; rawBody?: string } = {},
): NextRequest {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const origin = init.origin === undefined ? ORIGIN : init.origin;
  if (origin !== null) headers["origin"] = origin;
  if (init.fetchSite != null) headers["sec-fetch-site"] = init.fetchSite;
  return new NextRequest(`${ORIGIN}/api/project-scope`, {
    method: "POST",
    headers,
    body: init.rawBody ?? JSON.stringify(body),
  });
}

async function post(body: unknown, init?: Parameters<typeof request>[1]) {
  return POST(request(body, init));
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
});

describe("POST /api/project-scope", () => {
  it("has no PUT handler — this route only ever replaces the preference by value", () => {
    expect((route as Record<string, unknown>).PUT).toBeUndefined();
  });

  it("refuses a cross-site request before touching the session or the gateway", async () => {
    const response = await post(
      { scope: "ALL_PROJECTS" },
      { origin: "https://evil.example" },
    );
    expect(response.status).toBe(403);
    expect(requirePrincipal).not.toHaveBeenCalled();
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("requires a valid session Principal", async () => {
    requirePrincipal.mockResolvedValue({
      ok: false,
      response: new Response(
        JSON.stringify({ error: { code: "unauthenticated", message: "no valid session" } }),
        { status: 401 },
      ),
    });
    const response = await post({ scope: "ALL_PROJECTS" });
    expect(response.status).toBe(401);
  });

  it.each([
    ["malformed JSON", undefined, { rawBody: "{not json" }],
    ["an unknown scope value", { scope: "SOME_PROJECTS" }, {}],
    ["ALL_PROJECTS with an extra field", { scope: "ALL_PROJECTS", projectId: PROJECT_ID }, {}],
    ["PROJECT missing projectId", { scope: "PROJECT" }, {}],
    ["PROJECT with an extra field", { scope: "PROJECT", projectId: PROJECT_ID, extra: 1 }, {}],
    ["PROJECT with a malformed projectId", { scope: "PROJECT", projectId: "not-a-project-id" }, {}],
    ["a non-object body", [1, 2, 3], {}],
  ] as const)("400s on %s", async (_label, body, init) => {
    const response = await post(body, init);
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(resolveServing).not.toHaveBeenCalled();
  });

  it("400s a well-shaped-but-unknown scope value with the validation error class", async () => {
    const response = await post({ scope: "SOME_PROJECTS" });
    expect((await response.json()).error.errorClass).toBe("validation");
  });

  it("writes the exact serialized cookie and returns ALL_PROJECTS without reading the gateway", async () => {
    const response = await post({ scope: "ALL_PROJECTS" });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ scope: "ALL_PROJECTS" });
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(invokeGateway).not.toHaveBeenCalled();
    const setCookie = response.headers.get("set-cookie")!;
    expect(setCookie.startsWith(`${PROJECT_SCOPE_COOKIE}=ALL_PROJECTS;`)).toBe(true);
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Lax");
    expect(setCookie).toContain("Max-Age=31536000");
  });

  it("resolves a PROJECT selection through the same canonical exact-read composition gateway-reader.ts uses, and writes its cookie", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: PROJECT, disclosure: {} });
    const response = await post({ scope: "PROJECT", projectId: PROJECT_ID });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      scope: "PROJECT",
      project: { id: PROJECT_ID, name: "North Bridge", state: "active", version: 4 },
    });
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "continuity.projects.read", {
      project_id: PROJECT_ID,
    });
    const setCookie = response.headers.get("set-cookie")!;
    expect(setCookie.startsWith(`${PROJECT_SCOPE_COOKIE}=PROJECT:${PROJECT_ID};`)).toBe(true);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it.each([
    // The canonical `continuity.projects.read` capability itself already
    // answers a foreign Project with the same 404 as a missing one (see
    // `GET /api/projects/[projectId]`'s own comment on this), so "foreign"
    // is not a distinct fixture here — it arrives as this same "unknown" 404.
    ["unknown", { ok: false, status: 404, error: { errorClass: "not_found" } }],
    [
      "closed",
      {
        ok: true,
        result: { ...PROJECT, state: "closed" },
        disclosure: {},
      },
    ],
  ] as const)("makes an %s Project the identical generic 404 — no disclosing signal", async (_label, outcome) => {
    invokeGateway.mockResolvedValue(outcome);
    const response = await post({ scope: "PROJECT", projectId: PROJECT_ID });
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: {
        errorClass: "not_found",
        code: "not_found",
        message: "the Project could not be read",
      },
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("answers 503 typed unavailable when the backend cannot be reached", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: { errorClass: "unavailable" },
    });
    const response = await post({ scope: "PROJECT", projectId: PROJECT_ID });
    expect(response.status).toBe(503);
    expect((await response.json()).error.errorClass).toBe("unavailable");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it(
    "surfaces a non-404 gateway refusal (e.g. a policy denial distinct from the " +
      "capability's own nondisclosure) as 503 unavailable, inherited unchanged from " +
      "canonicalGatewayProjectReader's existing status mapping",
    async () => {
      invokeGateway.mockResolvedValue({
        ok: false,
        status: 403,
        error: { errorClass: "authorization" },
      });
      const response = await post({ scope: "PROJECT", projectId: PROJECT_ID });
      expect(response.status).toBe(503);
    },
  );

  it("refuses a PROJECT selection under explicitly synthetic serving rather than fabricating a resolution", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    const response = await post({ scope: "PROJECT", projectId: PROJECT_ID });
    expect(response.status).toBe(404);
    expect(invokeGateway).not.toHaveBeenCalled();
  });

  it("does not consult the gateway or serving to refuse a caller-supplied identity field", async () => {
    const response = await post({ scope: "ALL_PROJECTS", principal_id: "prn_ffffffffffffffffffffffffffffffff" });
    expect(response.status).toBe(400);
    expect(resolveServing).not.toHaveBeenCalled();
  });
});
