/**
 * What the route answers with, for each of the three things it can be asked.
 *
 * The first case is the one that matters most and is the easiest to get wrong.
 * A build with no Constraint capability behind it must say so; it must not
 * render an empty Register, because "you have no Constraints" and "this build
 * cannot ask" are different claims and only one of them is true here.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/work/projects/prj_syn_0001/constraints",
  useRouter: () => ({ push: () => undefined, replace: () => undefined, refresh: () => undefined }),
  useSearchParams: () => new URLSearchParams(),
}));

import ConstraintsPage from "./page";

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

async function renderPage(projectId: string, query: Record<string, string> = {}) {
  const tree: ReactNode = await ConstraintsPage({
    params: Promise.resolve({ projectId }),
    searchParams: Promise.resolve(query),
  });
  return render(tree);
}

describe("the canonical Constraint route", () => {
  it("states that this build serves no Constraint capability, rather than showing zero rows", async () => {
    await renderPage("prj_syn_0001");
    const state = screen.getByTestId("constraints-not-implemented");
    expect(state).toHaveAttribute("data-state", "not_implemented");
    expect(state).toHaveTextContent(/no Constraint read capability/i);
    // Nothing on the page claims the Project holds nothing.
    expect(screen.queryByTestId("register-table")).toBeNull();
    for (const claim of [/holds nothing/i, /you have none/i, /no results/i]) {
      expect(screen.getByTestId("constraints-not-implemented").textContent).not.toMatch(claim);
    }
  });

  it("keeps the Project visible even when it cannot serve the workspace", async () => {
    await renderPage("prj_syn_0001");
    expect(screen.getByText(/Project Controls · prj_syn_0001/)).toBeInTheDocument();
  });

  it("says a Project could not be read rather than showing it as empty", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderPage("prj_not_here");
    const state = screen.getByTestId("constraints-project-unavailable");
    expect(state).toHaveAttribute("data-state", "unavailable");
    expect(state).toHaveAttribute("role", "alert");
  });

  it("serves the fixture workspace when the synthetic provider is enabled", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderPage("prj_syn_0001");
    expect(screen.getByTestId("constraints-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("project-context")).toHaveTextContent("Fixture data");
  });

  it("resolves a deep link's view state on the server, without prior navigation", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderPage("prj_syn_0001", { view: "register", overdue: "1" });
    expect(screen.getByTestId("constraints-workspace")).toBeInTheDocument();
  });
});
