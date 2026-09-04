import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReportDetailView, structuredContentKeys } from "./report-detail-view";
import { ReportCard } from "./report-card";
import type { ReportsReadResult } from "@/lib/api/decode/capabilities/reports.read";
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";

afterEach(cleanup);

const REPORT: ReportsReadResult = {
  report_id: "rpt_aaaaaaaa11111111",
  report_run_id: "rrun_aaaaaaaa11111111",
  cycle_run_id: "micr_aaaaaaaa11111111",
  focus_area_id: "communications",
  stage: "collector",
  artifact_kind: "collector_candidates",
  source_lane: null,
  report_date: "2026-08-20",
  title: "E2E morning brief collector",
  artifact_state: "final",
  content_sha256: "a".repeat(64),
  content_bytes: 48,
  committed_at: "2026-08-20T12:00:00Z",
  version: 1,
  supersedes_report_id: null,
  dependency_report_ids: [],
  provenance: [
    {
      source_system: "synthetic",
      source_ref: "src_aaaaaaaa11111111",
      relation: "supports",
      source_url: null,
    },
  ],
  body_markdown: "# Morning Brief\n\n- scraped item one",
  structured_content: { lane: "persisted", marker: "e2e-structured-not-from-markdown" },
};

describe("opaque structured_content", () => {
  it("lists keys and does not treat them as Brief items", () => {
    expect(structuredContentKeys(REPORT.structured_content)).toEqual(["lane", "marker"]);
    expect(structuredContentKeys({ items: [{ id: "invented" }] })).toEqual(["items"]);
    expect(structuredContentKeys(undefined)).toEqual([]);
  });

  it("discloses persisted structured content without rendering item schema", () => {
    render(<ReportDetailView report={REPORT} />);
    expect(screen.getByTestId("intelligence-structured-present").textContent).toMatch(
      /not a Brief section\/item schema/,
    );
    expect(screen.getByTestId("intelligence-structured-keys").textContent).toMatch(/lane/);
    expect(screen.queryByTestId("brief-item")).toBeNull();
    expect(screen.getByTestId("intelligence-body-markdown").textContent).toMatch(/scraped item one/);
    expect(screen.queryByText(/task from brief/i)).toBeNull();
  });
});

describe("superseded and malformed report rendering", () => {
  it("labels a superseded artifact without hiding it", () => {
    render(
      <ReportDetailView
        report={{
          ...REPORT,
          artifact_state: "superseded",
          supersedes_report_id: "rpt_bbbbbbbb22222222",
          body_markdown: undefined,
          structured_content: undefined,
        }}
      />,
    );
    expect(screen.getByTestId("intelligence-artifact-state").textContent).toBe("superseded");
    expect(screen.getByTestId("intelligence-supersedes").textContent).toMatch(/rpt_bbbbbbbb22222222/);
    expect(screen.getByTestId("intelligence-body-absent")).toBeTruthy();
    expect(document.querySelector("[data-epistemic-role='superseded']")).not.toBeNull();
  });

  it("does not scrape malformed HTML into Brief items", () => {
    render(
      <ReportDetailView
        report={{
          ...REPORT,
          body_markdown: '<script>alert(1)</script>\n\n<img src="javascript:alert(1)">',
          structured_content: { items: ["scraped item one"] },
        }}
      />,
    );
    expect(screen.queryByRole("link", { name: /javascript/i })).toBeNull();
    expect(screen.getByTestId("intelligence-structured-keys").textContent).toMatch(/items/);
    expect(screen.queryByTestId("brief-item")).toBeNull();
    expect(screen.getByTestId("intelligence-structured-present").textContent).toMatch(
      /not rendered as items/,
    );
  });

  it("highlights a morning_brief listing card as an artifact, not items", () => {
    const row: ReportListEntry = {
      report_id: "rpt_brief0000000001",
      cycle_run_id: "micr_aaaaaaaa11111111",
      stage: "morning_brief",
      artifact_kind: "morning_brief",
      focus_area_id: null,
      source_lane: null,
      title: "Morning brief artifact",
      content_sha256: "b".repeat(64),
      artifact_state: "final",
    };
    render(<ReportCard row={row} currentCycle={row.cycle_run_id} />);
    expect(screen.getByTestId("intelligence-brief-artifact").textContent).toBe("Brief artifact");
    expect(screen.queryByText("scraped item one")).toBeNull();
  });
});
