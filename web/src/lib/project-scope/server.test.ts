// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PrincipalSession } from "@/contracts/identity";

const { resolveServing, canonicalGatewayProjectReader } = vi.hoisted(() => ({
  resolveServing: vi.fn(),
  canonicalGatewayProjectReader: vi.fn(),
}));
vi.mock("@/lib/api/serving", () => ({ resolveServing }));
vi.mock("./gateway-reader", () => ({ canonicalGatewayProjectReader }));

import { resolveServerProjectScope } from "./server";

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
const LINKED = "prj_aaaaaaaa11111111";
const SAVED = "prj_bbbbbbbb22222222";
const invokeProjectCapability = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  resolveServing.mockReturnValue({ kind: "backend" });
});

describe("resolveServerProjectScope", () => {
  it("resolves a cookie preference only through the authenticated canonical reader", async () => {
    const readProject = vi.fn(async () => ({
      kind: "found" as const,
      project: { project_id: SAVED, state: "on_hold" as const, version: 3 },
    }));
    canonicalGatewayProjectReader.mockReturnValue({
      readProject,
      listProjects: async () => ({ projects: [], nextCursor: null }),
    });
    await expect(
      resolveServerProjectScope({
        principal: PRINCIPAL,
        invokeProjectCapability,
        preferenceValue: `PROJECT:${SAVED}`,
      }),
    ).resolves.toMatchObject({
      scope: { kind: "PROJECT", projectId: SAVED },
      source: "preference",
      project: { state: "on_hold", version: 3 },
    });
    expect(canonicalGatewayProjectReader).toHaveBeenCalledWith(PRINCIPAL, invokeProjectCapability);
    expect(readProject).toHaveBeenCalledWith(SAVED);
  });

  it("gives the explicit route Project precedence over a different cookie Project", async () => {
    const readProject = vi.fn(async (projectId: string) => ({
      kind: "found" as const,
      project: { project_id: projectId, state: "active" as const, version: 8 },
    }));
    canonicalGatewayProjectReader.mockReturnValue({
      readProject,
      listProjects: async () => ({ projects: [], nextCursor: null }),
    });
    const result = await resolveServerProjectScope({
      principal: PRINCIPAL,
      invokeProjectCapability,
      deepLinkProjectId: LINKED,
      preferenceValue: `PROJECT:${SAVED}`,
    });
    expect(result).toMatchObject({
      scope: { kind: "PROJECT", projectId: LINKED },
      source: "deep_link",
    });
    expect(readProject).toHaveBeenCalledOnce();
    expect(readProject).toHaveBeenCalledWith(LINKED);
  });

  it("normalizes a selected Project without crossing synthetic/unconfigured serving boundaries", async () => {
    resolveServing.mockReturnValue({ kind: "synthetic" });
    await expect(
      resolveServerProjectScope({
        principal: PRINCIPAL,
        invokeProjectCapability,
        preferenceValue: `PROJECT:${SAVED}`,
      }),
    ).resolves.toEqual({
      scope: { kind: "ALL_PROJECTS" },
      source: "preference",
      project: null,
      normalized: true,
    });
    expect(canonicalGatewayProjectReader).not.toHaveBeenCalled();
  });

  it("does not fall through to a cookie after a malformed explicit route segment", async () => {
    canonicalGatewayProjectReader.mockReturnValue({
      readProject: vi.fn(),
      listProjects: async () => ({ projects: [], nextCursor: null }),
    });
    await expect(
      resolveServerProjectScope({
        principal: PRINCIPAL,
        invokeProjectCapability,
        deepLinkProjectId: "prj_short",
        preferenceValue: `PROJECT:${SAVED}`,
      }),
    ).resolves.toMatchObject({
      scope: { kind: "ALL_PROJECTS" },
      source: "deep_link",
      normalized: true,
    });
  });
});
