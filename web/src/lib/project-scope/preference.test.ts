import { describe, expect, it } from "vitest";
import { projectFromDeepLink } from "./deep-link";
import {
  parseProjectScopePreference,
  projectScopePreferenceValue,
  serializeProjectScopePreference,
} from "./preference";
import { ALL_PROJECTS, projectScope } from "./scope";

const PROJECT = "prj_aaaaaaaa11111111";

describe("Project Scope preference", () => {
  it("round-trips only the closed scope vocabulary", () => {
    expect(parseProjectScopePreference(projectScopePreferenceValue(ALL_PROJECTS))).toEqual(
      ALL_PROJECTS,
    );
    expect(parseProjectScopePreference(projectScopePreferenceValue(projectScope(PROJECT)))).toEqual(
      projectScope(PROJECT),
    );
  });

  it.each([
    undefined,
    "",
    "all_projects",
    " ALL_PROJECTS",
    "ALL_PROJECTS ",
    "PROJECT",
    "PROJECT:",
    "PROJECT:prj_short",
    "PROJECT:prj_aaaaaaaa1111!111",
    "PROJECT:%70rj_aaaaaaaa11111111",
    `PROJECT:${PROJECT}:extra`,
  ])("rejects malformed or non-canonical value %s", (value) => {
    expect(parseProjectScopePreference(value)).toBeNull();
  });

  it("serializes a bounded first-party HttpOnly preference", () => {
    expect(serializeProjectScopePreference(projectScope(PROJECT), { secure: true })).toBe(
      `my-pa-project-scope=PROJECT:${PROJECT}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax; Secure`,
    );
  });
});
describe("Project deep links", () => {
  it("extracts only the canonical Project route segment", () => {
    expect(projectFromDeepLink(`/work/projects/${PROJECT}/constraints`)).toEqual({
      kind: "present",
      projectId: PROJECT,
    });
    expect(projectFromDeepLink("/work")).toEqual({ kind: "absent" });
  });

  it("keeps a malformed explicit segment present so it cannot fall through to preference", () => {
    expect(projectFromDeepLink("/work/projects/prj_short/constraints")).toEqual({
      kind: "present",
      projectId: null,
    });
    expect(projectFromDeepLink("/work/projects/%E0%A4%A/constraints")).toEqual({
      kind: "present",
      projectId: null,
    });
  });
});
