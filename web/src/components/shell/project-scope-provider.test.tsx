import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { useState } from "react";
import {
  ProjectScopeProvider,
  useProjectScope,
} from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

const PROJECT = "prj_aaaaaaaa11111111";

const PROJECT_V1: ResolvedProjectScope = {
  scope: { kind: "PROJECT", projectId: PROJECT },
  source: "deep_link",
  project: { project_id: PROJECT, state: "active", version: 1 },
  normalized: false,
};

function Harness() {
  const { resolution, epoch, applyResolution, isCurrentEpoch } = useProjectScope();
  const [local, setLocal] = useState(0);
  return (
    <div>
      <output data-testid="scope">{resolution.scope.kind}</output>
      <output data-testid="epoch">{epoch}</output>
      <output data-testid="local">{local}</output>
      <output data-testid="current">{String(isCurrentEpoch(epoch))}</output>
      <button type="button" onClick={() => setLocal((value) => value + 1)}>
        Local
      </button>
      <button type="button" onClick={() => applyResolution(PROJECT_V1)}>
        Project v1
      </button>
      <button
        type="button"
        onClick={() =>
          applyResolution({
            ...PROJECT_V1,
            project: { ...PROJECT_V1.project!, version: 2 },
          })
        }
      >
        Project v2
      </button>
      <button
        type="button"
        onClick={() =>
          applyResolution({
            ...PROJECT_V1,
            project: { ...PROJECT_V1.project!, state: "on_hold" },
          })
        }
      >
        Hold
      </button>
    </div>
  );
}

afterEach(cleanup);

describe("Project Scope provider", () => {
  it("increments a monotonic epoch and remounts descendant state on scope transitions", async () => {
    const user = userEvent.setup();
    render(
      <ProjectScopeProvider>
        <Harness />
      </ProjectScopeProvider>,
    );
    expect(screen.getByTestId("epoch")).toHaveTextContent("0");
    await user.click(screen.getByRole("button", { name: "Local" }));
    expect(screen.getByTestId("local")).toHaveTextContent("1");

    await user.click(screen.getByRole("button", { name: "Project v1" }));
    expect(screen.getByTestId("scope")).toHaveTextContent("PROJECT");
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
    expect(screen.getByTestId("local")).toHaveTextContent("0");
    expect(screen.getByTestId("current")).toHaveTextContent("true");
  });

  it("does not advance for the same scope/version but does for a new canonical version", async () => {
    const user = userEvent.setup();
    render(
      <ProjectScopeProvider initialResolution={PROJECT_V1}>
        <Harness />
      </ProjectScopeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Project v1" }));
    expect(screen.getByTestId("epoch")).toHaveTextContent("0");
    await user.click(screen.getByRole("button", { name: "Project v2" }));
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
  });

  it("advances when canonical lifecycle state changes even if an upstream response repeats a version", async () => {
    const user = userEvent.setup();
    render(
      <ProjectScopeProvider initialResolution={PROJECT_V1}>
        <Harness />
      </ProjectScopeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Hold" }));
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
  });
});
