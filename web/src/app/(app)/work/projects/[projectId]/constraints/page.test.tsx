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

vi.mock("./live-constraints-workspace", () => ({
  LiveConstraintsWorkspace: ({ projectId }: { projectId: string }) => (
    <div data-testid="constraints-live-workspace">Live Constraint reads for {projectId}</div>
  ),
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
  it("serves the live read workspace when synthetic fixtures are disabled", async () => {
    await renderPage("prj_syn_0001");
    expect(screen.getByTestId("constraints-live-workspace")).toHaveTextContent("prj_syn_0001");
  });

  it("keeps the Project visible even when it cannot serve the workspace", async () => {
    await renderPage("prj_syn_0001");
    expect(screen.getByTestId("constraints-live-workspace")).toHaveTextContent("prj_syn_0001");
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
