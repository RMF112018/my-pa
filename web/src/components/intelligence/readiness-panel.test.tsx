import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReadinessPanel } from "./readiness-panel";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import type { ResolverMemberState } from "@/lib/api/decode/capabilities/reports.resolve_set";

afterEach(cleanup);

function member(
  member_id: string,
  readiness: ResolverMemberState,
  required = true,
): ReportsResolveSetResult["members"][number] {
  return {
    member_id,
    readiness,
    required,
    focus_area_id: member_id,
    source_lane: null,
    artifact_id: readiness === "READY" ? "rpt_aaaaaaaa11111111" : null,
    producer_run_id: readiness === "READY" ? "prun_aaaaaaaa11111111" : null,
    content_sha256: readiness === "READY" ? "a".repeat(64) : null,
    committed_at: readiness === "STALE" ? "2026-08-19T12:00:00Z" : readiness === "READY" ? "2026-08-20T12:00:00Z" : null,
    readiness_reason: readiness.toLowerCase(),
  };
}

function result(
  aggregate: ReportsResolveSetResult["aggregate"],
  members: ReportsResolveSetResult["members"],
): ReportsResolveSetResult {
  return {
    cycle_run_id: "micr_aaaaaaaa11111111",
    cycle_id: "morning_intelligence",
    business_date: "2026-08-20",
    set_id: "morning_brief_inputs",
    aggregate,
    members,
  };
}

describe("ReadinessPanel", () => {
  it("renders every member vocabulary and does not map READY to system health", () => {
    const members = [
      member("communications", "READY"),
      member("people", "MISSING"),
      member("projects", "PARTIAL"),
      member("research", "FAILED"),
      member("calendar", "STALE"),
      member("prior", "SUPERSEDED"),
      member("optional", "NOT_EXPECTED", false),
    ];
    render(
      <ReadinessPanel
        cycleRunId="micr_aaaaaaaa11111111"
        answer={{ kind: "resolved", result: result("DEGRADED", members) }}
      />,
    );
    expect(screen.getByTestId("intelligence-readiness-aggregate").textContent).toBe("DEGRADED");
    expect(screen.getByTestId("intelligence-readiness-not-health").textContent).toMatch(
      /not a claim that the system is healthy/,
    );
    expect(screen.getByTestId("intelligence-readiness-partial").textContent).toMatch(
      /Coverage is partial/,
    );
    const states = screen.getAllByTestId("intelligence-readiness-member-state").map((el) => el.textContent);
    expect(states).toEqual([
      "READY",
      "MISSING",
      "PARTIAL",
      "FAILED",
      "STALE",
      "SUPERSEDED",
      "NOT_EXPECTED",
    ]);
    expect(screen.getByTestId("intelligence-business-date").textContent).toBe("2026-08-20");
    expect(screen.getByTestId("intelligence-freshness").textContent).toMatch(/STALE/);
    expect(screen.getByTestId("intelligence-freshness").textContent).not.toMatch(/healthy/);
  });

  it("keeps BLOCKED aggregate and missing members visible rather than empty success", () => {
    render(
      <ReadinessPanel
        cycleRunId="micr_aaaaaaaa11111111"
        answer={{
          kind: "resolved",
          result: result("BLOCKED", [member("communications", "READY"), member("people", "MISSING")]),
        }}
      />,
    );
    expect(screen.getByTestId("intelligence-readiness-aggregate").textContent).toBe("BLOCKED");
    expect(screen.getByTestId("intelligence-readiness-partial").textContent).toMatch(/1 required member is not READY/);
    expect(screen.getByTestId("intelligence-readiness-members").textContent).toMatch(/MISSING/);
    expect(screen.queryByTestId("intelligence-readiness-members-none")).toBeNull();
  });

  it("does not treat an empty member list as specialists all present", () => {
    render(
      <ReadinessPanel
        cycleRunId="micr_aaaaaaaa11111111"
        answer={{ kind: "resolved", result: result("BLOCKED", []) }}
      />,
    );
    expect(screen.getByTestId("intelligence-readiness-members-none").textContent).toMatch(
      /not an empty-success/,
    );
    expect(screen.queryByTestId("intelligence-readiness-members")).toBeNull();
  });

  it("shows unavailable readiness without claiming an empty specialist set", () => {
    render(
      <ReadinessPanel
        cycleRunId="micr_aaaaaaaa11111111"
        answer={{ kind: "unavailable", detail: "gateway did not answer" }}
      />,
    );
    expect(screen.getByTestId("intelligence-readiness-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
    expect(screen.queryByTestId("intelligence-readiness-members")).toBeNull();
  });
});
