/**
 * `/work/constraints` — the canonical portfolio Constraint route
 * (`PC-CM-SCOPE-AC-014`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";

const { invokeGateway } = vi.hoisted(() => ({ invokeGateway: vi.fn() }));

vi.mock("@/lib/api/gateway", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/gateway")>();
  return { ...actual, invokeGateway };
});
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: (name: string) => (name === "mypa_session" ? { name, value: "a".repeat(64) } : undefined) }),
}));
vi.mock("@/lib/auth/principal", () => ({ resolveSessionPrincipal: async () => PRINCIPAL }));

import PortfolioConstraintsPage from "./page";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "subject",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

async function mount() {
  const tree = await PortfolioConstraintsPage();
  return render(tree);
}

describe("the canonical portfolio Constraint route", () => {
  it("lists every owned Project's own Constraint position, each linking into its own Register", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: {
        overview: {
          projects: [
            {
              projectId: "prj_aaaaaaaa11111111",
              projectName: "North Viaduct",
              totalOpen: 5,
              overdue: 2,
              dueSoon: 1,
              needsAttention: 1,
              draft: 3,
            },
          ],
          asOf: "2026-01-01T00:00:00Z",
          omittedProjects: 0,
        },
      },
      disclosure: {
        coverage: { state: "not_enrolled" },
        freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
        trust: { level: "source_original", basis: ["user_authored_record"] },
        truncation: { is_truncated: false },
        limitations: [],
        partial_result: false,
      },
    });
    await mount();
    expect(invokeGateway).toHaveBeenCalledWith(expect.anything(), "constraints.portfolio_overview", {});
    const link = screen.getByTestId("portfolio-project-prj_aaaaaaaa11111111");
    expect(link).toHaveAttribute("href", "/work/projects/prj_aaaaaaaa11111111/constraints");
    expect(within(link).getByText("North Viaduct")).toBeInTheDocument();
    expect(link).toHaveTextContent("5 open");
    expect(link).toHaveTextContent("2 overdue");
    expect(link).toHaveTextContent("1 needing attention");
    expect(link).toHaveTextContent("3 Drafts");
  });

  it("discloses omitted Projects rather than silently dropping them", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { overview: { projects: [], asOf: "2026-01-01T00:00:00Z", omittedProjects: 2 } },
      disclosure: {
        coverage: { state: "not_enrolled" },
        freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
        trust: { level: "source_original", basis: ["user_authored_record"] },
        truncation: { is_truncated: false },
        limitations: [],
        partial_result: false,
      },
    });
    await mount();
    expect(screen.getByTestId("portfolio-omitted-projects")).toHaveTextContent("2 owned Projects");
    expect(screen.getByTestId("portfolio-constraints-empty")).toHaveAttribute("data-state", "empty");
  });

  it("states the portfolio position is unavailable rather than showing an empty page", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: { errorClass: "unavailable", code: "gateway_unreachable", message: "down" },
    });
    await mount();
    expect(screen.getByTestId("portfolio-constraints-unavailable")).toHaveAttribute("data-state", "unavailable");
  });

  it("shows the fixture-not-implemented state in the synthetic build", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await mount();
    expect(invokeGateway).not.toHaveBeenCalled();
    expect(screen.getByTestId("portfolio-constraints-not-implemented")).toBeInTheDocument();
  });
});
