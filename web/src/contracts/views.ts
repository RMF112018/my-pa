/**
 * View-facing canonical contracts: Situation, Frame, Trace, ReviewCase,
 * PulseItem — parity with the v4.0 domain model definitions.
 *
 * These are derived, principal-scoped projections. A Trace is not source
 * evidence; a PulseItem is a recommendation with a reason, never a bare alert.
 */
import type { DisclosureEnvelope, IsoTimestamp, OpaqueId, SourceSpan } from "./envelope";
import type { ProposalState } from "./states";

/** Purposeful operational context referencing objects it does not own. */
export interface Situation {
  readonly situationId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly kind: "project" | "relationship" | "topic";
  readonly title: string;
  readonly referencedObjectIds: readonly OpaqueId[];
  readonly updatedAt: IsoTimestamp;
}

/** Current or saved view of what matters in a Situation. */
export interface Frame {
  readonly frameId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly situationId: OpaqueId;
  readonly whatMatters: readonly string[];
  readonly obligations: readonly OpaqueId[];
  readonly uncertainty: readonly string[];
  readonly nextAuthorityPoint: string | null;
  readonly disclosure: DisclosureEnvelope;
}

/** Derived source-linked temporal reconstruction. Not source evidence. */
export interface TraceEntry {
  readonly traceEntryId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly occurredAt: IsoTimestamp;
  readonly label: string;
  readonly authority: "accepted" | "proposed";
  readonly evidence: readonly SourceSpan[];
}

/** Source + proposal + impact + authority + disposition. */
export interface ReviewCase {
  readonly reviewCaseId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly proposalId: OpaqueId;
  readonly proposalState: ProposalState;
  readonly proposalSummary: string;
  readonly evidence: readonly SourceSpan[];
  readonly impactSummary: string;
  readonly openedAt: IsoTimestamp;
}

export type ReviewDisposition = "accept" | "correct" | "reject" | "defer" | "unresolved";

/** Derived attention recommendation. Always explains itself. */
export interface PulseItem {
  readonly pulseItemId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly title: string;
  readonly reason: string;
  readonly consequence: string;
  readonly uncertainty: string | null;
  readonly nextStep: string;
  readonly evidenceRefs: readonly OpaqueId[];
  readonly disclosure: DisclosureEnvelope;
}
