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
  readonly description: string | null;
  readonly state: SituationState;
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

/** Situation lifecycle — parity with the Python `SituationState`. */
export type SituationState = "open" | "active" | "suspended" | "closed";

/** Project lifecycle — parity with the Python `ProjectState`. */
export type ProjectState = "active" | "on_hold" | "closed";

/** Durable work context with participants, situations, and a timeline. */
export interface Project {
  readonly projectId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly name: string;
  readonly description: string | null;
  readonly state: ProjectState;
  readonly participants: readonly string[];
  readonly openedAt: IsoTimestamp;
  readonly disclosure: DisclosureEnvelope;
}

/** Kinds of association events on a relationship timeline. */
export type RelationshipEventType =
  | "interaction"
  | "meeting"
  | "commitment"
  | "observation"
  | "affiliation_change"
  | "project_link";

/**
 * A time/context-aware event on a person's relationship timeline. The
 * `accepted` flag is the visibility gate: Today/Pulse and the timeline read
 * only accepted events. Proposed (not-accepted) events never surface as fact.
 */
export interface RelationshipEvent {
  readonly eventId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly personId: OpaqueId;
  readonly eventType: RelationshipEventType;
  readonly occurredAt: IsoTimestamp;
  readonly context: string | null;
  readonly accepted: boolean;
  readonly sourceRef: OpaqueId | null;
}

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
