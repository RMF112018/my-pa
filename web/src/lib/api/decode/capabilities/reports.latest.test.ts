// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsLatest } from "./reports.latest";

const LATEST = {
  report_id: "rpt_aaaaaaaa11111111",
  cycle_run_id: "micr_aaaaaaaa11111111",
  stage: "collector",
  artifact_kind: "collector_candidates",
  focus_area_id: "communications",
  source_lane: null,
  content_sha256: "a".repeat(64),
  artifact_state: "final",
};

describe("decodeReportsLatest", () => {
  it("accepts a Python-derived success payload", () => {
    expect(decodeReportsLatest(LATEST).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReportsLatest({ ...LATEST, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when a required field is missing", () => {
    const { report_id: _, ...rest } = LATEST;
    expect(decodeReportsLatest(rest).ok).toBe(false);
    expect(decodeReportsLatest({}).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeReportsLatest({ ...LATEST, content_sha256: 1 }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeReportsLatest({ ...LATEST, stage: "planner" }).ok).toBe(false);
    expect(decodeReportsLatest({ ...LATEST, artifact_state: "draft" }).ok).toBe(false);
  });
});
