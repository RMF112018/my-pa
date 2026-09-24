/**
 * The Constraints command-center panel (`PC-CM-SCOPE-AC-019`/`-020`/`-021`).
 *
 * Situations/Projects board behaviour is already covered end-to-end, with a
 * realistic fetch stub, in `app/(app)/surfaces.test.tsx`'s "Situations never
 * calls a partial answer an empty board" suite — this file is deliberately
 * narrower and exists only for the one thing that suite's shared cookie stub
 * cannot exercise: the Constraints panel's two scope-dependent branches
 * (`PROJECT` vs `ALL_PROJECTS`), which turn on the `my-pa-project-scope`
 * cookie that suite's harness hard-codes away.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";

const { invokeGateway, cookieValue } = vi.hoisted(() => ({
  invokeGateway: vi.fn(),
  cookieValue: { current: undefined as string | undefined },
}));

vi.mock("@/lib/api/gateway", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/gateway")>();
  return { ...actual, invokeGateway };
});
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "my-pa-project-scope" && cookieValue.current !== undefined
        ? { name, value: cookieValue.current }
        : name === "mypa_session"
          ? { name, value: "a".repeat(64) }
          : undefined,
  }),
}));
vi.mock("@/lib/auth/principal", () => ({ resolveSessionPrincipal: async () => PRINCIPAL }));

import { WorkPage } from "./work-page";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "subject",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

/**
 * `invokeGateway`'s own `disclosure` member is the raw decoded Python
 * envelope (`PythonDisclosure`), not the BFF-facing `DisclosureEnvelope` —
 * `surfaceAnswer()` (used for the Situations/Projects halves) converts one
 * into the other via `backendDisclosure`, so this mock supplies the shape
 * that conversion actually reads.
 */
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
} as const;

const EMPTY_BOARD_ANSWER = { situations: [], projects: [] };

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
  cookieValue.current = undefined;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

async function mount() {
  const tree = await WorkPage();
  return render(tree);
}

describe("the Work command center's Constraints panel", () => {
  it("routes to the exact-Project Constraints route and shows that Project's own figures", async () => {
    cookieValue.current = "PROJECT:prj_aaaaaaaa11111111";
    invokeGateway.mockImplementation(async (_principal: unknown, capability: string) => {
      if (capability === "continuity.situations" || capability === "continuity.projects") {
        return { ok: true, result: EMPTY_BOARD_ANSWER, disclosure: DISCLOSURE };
      }
      if (capability === "constraints.overview") {
        return {
          ok: true,
          result: { overview: { totalOpen: 4, needsAttention: 1 } },
          disclosure: DISCLOSURE,
        };
      }
      throw new Error(`unexpected capability ${capability}`);
    });
    await mount();
    const panel = screen.getByTestId("work-constraints-panel");
    expect(panel).toHaveAttribute("href", "/work/projects/prj_aaaaaaaa11111111/constraints");
    expect(panel).toHaveTextContent("4 open");
    expect(panel).toHaveTextContent("1 needing attention");
    expect(invokeGateway).toHaveBeenCalledWith(
      expect.anything(),
      "constraints.overview",
      { project_id: "prj_aaaaaaaa11111111" },
    );
  });

  it("routes to the portfolio Constraints route and counts Projects, never a summed total", async () => {
    // No PROJECT cookie: the default is ALL_PROJECTS.
    invokeGateway.mockImplementation(async (_principal: unknown, capability: string) => {
      if (capability === "continuity.situations" || capability === "continuity.projects") {
        return { ok: true, result: EMPTY_BOARD_ANSWER, disclosure: DISCLOSURE };
      }
      if (capability === "constraints.portfolio_overview") {
        return {
          ok: true,
          result: {
            overview: {
              projects: [
                { projectId: "prj_aaaaaaaa11111111", totalOpen: 3, needsAttention: 1 },
                { projectId: "prj_bbbbbbbb22222222", totalOpen: 0, needsAttention: 0 },
                { projectId: "prj_cccccccc33333333", totalOpen: 2, needsAttention: 0 },
              ],
              asOf: "2026-01-01T00:00:00Z",
              omittedProjects: 0,
            },
          },
          disclosure: DISCLOSURE,
        };
      }
      throw new Error(`unexpected capability ${capability}`);
    });
    await mount();
    const panel = screen.getByTestId("work-constraints-panel");
    expect(panel).toHaveAttribute("href", "/work/constraints");
    // Two of three owned Projects carry an open Constraint; one needs
    // attention — never a cross-Project sum of `totalOpen`.
    expect(panel).toHaveTextContent("2 Projects with open Constraints");
    expect(panel).toHaveTextContent("1 needing attention");
    expect(invokeGateway).toHaveBeenCalledWith(expect.anything(), "constraints.portfolio_overview", {});
  });

  it("states the Constraints panel is unavailable rather than showing a false zero", async () => {
    invokeGateway.mockImplementation(async (_principal: unknown, capability: string) => {
      if (capability === "continuity.situations" || capability === "continuity.projects") {
        return { ok: true, result: EMPTY_BOARD_ANSWER, disclosure: DISCLOSURE };
      }
      return { ok: false, status: 503, error: { errorClass: "unavailable", code: "gateway_unreachable", message: "down" } };
    });
    await mount();
    const state = screen.getByTestId("work-constraints-unavailable");
    expect(state).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("work-constraints-panel")).toBeNull();
  });
});
