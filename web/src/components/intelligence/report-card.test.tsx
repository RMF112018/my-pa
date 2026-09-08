import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";
import { groupArtifactsByCycle } from "./cycle-selection";
import { ReportCard, ReportListing } from "./report-card";

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

describe("ReportCard", () => {
  it("badges a morning brief as Brief, not Brief artifact", () => {
    render(
      <ReportCard
        row={entry({
          artifact_kind: "morning_brief",
          stage: "morning_brief",
          title: "Morning brief",
        })}
      />,
    );
    const badge = screen.getByTestId("intelligence-brief-artifact");
    expect(badge.textContent).toBe("Brief");
    expect(badge.textContent).not.toMatch(/artifact/i);
    expect(screen.getByRole("link", { name: "Morning brief" })).toBeTruthy();
  });

  it("keeps report and cycle identifiers behind Details", () => {
    const row = entry();
    render(<ReportCard row={row} />);
    const details = screen.getByTestId("intelligence-report-details");
    expect(details.querySelector("summary")?.textContent).toBe("Details");
    expect(screen.getByTestId("intelligence-report-id").textContent).toBe(row.report_id);
    expect(screen.getByTestId("intelligence-report-cycle").textContent).toBe(row.cycle_run_id);
    expect(details.contains(screen.getByTestId("intelligence-report-id"))).toBe(true);
    expect(details.contains(screen.getByTestId("intelligence-report-cycle"))).toBe(true);
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).toBeNull();
  });

  it("labels superseded and partial reports without inventing dates", () => {
    const { rerender } = render(
      <ReportCard row={entry({ artifact_state: "superseded", title: "Superseded collector" })} />,
    );
    expect(document.querySelector("[data-epistemic-role='superseded']")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Superseded collector" })).toBeTruthy();
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).toBeNull();

    rerender(
      <ReportCard row={entry({ artifact_state: "partial", title: "Partial collector" })} />,
    );
    expect(document.querySelector("[data-epistemic-role='pipeline-incomplete']")).not.toBeNull();
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).toBeNull();
  });
});
