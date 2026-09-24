import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { useState } from "react";
import {
  ProjectScopeProvider,
  projectScopeLabel,
  useProjectScope,
} from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";
import { sessionReplayBinding } from "@/lib/auth/session";

const PROJECT = "prj_aaaaaaaa11111111";
const OTHER_PROJECT = "prj_bbbbbbbb22222222";
const PRINCIPAL_A = "prn_aaaaaaaa11111111";
const PRINCIPAL_B = "prn_bbbbbbbb22222222";

const PROJECT_V1: ResolvedProjectScope = {
  scope: { kind: "PROJECT", projectId: PROJECT },
  source: "deep_link",
  project: { project_id: PROJECT, name: "Original Project", state: "active", version: 1 },
  normalized: false,
};

function Harness() {
  const { resolution, epoch, applyResolution, isCurrentEpoch } = useProjectScope();
  const [local, setLocal] = useState(0);
  const [initialEpoch] = useState(epoch);
  return (
    <div>
      <output data-testid="scope">{resolution.scope.kind}</output>
      <output data-testid="project">
        {resolution.scope.kind === "PROJECT" ? resolution.scope.projectId : "all"}
      </output>
      <output data-testid="version">{resolution.project?.version ?? "none"}</output>
      <output data-testid="name">{resolution.project?.name ?? "none"}</output>
      <output data-testid="epoch">{epoch}</output>
      <output data-testid="local">{local}</output>
      <output data-testid="current">{String(isCurrentEpoch(epoch))}</output>
      <output data-testid="initial-current">{String(isCurrentEpoch(initialEpoch))}</output>
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

describe("projectScopeLabel", () => {
  it("is the exact canonical name for a resolved Project scope", () => {
    expect(projectScopeLabel(PROJECT_V1)).toBe("Original Project");
  });

  it("is All Projects for ALL_PROJECTS, including a normalized fallback", () => {
    expect(
      projectScopeLabel({
        scope: { kind: "ALL_PROJECTS" },
        source: "default",
        project: null,
        normalized: false,
      }),
    ).toBe("All Projects");
    expect(
      projectScopeLabel({
        scope: { kind: "ALL_PROJECTS" },
        source: "deep_link",
        project: null,
        normalized: true,
      }),
    ).toBe("All Projects");
  });

  it("falls back to the Project id if a PROJECT scope somehow carries no canonical record", () => {
    expect(
      projectScopeLabel({
        scope: { kind: "PROJECT", projectId: PROJECT },
        source: "preference",
        project: null,
        normalized: false,
      }),
    ).toBe(PROJECT);
  });
});

describe("Project Scope provider", () => {
  it("increments a monotonic epoch without broadly remounting authenticated shell state", async () => {
    const user = userEvent.setup();
    render(
      <ProjectScopeProvider principalId={PRINCIPAL_A} sessionEpoch="session:a">
        <Harness />
      </ProjectScopeProvider>,
    );
    expect(screen.getByTestId("epoch")).toHaveTextContent("0");
    await user.click(screen.getByRole("button", { name: "Local" }));
    expect(screen.getByTestId("local")).toHaveTextContent("1");

    await user.click(screen.getByRole("button", { name: "Project v1" }));
    expect(screen.getByTestId("scope")).toHaveTextContent("PROJECT");
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
    expect(screen.getByTestId("local")).toHaveTextContent("1");
    expect(screen.getByTestId("current")).toHaveTextContent("true");
    expect(screen.getByTestId("initial-current")).toHaveTextContent("false");
    expect(screen.getByTestId("name")).toHaveTextContent("Original Project");
  });

  it("does not advance for the same scope/version but does for a new canonical version", async () => {
    const user = userEvent.setup();
    render(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch="session:a"
        initialResolution={PROJECT_V1}
      >
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
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch="session:a"
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Hold" }));
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
  });

  it("reconciles a new authenticated Principal without remounting shell-local state", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch="session:a"
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Local" }));

    const replacement: ResolvedProjectScope = {
      ...PROJECT_V1,
      scope: { kind: "PROJECT", projectId: OTHER_PROJECT },
      project: { project_id: OTHER_PROJECT, name: "Other Project", state: "active", version: 4 },
    };
    rerender(
      <ProjectScopeProvider
        principalId={PRINCIPAL_B}
        sessionEpoch="session:b"
        initialResolution={replacement}
      >
        <Harness />
      </ProjectScopeProvider>,
    );

    expect(screen.getByTestId("project")).toHaveTextContent(OTHER_PROJECT);
    expect(screen.getByTestId("version")).toHaveTextContent("4");
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
    expect(screen.getByTestId("initial-current")).toHaveTextContent("false");
    expect(screen.getByTestId("local")).toHaveTextContent("1");
  });

  it("invalidates the epoch when a new Principal resolves the same Project version", () => {
    const { rerender } = render(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch="session:a"
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    rerender(
      <ProjectScopeProvider
        principalId={PRINCIPAL_B}
        sessionEpoch="session:a"
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
    expect(screen.getByTestId("initial-current")).toHaveTextContent("false");
  });

  it("uses the verified SID binding to distinguish a new session from an ordinary rerender", async () => {
    const firstSession = await sessionReplayBinding("a".repeat(64));
    const nextSession = await sessionReplayBinding("b".repeat(64));
    const { rerender } = render(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch={firstSession}
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    rerender(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch={firstSession}
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    expect(screen.getByTestId("epoch")).toHaveTextContent("0");

    rerender(
      <ProjectScopeProvider
        principalId={PRINCIPAL_A}
        sessionEpoch={nextSession}
        initialResolution={PROJECT_V1}
      >
        <Harness />
      </ProjectScopeProvider>,
    );
    expect(screen.getByTestId("epoch")).toHaveTextContent("1");
    expect(screen.getByTestId("initial-current")).toHaveTextContent("false");
  });
});
