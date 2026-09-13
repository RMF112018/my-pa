import { describe, expect, it, vi } from "vitest";
import {
  discoverProjectScopes,
  resolveAuthenticatedProjectScope,
  type CanonicalProjectScopeReader,
  type CanonicalProjectState,
} from "./resolver";

const LINKED = "prj_aaaaaaaa11111111";
const SAVED = "prj_bbbbbbbb22222222";

function reader(
  answers: Partial<Record<string, { state: CanonicalProjectState; version: number }>> = {},
): CanonicalProjectScopeReader {
  return {
    readProject: vi.fn(async (projectId: string) => {
      const answer = answers[projectId];
      return answer
        ? {
            kind: "found" as const,
            project: { project_id: projectId, state: answer.state, version: answer.version },
          }
        : { kind: "not_found" as const };
    }),
    listProjects: vi.fn(async () => []),
  };
}

describe("authenticated Project Scope resolution", () => {
  it("gives an explicit deep link precedence over a saved preference", async () => {
    const projects = reader({
      [LINKED]: { state: "active", version: 4 },
      [SAVED]: { state: "active", version: 8 },
    });
    const resolution = await resolveAuthenticatedProjectScope({
      deepLinkProjectId: LINKED,
      preferenceValue: `PROJECT:${SAVED}`,
      projects,
    });
    expect(resolution).toEqual({
      scope: { kind: "PROJECT", projectId: LINKED },
      source: "deep_link",
      project: { project_id: LINKED, state: "active", version: 4 },
      normalized: false,
    });
    expect(projects.readProject).toHaveBeenCalledTimes(1);
    expect(projects.readProject).toHaveBeenCalledWith(LINKED);
  });

  it("uses a canonical saved preference when no deep link is present", async () => {
    const projects = reader({ [SAVED]: { state: "on_hold", version: 3 } });
    const resolution = await resolveAuthenticatedProjectScope({
      preferenceValue: `PROJECT:${SAVED}`,
      projects,
    });
    expect(resolution.scope).toEqual({ kind: "PROJECT", projectId: SAVED });
    expect(resolution.project).toMatchObject({ state: "on_hold", version: 3 });
    expect(resolution.source).toBe("preference");
  });

  it.each([
    ["missing", reader()],
    ["closed", reader({ [LINKED]: { state: "closed", version: 2 } })],
    ["invalid version", reader({ [LINKED]: { state: "active", version: 0 } })],
  ])("normalizes %s without exposing why the Project was ineligible", async (_label, projects) => {
    await expect(
      resolveAuthenticatedProjectScope({ deepLinkProjectId: LINKED, projects }),
    ).resolves.toEqual({
      scope: { kind: "ALL_PROJECTS" },
      source: "deep_link",
      project: null,
      normalized: true,
    });
  });

  it("does not consult preference after a malformed explicit deep link", async () => {
    const projects = reader({ [SAVED]: { state: "active", version: 1 } });
    const result = await resolveAuthenticatedProjectScope({
      deepLinkProjectId: null,
      preferenceValue: `PROJECT:${SAVED}`,
      projects,
    });
    expect(result).toMatchObject({
      scope: { kind: "ALL_PROJECTS" },
      source: "deep_link",
      normalized: true,
    });
    expect(projects.readProject).not.toHaveBeenCalled();
  });

  it("normalizes a mismatched canonical response instead of trusting its identity", async () => {
    const projects: CanonicalProjectScopeReader = {
      readProject: async () => ({
        kind: "found",
        project: { project_id: SAVED, state: "active", version: 1 },
      }),
      listProjects: async () => [],
    };
    const result = await resolveAuthenticatedProjectScope({
      deepLinkProjectId: LINKED,
      projects,
    });
    expect(result.scope).toEqual({ kind: "ALL_PROJECTS" });
    expect(result.normalized).toBe(true);
  });

  it("does not call exact read for ALL_PROJECTS", async () => {
    const projects = reader();
    const result = await resolveAuthenticatedProjectScope({
      preferenceValue: "ALL_PROJECTS",
      projects,
    });
    expect(result).toMatchObject({ source: "preference", normalized: false });
    expect(projects.readProject).not.toHaveBeenCalled();
  });

  it("composes bounded discovery from the canonical Project list response", async () => {
    const listProjects = vi.fn(async () => [
      { project_id: LINKED, state: "active" as const, version: 4 },
      { project_id: SAVED, state: "closed" as const, version: 7 },
      { project_id: "prj_short", state: "active" as const, version: 1 },
    ]);
    const projects: CanonicalProjectScopeReader = {
      readProject: async () => ({ kind: "not_found" }),
      listProjects,
    };
    await expect(
      discoverProjectScopes(projects, { state: "active", query: "steel", pageSize: 500 }),
    ).resolves.toEqual([{ project_id: LINKED, state: "active", version: 4 }]);
    expect(listProjects).toHaveBeenCalledWith({
      state: "active",
      query: "steel",
      pageSize: 100,
    });
  });
});
