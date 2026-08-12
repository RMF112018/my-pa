/**
 * Synthetic Pulse fixtures — WP-02 only.
 *
 * Every item is labeled `coverage: "synthetic"` / `authority:
 * "synthetic_fixture"` so the UI never presents fixture data as real.
 * Real projections replace this module when the backend read models land.
 *
 * **Both exports are gated** (`./gate`). `syntheticDisclosure` is gated as
 * firmly as the data is, because the label is the half that can lie on its own:
 * a route that attached it to a real backend answer, or that attached a real
 * disclosure to fixture data, would be misreporting provenance in the one field
 * a reader has to check provenance with.
 */
import type { PulseItem } from "@/contracts/views";
import type { PrincipalSession } from "@/contracts/identity";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import { requireSyntheticProvider } from "@/lib/fixtures/gate";

export function syntheticDisclosure(scope: string): DisclosureEnvelope {
  requireSyntheticProvider();
  return {
    scope,
    coverage: "synthetic",
    freshnessAt: null,
    authority: "synthetic_fixture",
    limitations: ["Synthetic fixture data. No live sources are connected."],
    truncated: false,
  };
}

/** Deterministic synthetic Pulse for a principal. */
export function syntheticPulse(principal: PrincipalSession): readonly PulseItem[] {
  requireSyntheticProvider();
  const pid = principal.principalId;
  return [
    {
      pulseItemId: `pulse-${pid}-001`,
      principalId: pid,
      title: "Confirm the concrete pour window with the site team",
      reason:
        "A captured note from yesterday mentions a weather hold; the pour is on tomorrow's plan.",
      consequence: "If the hold stands, the crew schedule needs to move before 3 PM today.",
      uncertainty: "The weather hold has not been confirmed by a second source.",
      nextStep: "Message the superintendent to confirm the hold status.",
      evidenceRefs: [`src-${pid}-note-014`],
      disclosure: syntheticDisclosure("pulse"),
    },
    {
      pulseItemId: `pulse-${pid}-002`,
      principalId: pid,
      title: "An RFI response is waiting on your review",
      reason: "A captured item was classified as an RFI response and routed to Review.",
      consequence: "The submittal package is blocked until the response is dispositioned.",
      uncertainty: null,
      nextStep: "Open Review and disposition the proposal.",
      evidenceRefs: [`src-${pid}-rfi-007`],
      disclosure: syntheticDisclosure("pulse"),
    },
  ];
}
