import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";
import { groupArtifactsByCycle } from "./cycle-selection";
import { ReportListing } from "./report-card";

function entry(overrides: Partial<ReportListEntry> = {}): ReportListEntry {
  return {
    report_id: "rpt_aaaaaaaa11111111",
    cycle_run_id: "micr_aaaaaaaa11111111",
    stage: "collector",
    artifact_kind: "collector_candidates",
    focus_area_id: "communications",
    source_lane: null,
    title: "Current-run collector",
    content_sha256: "a".repeat(64),
    artifact_state: "final",
    ...overrides,
  };
}

afterEach(cleanup);

describe("History report cards", () => {
  it("does not badge prior-cycle cards as Current cycle", () => {
    const items = [
      entry(),
      entry({
        report_id: "rpt_bbbbbbbb22222222",
        cycle_run_id: "micr_bbbbbbbb22222222",
        title: "Prior-run collector",
      }),
    ];
    const dates = [
      { cycle_run_id: "micr_aaaaaaaa11111111", business_date: "2026-08-20" },
      { cycle_run_id: "micr_bbbbbbbb22222222", business_date: "2026-08-19" },
    ];
    const groups = groupArtifactsByCycle(items, dates);
    expect(groups).toHaveLength(2);
    expect(groups[0]?.current).toBe(true);
    expect(groups[1]?.current).toBe(false);

    const { rerender } = render(
      <ReportListing
        items={groups[0]!.items}
        currentCycle={groups[0]!.current ? groups[0]!.cycle_run_id : null}
      />,
    );
    expect(screen.getByText("Current cycle")).toBeTruthy();
    expect(screen.getByText("Current-run collector")).toBeTruthy();

    rerender(
      <ReportListing
        items={groups[1]!.items}
        currentCycle={groups[1]!.current ? groups[1]!.cycle_run_id : null}
      />,
    );
    expect(screen.getByText("Prior-run collector")).toBeTruthy();
    expect(screen.queryByText("Current cycle")).toBeNull();
  });
});
