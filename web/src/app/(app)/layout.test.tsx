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
vi.mock("@/components/shell/app-shell", () => ({ AppShell: () => null }));

import AppLayout from "./layout";

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
const RESOLUTION = {
  scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" },
  source: "preference",
  project: { project_id: "prj_aaaaaaaa11111111", state: "active", version: 2 },
  normalized: false,
} as const;

describe("authenticated App layout Project Scope", () => {
  it("passes the HttpOnly preference through authenticated server resolution", async () => {
    cookies.mockResolvedValue({
      get: (name: string) =>
        name === "mypa_session"
          ? { value: "a".repeat(64) }
          : name === "my-pa-project-scope"
            ? { value: "PROJECT:prj_aaaaaaaa11111111" }
            : undefined,
    });
    resolveSessionPrincipal.mockResolvedValue(PRINCIPAL);
    resolveServerProjectScope.mockResolvedValue(RESOLUTION);
    const tree = await AppLayout({ children: "content" });
    expect(resolveServerProjectScope).toHaveBeenCalledWith({
      principal: PRINCIPAL,
      invokeProjectCapability: invokeGateway,
      preferenceValue: "PROJECT:prj_aaaaaaaa11111111",
    });
    expect(tree.props.initialProjectScope).toEqual(RESOLUTION);
  });
});
