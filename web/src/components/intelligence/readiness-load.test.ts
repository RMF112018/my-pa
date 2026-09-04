// @vitest-environment node
import { describe, expect, it } from "vitest";
import { readinessAnswerFromOutcome } from "./readiness-load";
import type { GatewayOutcome } from "@/lib/api/gateway";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import type { PythonDisclosure } from "@/lib/api/gateway";

const DISCLOSURE: PythonDisclosure = {
  coverage: { state: "processed" },
  freshness: { observed_at: "2026-08-20T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_bound_derived", basis: ["report_artifact"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

const RESULT: ReportsResolveSetResult = {
  cycle_run_id: "micr_aaaaaaaa11111111",
  cycle_id: "morning_intelligence",
  business_date: "2026-08-20",
  set_id: "morning_brief_inputs",
  aggregate: "BLOCKED",
  members: [],
};

describe("readinessAnswerFromOutcome", () => {
  it("keeps an empty member array as a resolved answer, not empty success", () => {
    const outcome: GatewayOutcome<ReportsResolveSetResult> = {
      ok: true,
      result: RESULT,
      disclosure: DISCLOSURE,
    };
    const answer = readinessAnswerFromOutcome("intelligence:reports.resolve_set", outcome);
    expect(answer.kind).toBe("resolved");
    if (answer.kind === "resolved") {
      expect(answer.result.aggregate).toBe("BLOCKED");
      expect(answer.result.members).toEqual([]);
      expect(answer.result.business_date).toBe("2026-08-20");
    }
  });

  it("does not invent READY coverage when the gateway refused", () => {
    const outcome: GatewayOutcome<ReportsResolveSetResult> = {
      ok: false,
      status: 503,
      error: {
        errorClass: "unavailable",
        code: "gateway_unreachable",
        message: "the application gateway did not answer",
      },
    };
    expect(readinessAnswerFromOutcome("intelligence:reports.resolve_set", outcome)).toEqual({
      kind: "unavailable",
      detail: "the application gateway did not answer",
    });
  });
});
