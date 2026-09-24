/**
 * `/work/constraints` — the canonical portfolio Constraint route
 * (`PC-CM-SCOPE-AC-014`).
 *
 * Corrective: proves the page's main body is a real, row-level, cross-Project
 * Constraint Register (`constraints.portfolio_list`/`portfolio_search`) —
 * plan §6.1/§6.2 — not the earlier per-Project card launcher: real rows
 * (not cards), a Project name per row, no Category filter or administration
 * anywhere on the page, and row-open navigating/binding the exact Project and
 * Constraint.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PrincipalSession } from "@/contracts/identity";

const { invokeGateway, push, portfolioRegister } = vi.hoisted(() => ({
  invokeGateway: vi.fn(),
  push: vi.fn(),
  portfolioRegister: vi.fn(),
}));

vi.mock("@/lib/api/gateway", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/gateway")>();
  return { ...actual, invokeGateway };
});
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: (name: string) => (name === "mypa_session" ? { name, value: "a".repeat(64) } : undefined) }),
}));
vi.mock("@/lib/auth/principal", () => ({ resolveSessionPrincipal: async () => PRINCIPAL }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push, refresh: () => undefined }),
}));
vi.mock("@/app/(app)/work/projects/[projectId]/constraints/constraint-live", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/app/(app)/work/projects/[projectId]/constraints/constraint-live")>();
  return { ...actual, readPortfolioRegister: portfolioRegister };
});

import PortfolioConstraintsPage from "./page";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "subject",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const OVERVIEW_DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
} as const;

const REGISTER_DISCLOSURE = {
  scope: "constraint-portfolio-register",
  coverage: "complete",
  freshnessAt: "2026-01-01T00:00:00Z",
  authority: "accepted",
  limitations: [],
  truncated: false,
  nextCursor: null,
} as const;

function overviewOk(omittedProjects = 0) {
  return {
    ok: true,
    result: { overview: { projects: [], asOf: "2026-01-01T00:00:00Z", omittedProjects } },
    disclosure: OVERVIEW_DISCLOSURE,
  };
}

const ROW_A = {
  constraintId: "cst_aaaaaaaa11111111",
  projectId: "prj_aaaaaaaa11111111",
  projectName: "North Viaduct",
  constraintCode: "1.01",
  description: "Confirm the schedule",
  category: null,
  status: "IN_PROGRESS",
  dateIdentified: "2026-01-01",
  dueDate: "2026-02-01",
  bic: [],
  responsible: [],
  reference: null,
  daysElapsed: 10,
  version: 1,
  updatedAt: "2026-01-05T00:00:00Z",
  isOverdue: false,
  isDueSoon: false,
  inMyCourt: false,
  recordQuality: "NORMAL",
  needsAttention: false,
  syncState: "NEVER_SYNCED",
  groupKeys: [],
} as const;

const ROW_B = {
  ...ROW_A,
  constraintId: "cst_bbbbbbbb22222222",
  projectId: "prj_bbbbbbbb22222222",
  projectName: "South Interchange",
  constraintCode: "3.02",
};

function registerOk(entries: readonly unknown[], overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    value: { entries, isTruncated: false, nextCursor: null, omittedProjects: 0, ...overrides },
    disclosure: REGISTER_DISCLOSURE,
  };
}

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })));
  portfolioRegister.mockResolvedValue(registerOk([]));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

async function mount() {
  const tree = await PortfolioConstraintsPage();
  return render(tree);
}

describe("the canonical portfolio Constraint route", () => {
  it("renders real cross-Project rows from constraints.portfolio_list, not Project cards", async () => {
    invokeGateway.mockResolvedValue(overviewOk());
    portfolioRegister.mockResolvedValue(registerOk([ROW_A, ROW_B]));
    await mount();
    await waitFor(() => expect(portfolioRegister).toHaveBeenCalled());
    const table = await screen.findByTestId("register-table");
    expect(within(table).getByRole("button", { name: "1.01" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "3.02" })).toBeInTheDocument();
    // Never the old per-Project card launcher.
    expect(screen.queryByTestId("portfolio-project-list")).toBeNull();
    expect(screen.queryByTestId(`portfolio-project-${ROW_A.projectId}`)).toBeNull();
  });

  it("shows each row's own Project name", async () => {
    invokeGateway.mockResolvedValue(overviewOk());
    portfolioRegister.mockResolvedValue(registerOk([ROW_A, ROW_B]));
    await mount();
    const table = await screen.findByTestId("register-table");
    const rowA = within(table).getByTestId(`register-row-${ROW_A.constraintId}`);
    const rowB = within(table).getByTestId(`register-row-${ROW_B.constraintId}`);
    expect(rowA).toHaveTextContent("North Viaduct");
    expect(rowB).toHaveTextContent("South Interchange");
  });

  it("offers no Category filter and no Category administration anywhere on the page", async () => {
    invokeGateway.mockResolvedValue(overviewOk());
    portfolioRegister.mockResolvedValue(registerOk([ROW_A]));
    await mount();
    await screen.findByTestId("register-table");
    expect(screen.queryByTestId("open-categories")).toBeNull();
    expect(screen.queryByTestId("category-table")).toBeNull();
    // Open the filters panel — Category must stay absent even once every
    // other filter is showing, not merely before the panel is opened.
    expect(screen.getByTestId("register-filters")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("register-filters"));
    expect(screen.getByTestId("register-filter-status")).toBeInTheDocument();
    expect(screen.getByTestId("register-filter-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("register-filter-category")).toBeNull();
  });

  it("opening a row navigates to, and binds, the exact Project and Constraint — never merely the Project", async () => {
    invokeGateway.mockResolvedValue(overviewOk());
    portfolioRegister.mockResolvedValue(registerOk([ROW_A, ROW_B]));
    const user = userEvent.setup();
    await mount();
    const table = await screen.findByTestId("register-table");
    await user.click(within(table).getByRole("button", { name: "3.02" }));
    expect(push).toHaveBeenCalledWith(
      `/work/projects/${ROW_B.projectId}/constraints?view=register&constraint=${ROW_B.constraintId}`,
    );
  });

  it("keeps its own row-level omittedProjects disclosure distinct from the overview's", async () => {
    invokeGateway.mockResolvedValue(overviewOk(2));
    portfolioRegister.mockResolvedValue(registerOk([ROW_A], { omittedProjects: 1 }));
    await mount();
    await screen.findByTestId("register-table");
    // The overview's own figure (top of page).
    expect(screen.getByTestId("portfolio-omitted-projects")).toHaveTextContent("2 owned Projects");
    // The register read's own, separate figure.
    expect(screen.getByTestId("portfolio-register-omitted-projects")).toHaveTextContent("1 owned Project");
  });

  it("states the portfolio position is unavailable rather than showing an empty page", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: { errorClass: "unavailable", code: "gateway_unreachable", message: "down" },
    });
    await mount();
    expect(screen.getByTestId("portfolio-constraints-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(portfolioRegister).not.toHaveBeenCalled();
  });

  it("shows the fixture-not-implemented state in the synthetic build", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await mount();
    expect(invokeGateway).not.toHaveBeenCalled();
    expect(screen.getByTestId("portfolio-constraints-not-implemented")).toBeInTheDocument();
  });
});
