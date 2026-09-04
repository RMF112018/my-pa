import { describe, expect, it } from "vitest";
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";
import {
  currentCycleRunId,
  groupArtifactsByCycle,
  MORNING_BRIEF_SET_ID,
  nonReadyRequiredCount,
  resolveSetPayload,
} from "./cycle-selection";

function entry(overrides: Partial<ReportListEntry> = {}): ReportListEntry {
  return {
    report_id: "rpt_aaaaaaaa11111111",
    cycle_run_id: "micr_aaaaaaaa11111111",
    stage: "collector",
    artifact_kind: "collector_candidates",
    focus_area_id: "communications",
    source_lane: null,
    title: "E2E morning brief collector",
    content_sha256: "a".repeat(64),
    artifact_state: "final",
    ...overrides,
  };
}

describe("cycle selection from backend fields", () => {
  it("does not invent a cycle from the browser clock", () => {
    expect(currentCycleRunId([])).toBeNull();
    expect(currentCycleRunId([entry()])).toBe("micr_aaaaaaaa11111111");
    expect(resolveSetPayload("micr_aaaaaaaa11111111")).toEqual({
      cycle_run_id: "micr_aaaaaaaa11111111",
      set_id: MORNING_BRIEF_SET_ID,
    });
  });

  it("uses the first listed cycle when resolve_set dates are absent", () => {
    const items = [
      entry({ report_id: "rpt_older0000000001", cycle_run_id: "micr_older0000000001" }),
      entry({ report_id: "rpt_newer0000000001", cycle_run_id: "micr_newer0000000001" }),
    ];
    expect(currentCycleRunId(items)).toBe("micr_older0000000001");
  });

  it("falls back to list order when only some cycles have resolve_set dates", () => {
    const items = [
      entry({ report_id: "rpt_listedfirst0001", cycle_run_id: "micr_listedfirst0001" }),
      entry({ report_id: "rpt_datedolder00001", cycle_run_id: "micr_datedolder00001" }),
    ];
    const dates = [{ cycle_run_id: "micr_datedolder00001", business_date: "2026-08-20" }];
    expect(currentCycleRunId(items, dates)).toBe("micr_listedfirst0001");
    const groups = groupArtifactsByCycle(items, dates);
    expect(groups.find((group) => group.cycle_run_id === "micr_listedfirst0001")?.current).toBe(
      true,
    );
    expect(groups.find((group) => group.cycle_run_id === "micr_datedolder00001")?.current).toBe(
      false,
    );
  });

  it("selects current vs history from backend business_date, not Date.now()", () => {
    const items = [
      entry({
        report_id: "rpt_older0000000001",
        cycle_run_id: "micr_older0000000001",
        title: "Older run",
      }),
      entry({
        report_id: "rpt_newer0000000001",
        cycle_run_id: "micr_newer0000000001",
        title: "Newer run",
      }),
    ];
    const dates = [
      { cycle_run_id: "micr_older0000000001", business_date: "2026-08-19" },
      { cycle_run_id: "micr_newer0000000001", business_date: "2026-08-20" },
    ];
    expect(currentCycleRunId(items, dates)).toBe("micr_newer0000000001");
    const groups = groupArtifactsByCycle(items, dates);
    expect(groups.map((group) => group.cycle_run_id)).toEqual([
      "micr_newer0000000001",
      "micr_older0000000001",
    ]);
    expect(groups[0]?.current).toBe(true);
    expect(groups[0]?.business_date).toBe("2026-08-20");
    expect(groups[1]?.current).toBe(false);
  });

  it("counts non-READY required members without treating them as empty success", () => {
    expect(
      nonReadyRequiredCount([
        { required: true, readiness: "READY" },
        { required: true, readiness: "MISSING" },
        { required: false, readiness: "NOT_EXPECTED" },
      ]),
    ).toBe(1);
    expect(nonReadyRequiredCount([])).toBe(0);
  });
});
