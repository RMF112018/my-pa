import { isFiniteInteger, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredInt,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export const REVIEW_SUBJECT_KINDS = [
  "capture_proposal",
  "goodnotes_region",
  "goodnotes_semantic",
  "relationship_memory",
  "entity_proposal",
] as const;

export type ReviewSubjectKind = (typeof REVIEW_SUBJECT_KINDS)[number];

export const PROPOSAL_STATES = [
  "proposed",
  "needs_review",
  "accepted",
  "corrected_accepted",
  "rejected",
  "deferred",
  "unresolved",
  "superseded",
  "invalidated",
] as const;

export const RISK_CLASSES = ["low", "moderate", "high", "critical"] as const;

export const DISPOSITIONS = [
  "accept",
  "correct_and_accept",
  "reject",
  "defer",
  "mark_unresolved",
  "reprocess",
  "escalate",
  "invalidate",
] as const;

export const CONSEQUENTIAL_CLASSES = [
  "commitment",
  "decision",
  "critical_date",
  "financial_fact",
  "identity_merge",
  "contradiction",
  "sensitive_relationship_conclusion",
] as const;

export const MEMORY_KINDS = [
  "general_note",
  "personal_detail",
  "important_date",
  "interest",
  "communication_preference",
  "working_preference",
  "concern",
  "sensitivity",
  "follow_up_context",
  "user_pinned_context",
] as const;

export const ENTITY_PROPOSAL_KINDS = [
  "create_entity",
  "update_entity",
  "bind_identifier",
  "retire_identifier",
  "supersede_identifier",
  "record_alias",
  "retire_alias",
  "supersede_alias",
  "record_assignment",
  "revise_assignment",
  "end_assignment",
  "record_relationship",
  "revise_relationship",
  "end_relationship",
  "resolve_mention",
  "merge_entities",
  "split_identity",
] as const;

export const ENTITY_PROPOSAL_METHODS = ["deterministic", "rule", "local_model"] as const;

interface ReviewCaseCommon {
  readonly review_case_id: string;
  readonly proposal_id: string;
  readonly proposal_state: (typeof PROPOSAL_STATES)[number];
  readonly risk_class: (typeof RISK_CLASSES)[number];
  readonly opened_at: string;
  readonly review_version: number;
  readonly latest_disposition: (typeof DISPOSITIONS)[number] | null;
}

export interface CaptureProposalReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "capture_proposal";
  readonly capture_id: string;
  readonly version_id: string;
  readonly proposal_type: (typeof CONSEQUENTIAL_CLASSES)[number];
}

export interface GoodNotesReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "goodnotes_region";
  readonly region_id: string;
  readonly page_version_id: string;
  readonly confidence: number;
}

export interface GoodNotesSemanticReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "goodnotes_semantic";
  readonly run_id: string;
  readonly page_version_id: string;
}

export interface RelationshipMemoryReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "relationship_memory";
  readonly subject_entity_id: string;
  readonly proposed_kind: (typeof MEMORY_KINDS)[number];
  readonly accepted_memory_id: string | null;
  readonly accepted_memory_version_id: string | null;
}

export interface EntityProposalReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "entity_proposal";
  readonly subject_entity_id: string;
  readonly proposed_kind: (typeof ENTITY_PROPOSAL_KINDS)[number];
  readonly method: (typeof ENTITY_PROPOSAL_METHODS)[number];
  readonly escalated: boolean;
  readonly accepted_record_id: string | null;
}

export type ReviewCase =
  | CaptureProposalReviewCase
  | GoodNotesReviewCase
  | GoodNotesSemanticReviewCase
  | RelationshipMemoryReviewCase
  | EntityProposalReviewCase;

export interface ReviewListResult {
  readonly review_cases: readonly ReviewCase[];
}

const COMMON_KEYS = [
  "review_case_id",
  "proposal_id",
  "proposal_state",
  "risk_class",
  "opened_at",
  "review_version",
  "latest_disposition",
  "subject_kind",
] as const;

function decodeCommon(record: Record<string, unknown>): DecodeResult<ReviewCaseCommon> {
  const reviewCaseId = requiredString(record.review_case_id);
  if (!reviewCaseId.ok) return reviewCaseId;
  const proposalId = requiredString(record.proposal_id);
  if (!proposalId.ok) return proposalId;
  const proposalState = oneOf(record.proposal_state, PROPOSAL_STATES);
  if (!proposalState.ok) return proposalState;
  const riskClass = oneOf(record.risk_class, RISK_CLASSES);
  if (!riskClass.ok) return riskClass;
  const openedAt = requiredString(record.opened_at);
  if (!openedAt.ok) return openedAt;
  const reviewVersion = requiredInt(record.review_version);
  if (!reviewVersion.ok) return reviewVersion;
  const disposition = requiredNullableString(record.latest_disposition);
  if (!disposition.ok) return disposition;
  let latest: ReviewCaseCommon["latest_disposition"] = null;
  if (disposition.value !== null) {
    const parsed = oneOf(disposition.value, DISPOSITIONS);
    if (!parsed.ok) return parsed;
    latest = parsed.value;
  }
  return ok({
    review_case_id: reviewCaseId.value,
    proposal_id: proposalId.value,
    proposal_state: proposalState.value,
    risk_class: riskClass.value,
    opened_at: openedAt.value,
    review_version: reviewVersion.value,
    latest_disposition: latest,
  });
}

function requiredFiniteNumber(value: unknown): DecodeResult<number> {
  if (value === undefined) return fail("a required field was missing");
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail("a required field was not the expected type");
  }
  if (isFiniteInteger(value) || typeof value === "number") return ok(value);
  return fail("a required field was not the expected type");
}

function decodeCase(input: unknown): DecodeResult<ReviewCase> {
  const known = pick(input, [
    ...COMMON_KEYS,
    "capture_id",
    "version_id",
    "proposal_type",
    "region_id",
    "page_version_id",
    "run_id",
    "confidence",
    "subject_entity_id",
    "proposed_kind",
    "accepted_memory_id",
    "accepted_memory_version_id",
    "method",
    "escalated",
    "accepted_record_id",
  ]);
  if (!known.ok) return known;
  const kind = oneOf(known.value.subject_kind, REVIEW_SUBJECT_KINDS);
  if (!kind.ok) return kind;
  const common = decodeCommon(known.value);
  if (!common.ok) return common;
  if (kind.value === "capture_proposal") {
    const captureId = requiredString(known.value.capture_id);
    if (!captureId.ok) return captureId;
    const versionId = requiredString(known.value.version_id);
    if (!versionId.ok) return versionId;
    const proposalType = oneOf(known.value.proposal_type, CONSEQUENTIAL_CLASSES);
    if (!proposalType.ok) return proposalType;
    return ok({
      ...common.value,
      subject_kind: "capture_proposal",
      capture_id: captureId.value,
      version_id: versionId.value,
      proposal_type: proposalType.value,
    });
  }
  if (kind.value === "goodnotes_region") {
    const regionId = requiredString(known.value.region_id);
    if (!regionId.ok) return regionId;
    const pageVersionId = requiredString(known.value.page_version_id);
    if (!pageVersionId.ok) return pageVersionId;
    const confidence = requiredFiniteNumber(known.value.confidence);
    if (!confidence.ok) return confidence;
    return ok({
      ...common.value,
      subject_kind: "goodnotes_region",
      region_id: regionId.value,
      page_version_id: pageVersionId.value,
      confidence: confidence.value,
    });
  }
  if (kind.value === "goodnotes_semantic") {
    const runId = requiredString(known.value.run_id);
    if (!runId.ok) return runId;
    const pageVersionId = requiredString(known.value.page_version_id);
    if (!pageVersionId.ok) return pageVersionId;
    return ok({
      ...common.value,
      subject_kind: "goodnotes_semantic",
      run_id: runId.value,
      page_version_id: pageVersionId.value,
    });
  }
  if (kind.value === "relationship_memory") {
    const entityId = requiredString(known.value.subject_entity_id);
    if (!entityId.ok) return entityId;
    const proposedKind = oneOf(known.value.proposed_kind, MEMORY_KINDS);
    if (!proposedKind.ok) return proposedKind;
    const acceptedMemoryId = requiredNullableString(known.value.accepted_memory_id);
    if (!acceptedMemoryId.ok) return acceptedMemoryId;
    const acceptedVersion = requiredNullableString(known.value.accepted_memory_version_id);
    if (!acceptedVersion.ok) return acceptedVersion;
    return ok({
      ...common.value,
      subject_kind: "relationship_memory",
      subject_entity_id: entityId.value,
      proposed_kind: proposedKind.value,
      accepted_memory_id: acceptedMemoryId.value,
      accepted_memory_version_id: acceptedVersion.value,
    });
  }
  const entityId = requiredString(known.value.subject_entity_id);
  if (!entityId.ok) return entityId;
  const proposedKind = oneOf(known.value.proposed_kind, ENTITY_PROPOSAL_KINDS);
  if (!proposedKind.ok) return proposedKind;
  const method = oneOf(known.value.method, ENTITY_PROPOSAL_METHODS);
  if (!method.ok) return method;
  const escalated = requiredBoolean(known.value.escalated);
  if (!escalated.ok) return escalated;
  const acceptedRecord = requiredNullableString(known.value.accepted_record_id);
  if (!acceptedRecord.ok) return acceptedRecord;
  return ok({
    ...common.value,
    subject_kind: "entity_proposal",
    subject_entity_id: entityId.value,
    proposed_kind: proposedKind.value,
    method: method.value,
    escalated: escalated.value,
    accepted_record_id: acceptedRecord.value,
  });
}

export const decodeReviewList: Decoder<ReviewListResult> = (input) => {
  const known = pick(input, ["review_cases"]);
  if (!known.ok) return known;
  if (known.value.review_cases === undefined) return fail("a required array was omitted");
  const cases = decodeItems(known.value.review_cases, decodeCase);
  if (!cases.ok) return cases;
  return ok({ review_cases: cases.value });
};
