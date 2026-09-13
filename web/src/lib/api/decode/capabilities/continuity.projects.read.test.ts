// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeContinuityProjectsRead } from "./continuity.projects.read";

const PROJECT = {
  project_id: "prj_aaaa0001aaaa0001aaaa0001",
  name: "North slab",
  state: "on_hold",
  description: "Awaiting revised sequence",
  participants: [],
  canonical_participations: [],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-03T00:00:00Z",
  version: 7,
};

describe("decodeContinuityProjectsRead", () => {
  it("accepts the direct canonical exact-read payload and retains state/version", () => {
    const decoded = decodeContinuityProjectsRead(PROJECT);
    expect(decoded).toEqual({ ok: true, value: PROJECT });
  });

  it.each([
    ["wrapper instead of direct payload", { project: PROJECT }],
    ["missing version", (({ version: _, ...rest }) => rest)(PROJECT)],
    ["invalid state", { ...PROJECT, state: "paused" }],
    ["non-positive version", { ...PROJECT, version: 0 }],
    [
      "missing canonical participation collection",
      (({ canonical_participations: _, ...rest }) => rest)(PROJECT),
    ],
  ])("fails closed on %s", (_label, payload) => {
    expect(decodeContinuityProjectsRead(payload).ok).toBe(false);
  });
});
