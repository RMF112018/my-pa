// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeContinuityProjects } from "./continuity.projects";

const PROJECT = {
  project_id: "prj_aaaa0001aaaa0001aaaa0001",
  name: "North slab",
  state: "active",
  description: null,
  participants: ["per_aaaa0001aaaa0001aaaa0001"],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
};

describe("decodeContinuityProjects", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeContinuityProjects({ projects: [PROJECT] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.projects).toHaveLength(1);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeContinuityProjects({ projects: [{ ...PROJECT, extra: 1 }], noise: true }).ok).toBe(
      true,
    );
  });

  it("fails closed when projects is omitted", () => {
    expect(decodeContinuityProjects({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeContinuityProjects({}).ok).toBe(false);
    const empty = decodeContinuityProjects({ projects: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.projects).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeContinuityProjects({ projects: 1 }).ok).toBe(false);
    expect(decodeContinuityProjects({ projects: [{ ...PROJECT, participants: "x" }] }).ok).toBe(
      false,
    );
  });

  it("fails closed when a required field is missing", () => {
    const { name: _, ...rest } = PROJECT;
    expect(decodeContinuityProjects({ projects: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeContinuityProjects({ projects: [{ ...PROJECT, state: "paused" }] }).ok).toBe(
      false,
    );
  });
});
