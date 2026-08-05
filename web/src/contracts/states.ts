/**
 * Canonical state vocabularies — parity with the v4.0 domain model
 * (`09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, "State patterns").
 *
 * Closed sets. Adding a member is a contract change reviewed against the
 * Python vocabulary, never a local convenience.
 */

export type SourceState =
  | "active"
  | "archived"
  | "superseded"
  | "unavailable"
  | "denied"
  | "quarantined";

export type ProposalState =
  | "proposed"
  | "needs_review"
  | "accepted"
  | "corrected_accepted"
  | "rejected"
  | "deferred"
  | "unresolved"
  | "superseded"
  | "invalidated";

export type AssertionState =
  | "proposed"
  | "accepted"
  | "contradicted"
  | "stale"
  | "superseded"
  | "withdrawn"
  | "revalidation_required";

export type IdentityResolutionState =
  | "resolved"
  | "candidate"
  | "unresolved"
  | "merge_proposed"
  | "split_proposed"
  | "superseded";

export type CommitmentState =
  | "proposed"
  | "accepted"
  | "active"
  | "at_risk"
  | "fulfilled"
  | "broken"
  | "withdrawn"
  | "superseded"
  | "unknown";

export type ProcessingState =
  | "waiting"
  | "running"
  | "partial"
  | "retryable_failure"
  | "permanent_failure"
  | "policy_denied"
  | "complete";
