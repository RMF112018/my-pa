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

/**
 * One review case exactly as `review.list` emits it, and no more.
 *
 * Separate from `ReviewCase` above rather than merged with it, because the two
 * carry genuinely different things. `ReviewCase` is the workbench's view and has
 * `proposalSummary`, `evidence` and `impactSummary`; the backend listing has none
 * of the three — it carries no capture or normalized-value content at all, by
 * design, since a listing is not a read. Filling those fields with empty strings
 * and empty arrays would report "no evidence" where the truth is "not returned
 * by this capability", so the shapes stay distinct and `/api/review` says which
 * one it is returning.
 */
export interface BackendReviewCase {
  readonly reviewCaseId: OpaqueId;
  readonly proposalId: OpaqueId;
  readonly captureId: OpaqueId;
  readonly versionId: OpaqueId;
  readonly proposalType: string;
  readonly proposalState: string;
  readonly riskClass: string;
  readonly openedAt: IsoTimestamp;
  /** The version a `review.decide` must state to win the optimistic-concurrency check. */
  readonly reviewVersion: number;
  readonly latestDisposition: string | null;
}

/**
 * The immutable receipt a real disposition produced, as `review.decide` emits it.
 *
 * `assertionId` and `receiptId` are null for a disposition that promotes nothing
 * — a reject, defer or mark-unresolved records the decision without minting an
 * assertion — and that null is the honest report of what happened rather than a
 * missing field.
 */
export interface ReviewDecisionReceipt {
  readonly reviewCaseId: OpaqueId;
  readonly decisionId: OpaqueId;
  readonly reviewVersion: number;
  readonly disposition: string;
  readonly proposalState: string;
  readonly assertionId: OpaqueId | null;
  readonly receiptId: OpaqueId | null;
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

/**
 * The Pulse as the backend derives it, which is a different thing from the
 * `PulseItem` above and therefore a different type.
 *
 * `PulseItem` is the fixture shape: a title, a reason, a consequence, a next
 * step. A derived item has no title at all — nothing wrote one — and carries
 * three things the fixture shape has no field for and which are the whole point
 * of the derivation: a closed `reasonCode` naming *why now*, the `basisRefs` a
 * reader can open to check that reason, and a bounded `priority` that is an
 * evidentiary urgency rank rather than a position in a stream. Merging the two
 * would mean inventing a title and dropping the basis, which is exactly the
 * flattening that turns a Pulse back into a feed.
 *
 * `itemRef` names the accepted record the item is about; `generatedAt` is the
 * moment of the read and is identical across every item in one answer, so it
 * cannot be used to order them.
 */
export interface BackendPulseItem {
  readonly pulseId: OpaqueId;
  readonly itemType: string;
  readonly itemRef: OpaqueId;
  readonly reasonCode: string;
  readonly reason: string;
  readonly basisRefs: readonly OpaqueId[];
  readonly consequence: string | null;
  readonly nextStep: string | null;
  readonly priority: number;
  readonly generatedAt: IsoTimestamp;
}

/**
 * A Situation as `continuity.situations` returns it.
 *
 * Separate from `Situation` above for the reason `BackendReviewCase` is
 * separate from `ReviewCase`: the fixture shape carries a `disclosure` on every
 * row and a `principalId`, and the backend listing carries neither — the
 * disclosure belongs to the answer rather than to each row, and the Principal is
 * the session's and is never echoed back.
 */
export interface BackendSituation {
  readonly situationId: OpaqueId;
  readonly title: string;
  readonly state: SituationState;
  readonly description: string | null;
  readonly objectRefs: readonly OpaqueId[];
  readonly openedAt: IsoTimestamp;
  readonly closedAt: IsoTimestamp | null;
  readonly outcome: string | null;
}

/** A Project as `continuity.projects` returns it. Same distinction as above. */
export interface BackendProject {
  readonly projectId: OpaqueId;
  readonly name: string;
  readonly state: ProjectState;
  readonly description: string | null;
  readonly participants: readonly string[];
  readonly openedAt: IsoTimestamp;
  readonly closedAt: IsoTimestamp | null;
}
