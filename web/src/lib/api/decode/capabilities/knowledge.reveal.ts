import { optional, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredIntGe,
  requiredNullableEnum,
  requiredNullableString,
  requiredSha256,
  requiredString,
} from "./_mutation-helpers";

export const EVIDENCE_STATES = ["evidence", "no_evidence", "unavailable"] as const;
export type EvidenceState = (typeof EVIDENCE_STATES)[number];

export const EVIDENCE_GAPS = [
  "subject_kind_is_outside_the_evidence_model",
  "derivation_has_not_completed_for_every_version",
] as const;
export type EvidenceGap = (typeof EVIDENCE_GAPS)[number];

export const REVEAL_SUBJECT_KINDS = ["capture", "assertion"] as const;
export const OFFSET_BASES = ["unicode_code_point_v1"] as const;
export const SPAN_ROLES = ["direct", "context", "counterevidence"] as const;
export const PROCESSING_STATES = [
  "waiting",
  "running",
  "partial",
  "retryable_failure",
  "permanent_failure",
  "policy_denied",
  "complete",
] as const;
export const PROPOSAL_TYPES = [
  "task",
  "commitment",
  "decision",
  "follow_up",
  "open_question",
  "risk",
  "issue",
] as const;
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
export const ASSERTION_STATES = [
  "proposed",
  "accepted",
  "contradicted",
  "stale",
  "superseded",
  "withdrawn",
  "revalidation_required",
] as const;
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

export interface RevealSpanView {
  readonly span_id: string;
  readonly version_id: string;
  readonly start_offset: number;
  readonly end_offset: number;
  readonly offset_basis: (typeof OFFSET_BASES)[number];
  readonly line_start: number;
  readonly column_start: number;
  readonly line_end: number;
  readonly column_end: number;
  readonly character_count: number;
  readonly quoted_text_sha256: string;
  readonly span_role: (typeof SPAN_ROLES)[number];
  readonly mapping_version: string | null;
}

export interface RevealVersionView {
  readonly version_id: string;
  readonly capture_id: string;
  readonly version_number: number;
  readonly is_current: boolean;
  readonly content_sha256: string;
  readonly recorded_at: string;
  readonly derivation_state: (typeof PROCESSING_STATES)[number] | null;
  readonly derivation_is_complete: boolean;
}

export interface RevealProposalView {
  readonly proposal_id: string;
  readonly version_id: string;
  readonly proposal_type: (typeof PROPOSAL_TYPES)[number];
  readonly state: (typeof PROPOSAL_STATES)[number];
  readonly risk_class: (typeof RISK_CLASSES)[number];
  readonly method: string;
  readonly method_version: string;
  readonly schema_version: string;
  readonly created_at: string;
  readonly span_ids: readonly string[];
  readonly review_case_id: string | null;
  readonly latest_disposition: (typeof DISPOSITIONS)[number] | null;
}

export interface RevealAssertionView {
  readonly assertion_id: string;
  readonly version_id: string;
  readonly proposal_id: string;
  readonly decision_id: string;
  readonly assertion_type: (typeof PROPOSAL_TYPES)[number];
  readonly state: (typeof ASSERTION_STATES)[number];
  readonly accepted_at: string;
  readonly span_ids: readonly string[];
  readonly review_case_id: string | null;
  readonly disposition: (typeof DISPOSITIONS)[number] | null;
  readonly decided_at: string | null;
  readonly receipt_id: string | null;
  readonly policy_version: string | null;
  readonly revalidation_required_at: string | null;
}

export interface KnowledgeRevealResult {
  readonly subject_id: string;
  readonly subject_kind: (typeof REVEAL_SUBJECT_KINDS)[number] | null;
  readonly state: EvidenceState;
  readonly gap: EvidenceGap | null;
  readonly capture_id: string | null;
  readonly versions: readonly RevealVersionView[];
  readonly spans: readonly RevealSpanView[];
  readonly proposed: readonly RevealProposalView[];
  readonly accepted: readonly RevealAssertionView[];
  readonly versions_with_completed_derivation: number;
}

const SPAN_KEYS = [
  "span_id",
  "version_id",
  "start_offset",
  "end_offset",
  "offset_basis",
  "line_start",
  "column_start",
  "line_end",
  "column_end",
  "character_count",
  "quoted_text_sha256",
  "span_role",
  "mapping_version",
] as const;

function decodeSpan(input: unknown): DecodeResult<RevealSpanView> {
  const known = pick(input, SPAN_KEYS);
  if (!known.ok) return known;
  const spanId = requiredString(known.value.span_id);
  if (!spanId.ok) return spanId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const start = requiredIntGe(known.value.start_offset, 0);
  if (!start.ok) return start;
  const end = requiredIntGe(known.value.end_offset, 1);
  if (!end.ok) return end;
  const basis = oneOf(known.value.offset_basis, OFFSET_BASES);
  if (!basis.ok) return basis;
  const lineStart = requiredIntGe(known.value.line_start, 1);
  if (!lineStart.ok) return lineStart;
  const columnStart = requiredIntGe(known.value.column_start, 1);
  if (!columnStart.ok) return columnStart;
  const lineEnd = requiredIntGe(known.value.line_end, 1);
  if (!lineEnd.ok) return lineEnd;
  const columnEnd = requiredIntGe(known.value.column_end, 1);
  if (!columnEnd.ok) return columnEnd;
  const count = requiredIntGe(known.value.character_count, 1);
  if (!count.ok) return count;
  const digest = requiredSha256(known.value.quoted_text_sha256);
  if (!digest.ok) return digest;
  const role = oneOf(known.value.span_role, SPAN_ROLES);
  if (!role.ok) return role;
  const mapping = requiredNullableString(known.value.mapping_version);
  if (!mapping.ok) return mapping;
  return ok({
    span_id: spanId.value,
    version_id: versionId.value,
    start_offset: start.value,
    end_offset: end.value,
    offset_basis: basis.value,
    line_start: lineStart.value,
    column_start: columnStart.value,
    line_end: lineEnd.value,
    column_end: columnEnd.value,
    character_count: count.value,
    quoted_text_sha256: digest.value,
    span_role: role.value,
    mapping_version: mapping.value,
  });
}

const VERSION_KEYS = [
  "version_id",
  "capture_id",
  "version_number",
  "is_current",
  "content_sha256",
  "recorded_at",
  "derivation_state",
  "derivation_is_complete",
] as const;

function decodeVersion(input: unknown): DecodeResult<RevealVersionView> {
  const known = pick(input, VERSION_KEYS);
  if (!known.ok) return known;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const captureId = requiredString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const number = requiredIntGe(known.value.version_number, 1);
  if (!number.ok) return number;
  const isCurrent = requiredBoolean(known.value.is_current);
  if (!isCurrent.ok) return isCurrent;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  const derivation = requiredNullableEnum(known.value.derivation_state, PROCESSING_STATES);
  if (!derivation.ok) return derivation;
  const complete = requiredBoolean(known.value.derivation_is_complete);
  if (!complete.ok) return complete;
  return ok({
    version_id: versionId.value,
    capture_id: captureId.value,
    version_number: number.value,
    is_current: isCurrent.value,
    content_sha256: digest.value,
    recorded_at: recordedAt.value,
    derivation_state: derivation.value,
    derivation_is_complete: complete.value,
  });
}

const PROPOSAL_KEYS = [
  "proposal_id",
  "version_id",
  "proposal_type",
  "state",
  "risk_class",
  "method",
  "method_version",
  "schema_version",
  "created_at",
  "span_ids",
  "review_case_id",
  "latest_disposition",
] as const;

function decodeProposal(input: unknown): DecodeResult<RevealProposalView> {
  const known = pick(input, PROPOSAL_KEYS);
  if (!known.ok) return known;
  const proposalId = requiredString(known.value.proposal_id);
  if (!proposalId.ok) return proposalId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const type = oneOf(known.value.proposal_type, PROPOSAL_TYPES);
  if (!type.ok) return type;
  const state = oneOf(known.value.state, PROPOSAL_STATES);
  if (!state.ok) return state;
  const risk = oneOf(known.value.risk_class, RISK_CLASSES);
  if (!risk.ok) return risk;
  const method = requiredString(known.value.method);
  if (!method.ok) return method;
  const methodVersion = requiredString(known.value.method_version);
  if (!methodVersion.ok) return methodVersion;
  const schemaVersion = requiredString(known.value.schema_version);
  if (!schemaVersion.ok) return schemaVersion;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const spanIds = decodeItems(known.value.span_ids, (item) => requiredString(item));
  if (!spanIds.ok) return spanIds;
  const reviewCaseId = requiredNullableString(known.value.review_case_id);
  if (!reviewCaseId.ok) return reviewCaseId;
  const disposition = requiredNullableEnum(known.value.latest_disposition, DISPOSITIONS);
  if (!disposition.ok) return disposition;
  return ok({
    proposal_id: proposalId.value,
    version_id: versionId.value,
    proposal_type: type.value,
    state: state.value,
    risk_class: risk.value,
    method: method.value,
    method_version: methodVersion.value,
    schema_version: schemaVersion.value,
    created_at: createdAt.value,
    span_ids: spanIds.value,
    review_case_id: reviewCaseId.value,
    latest_disposition: disposition.value,
  });
}

const ASSERTION_KEYS = [
  "assertion_id",
  "version_id",
  "proposal_id",
  "decision_id",
  "assertion_type",
  "state",
  "accepted_at",
  "span_ids",
  "review_case_id",
  "disposition",
  "decided_at",
  "receipt_id",
  "policy_version",
  "revalidation_required_at",
] as const;

function decodeAssertion(input: unknown): DecodeResult<RevealAssertionView> {
  const known = pick(input, ASSERTION_KEYS);
  if (!known.ok) return known;
  const assertionId = requiredString(known.value.assertion_id);
  if (!assertionId.ok) return assertionId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const proposalId = requiredString(known.value.proposal_id);
  if (!proposalId.ok) return proposalId;
  const decisionId = requiredString(known.value.decision_id);
  if (!decisionId.ok) return decisionId;
  const type = oneOf(known.value.assertion_type, PROPOSAL_TYPES);
  if (!type.ok) return type;
  const state = oneOf(known.value.state, ASSERTION_STATES);
  if (!state.ok) return state;
  const acceptedAt = requiredString(known.value.accepted_at);
  if (!acceptedAt.ok) return acceptedAt;
  const spanIds = decodeItems(known.value.span_ids, (item) => requiredString(item));
  if (!spanIds.ok) return spanIds;
  if (spanIds.value.length < 1) return fail("a required array was omitted");
  const reviewCaseId = requiredNullableString(known.value.review_case_id);
  if (!reviewCaseId.ok) return reviewCaseId;
  const disposition = requiredNullableEnum(known.value.disposition, DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const decidedAt = requiredNullableString(known.value.decided_at);
  if (!decidedAt.ok) return decidedAt;
  const receiptId = requiredNullableString(known.value.receipt_id);
  if (!receiptId.ok) return receiptId;
  const policyVersion = requiredNullableString(known.value.policy_version);
  if (!policyVersion.ok) return policyVersion;
  const revalidation = requiredNullableString(known.value.revalidation_required_at);
  if (!revalidation.ok) return revalidation;
  return ok({
    assertion_id: assertionId.value,
    version_id: versionId.value,
    proposal_id: proposalId.value,
    decision_id: decisionId.value,
    assertion_type: type.value,
    state: state.value,
    accepted_at: acceptedAt.value,
    span_ids: spanIds.value,
    review_case_id: reviewCaseId.value,
    disposition: disposition.value,
    decided_at: decidedAt.value,
    receipt_id: receiptId.value,
    policy_version: policyVersion.value,
    revalidation_required_at: revalidation.value,
  });
}

const VIEW_KEYS = [
  "subject_id",
  "subject_kind",
  "state",
  "gap",
  "capture_id",
  "versions",
  "spans",
  "proposed",
  "accepted",
  "versions_with_completed_derivation",
] as const;

export const decodeKnowledgeReveal: Decoder<KnowledgeRevealResult> = (input) => {
  const known = pick(input, VIEW_KEYS);
  if (!known.ok) return known;
  const subjectId = requiredString(known.value.subject_id);
  if (!subjectId.ok) return subjectId;
  const subjectKind = requiredNullableEnum(known.value.subject_kind, REVEAL_SUBJECT_KINDS);
  if (!subjectKind.ok) return subjectKind;
  const state = oneOf(known.value.state, EVIDENCE_STATES);
  if (!state.ok) return state;
  const gap = requiredNullableEnum(known.value.gap, EVIDENCE_GAPS);
  if (!gap.ok) return gap;
  const captureId = requiredNullableString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const versions = decodeItems(known.value.versions, decodeVersion);
  if (!versions.ok) return versions;
  const spans = decodeItems(known.value.spans, decodeSpan);
  if (!spans.ok) return spans;
  const proposed = decodeItems(known.value.proposed, decodeProposal);
  if (!proposed.ok) return proposed;
  const accepted = decodeItems(known.value.accepted, decodeAssertion);
  if (!accepted.ok) return accepted;
  const completed = optional(known.value.versions_with_completed_derivation, (present) =>
    requiredIntGe(present, 0),
  );
  if (!completed.ok) return completed;
  if ((state.value === "unavailable") !== (gap.value !== null)) {
    return fail("an unavailable reveal states its gap and no other reveal does");
  }
  if (state.value === "evidence" && spans.value.length < 1) {
    return fail("a reveal claiming evidence carries at least one span");
  }
  if (
    state.value === "no_evidence" &&
    (spans.value.length > 0 || proposed.value.length > 0 || accepted.value.length > 0)
  ) {
    return fail("a reveal claiming no evidence carries none");
  }
  return ok({
    subject_id: subjectId.value,
    subject_kind: subjectKind.value,
    state: state.value,
    gap: gap.value,
    capture_id: captureId.value,
    versions: versions.value,
    spans: spans.value,
    proposed: proposed.value,
    accepted: accepted.value,
    versions_with_completed_derivation: completed.value ?? 0,
  });
};
