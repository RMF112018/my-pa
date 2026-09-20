// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
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

/**
 * The layout now returns `DiagnosticsProvider` wrapping `AppShell`, so the
 * shell's props live one level down. This helper names that relationship once
 * instead of spreading `.props.children.props` through every assertion.
 */
function shellOf(tree: { props: { children: { props: Record<string, unknown> } } }) {
  return tree.props.children.props;
}

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

beforeEach(() => {
  vi.clearAllMocks();
});

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
    expect(shellOf(tree).initialProjectScope).toEqual(RESOLUTION);
    expect(shellOf(tree).sessionEpoch).toMatch(/^[0-9a-f]{64}$/);
    expect(shellOf(tree).sessionEpoch).not.toBe("a".repeat(64));

    // WP07: diagnostics are seeded from server-resolved state, and a browser
    // carrying no diagnostics cookie resolves OFF.
    expect(tree.props.initialEnabled).toBe(false);
    expect(tree.props.epoch).toBe(shellOf(tree).sessionEpoch);
  });

  it("derives a distinct browser-safe generation for a new verified SID", async () => {
    let sid = "a".repeat(64);
    cookies.mockResolvedValue({
      get: (name: string) => (name === "mypa_session" ? { value: sid } : undefined),
    });
    resolveSessionPrincipal.mockResolvedValue(PRINCIPAL);
    resolveServerProjectScope.mockResolvedValue(RESOLUTION);

    const first = await AppLayout({ children: "content" });
    sid = "b".repeat(64);
    const second = await AppLayout({ children: "content" });

    expect(shellOf(first).sessionEpoch).toMatch(/^[0-9a-f]{64}$/);
    expect(shellOf(second).sessionEpoch).toMatch(/^[0-9a-f]{64}$/);
    expect(shellOf(second).sessionEpoch).not.toBe(shellOf(first).sessionEpoch);
    // A new SID is a new fencing epoch, which is what stops a delayed ON from
    // an earlier session being applied after a Principal change.
    expect(second.props.epoch).not.toBe(first.props.epoch);
    expect(resolveSessionPrincipal).toHaveBeenNthCalledWith(1, "a".repeat(64));
    expect(resolveSessionPrincipal).toHaveBeenNthCalledWith(2, "b".repeat(64));
  });
});
