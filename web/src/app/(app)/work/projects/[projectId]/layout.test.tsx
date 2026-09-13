// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import type { PrincipalSession } from "@/contracts/identity";

const { cookies, redirect, resolveSessionPrincipal, resolveServerProjectScope, invokeGateway } =
  vi.hoisted(() => ({
    cookies: vi.fn(),
    redirect: vi.fn(),
    resolveSessionPrincipal: vi.fn(),
    resolveServerProjectScope: vi.fn(),
    invokeGateway: vi.fn(),
  }));
vi.mock("next/headers", () => ({ cookies }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/lib/auth/principal", () => ({ resolveSessionPrincipal }));
vi.mock("@/lib/project-scope/server", () => ({ resolveServerProjectScope }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway }));

import ProjectRouteLayout from "./layout";

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

describe("Project route scope layout", () => {
  it("uses the real Next route param as explicit deep-link identity ahead of the cookie", async () => {
    cookies.mockResolvedValue({
      get: (name: string) =>
        name === "mypa_session"
          ? { value: "a".repeat(64) }
          : name === "my-pa-project-scope"
            ? { value: "PROJECT:prj_bbbbbbbb22222222" }
            : undefined,
    });
    resolveSessionPrincipal.mockResolvedValue(PRINCIPAL);
    const resolution = {
      scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" },
      source: "deep_link",
      project: { project_id: "prj_aaaaaaaa11111111", state: "active", version: 1 },
      normalized: false,
    } as const;
    const fallbackResolution = {
      scope: { kind: "PROJECT", projectId: "prj_bbbbbbbb22222222" },
      source: "preference",
      project: { project_id: "prj_bbbbbbbb22222222", state: "active", version: 4 },
      normalized: false,
    } as const;
    resolveServerProjectScope
      .mockResolvedValueOnce(fallbackResolution)
      .mockResolvedValueOnce(resolution);
    const tree = await ProjectRouteLayout({
      children: "content",
      params: Promise.resolve({ projectId: "prj_aaaaaaaa11111111" }),
    });
    expect(resolveServerProjectScope).toHaveBeenNthCalledWith(1, {
      principal: PRINCIPAL,
      invokeProjectCapability: invokeGateway,
      preferenceValue: "PROJECT:prj_bbbbbbbb22222222",
    });
    expect(resolveServerProjectScope).toHaveBeenNthCalledWith(2, {
      principal: PRINCIPAL,
      invokeProjectCapability: invokeGateway,
      deepLinkProjectId: "prj_aaaaaaaa11111111",
      preferenceValue: "PROJECT:prj_bbbbbbbb22222222",
    });
    expect(tree.props.resolution).toEqual(resolution);
    expect(tree.props.fallbackResolution).toEqual(fallbackResolution);
  });
});
