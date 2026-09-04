/**
 * Classify a reports.resolve_set outcome without treating zero members as
 * empty success. Member count is not a substitute for coverage.
 */
import { backendDisclosure, transportLimitations, type GatewayOutcome } from "@/lib/api/gateway";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import type { ReadinessAnswer } from "@/components/intelligence/readiness-panel";

export function readinessAnswerFromOutcome(
  scope: string,
  outcome: GatewayOutcome<ReportsResolveSetResult>,
): ReadinessAnswer {
  if (!outcome.ok) {
    return { kind: "unavailable", detail: outcome.error.message };
  }
  const disclosure = backendDisclosure(scope, outcome.disclosure, transportLimitations());
  if (disclosure.coverage === "unavailable") {
    return {
      kind: "unavailable",
      detail:
        "The backend answered, and reported that morning_brief_inputs was not resolved. " +
        "That is not an empty specialist set.",
    };
  }
  if (disclosure.coverage === "partial") {
    return {
      kind: "degraded",
      result: outcome.result,
      detail: disclosure.limitations.join(" ") || "The resolver answered incompletely.",
    };
  }
  return { kind: "resolved", result: outcome.result };
}
