import { isFiniteInteger, isRecord, isString, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredInt,
  requiredArray,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export const REVIEW_SUBJECT_KINDS = [
  "capture_proposal",
  "goodnotes_region",
  "goodnotes_semantic",
  "relationship_memory",
  "entity_proposal",
  "knowledge_assertion",
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

/**
 * KLP R6 section 10.1: what a Knowledge Assertion proposal is *about*. The
 * Python `KnowledgeSubjectKind` tokens; the row says which, never the fact.
 */
export const KNOWLEDGE_SUBJECT_KINDS = [
  "principal",
  "entity",
  "project",
  "managed_document",
  "evidence_ref",
] as const;

/** The Python `KnowledgeReviewRequirement` tokens a review case can carry. */
export const KNOWLEDGE_REVIEW_REQUIREMENTS = ["requires_review", "requires_operator"] as const;

/** The Python `KnowledgeValueType` tokens (shared with `knowledge.assertions.read`). */
export const KNOWLEDGE_VALUE_TYPES = ["text", "datetime"] as const;

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

/**
 * A Knowledge Assertion review case (KLP R6 section 10.1): the common keys, the
 * frozen five, and (KLP-WP-04 fix round 4, Manager ruling on DEV-83) the
 * read-only candidate an authorized reviewer decides on: the typed value,
 * qualifier, effective bounds, the cited evidence ids (`kaevd_`; never excerpt
 * text) and the current single_current holder (both holder fields null when
 * there is none or the caller may not see it). `risk_class`, `proposal_state`
 * and `latest_disposition` reuse the capture vocabularies.
 */
export interface KnowledgeAssertionReviewCase extends ReviewCaseCommon {
  readonly subject_kind: "knowledge_assertion";
  readonly subject_kind_of_fact: (typeof KNOWLEDGE_SUBJECT_KINDS)[number];
  readonly subject_id: string;
  readonly predicate_code: string;
  readonly review_requirement: (typeof KNOWLEDGE_REVIEW_REQUIREMENTS)[number];
  readonly value_type: (typeof KNOWLEDGE_VALUE_TYPES)[number];
  readonly value: string | null;
  readonly qualifier: Readonly<Record<string, unknown>> | null;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly evidence_ref_ids: readonly string[];
  readonly current_assertion_id: string | null;
  readonly current_value: string | null;
}

/**
 * A row whose `subject_kind` this build does not know (KLP-AC-135).
 *
 * It needs only `review_case_id` and a string `subject_kind`, which is kept
 * verbatim in `reported_subject_kind`. It carries nothing else on purpose: it
 * is inert and undecidable — no version, no proposal, nothing a decision could
 * be made against — so a newer backend can list a new kind without taking the
 * whole page down, and this build never guesses at what the row means.
 */
export interface UnknownReviewCase {
  readonly subject_kind: "unknown";
  readonly review_case_id: string;
  readonly reported_subject_kind: string;
}

export type ReviewCase =
  | CaptureProposalReviewCase
  | GoodNotesReviewCase
  | GoodNotesSemanticReviewCase
  | RelationshipMemoryReviewCase
  | EntityProposalReviewCase
  | KnowledgeAssertionReviewCase
  | UnknownReviewCase;

export interface ReviewListResult {
  readonly review_cases: readonly ReviewCase[];
  /**
   * Rows dropped because they lacked even a string `review_case_id` and
   * `subject_kind` (KLP-AC-135). Counted, never silently discarded: the page
   * renders the rest and states how many rows it could not show.
   */
  readonly dropped_row_count: number;
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

function nullableQualifier(value: unknown): DecodeResult<Readonly<Record<string, unknown>> | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isRecord(value)) return fail("a required field was not the expected type");
  return ok(value);
}

/** The cited evidence ids: `kaevd_` identifiers only, never a word of content. */
function evidenceRefIds(value: unknown): DecodeResult<readonly string[]> {
  const rows = requiredArray(value);
  if (!rows.ok) return rows;
  const ids: string[] = [];
  for (const row of rows.value) {
    if (!isString(row) || !row.startsWith("kaevd_")) {
      return fail("a cited evidence id was not a kaevd_ identifier");
    }
    ids.push(row);
  }
  return ok(ids);
}

function decodeKnowledgeCandidate(
  record: Record<string, unknown>,
): DecodeResult<
  Pick<
    KnowledgeAssertionReviewCase,
    | "value_type"
    | "value"
    | "qualifier"
    | "effective_from"
    | "effective_to"
    | "evidence_ref_ids"
    | "current_assertion_id"
    | "current_value"
  >
> {
  const valueType = oneOf(record.value_type, KNOWLEDGE_VALUE_TYPES);
  if (!valueType.ok) return valueType;
  const value = requiredNullableString(record.value);
  if (!value.ok) return value;
  const qualifier = nullableQualifier(record.qualifier);
  if (!qualifier.ok) return qualifier;
  const effectiveFrom = requiredNullableString(record.effective_from);
  if (!effectiveFrom.ok) return effectiveFrom;
  const effectiveTo = requiredNullableString(record.effective_to);
  if (!effectiveTo.ok) return effectiveTo;
  const evidence = evidenceRefIds(record.evidence_ref_ids);
  if (!evidence.ok) return evidence;
  const holder = requiredNullableString(record.current_assertion_id);
  if (!holder.ok) return holder;
  const holderValue = requiredNullableString(record.current_value);
  if (!holderValue.ok) return holderValue;
  if (holder.value !== null && !holder.value.startsWith("kasr_")) {
    return fail("the current holder was not a kasr_ identifier");
  }
  if (holder.value === null && holderValue.value !== null) {
    // Withheld or absent holder: both fields travel null together.
    return fail("a holder value arrived without its holder");
  }
  return ok({
    value_type: valueType.value,
    value: value.value,
    qualifier: qualifier.value,
    effective_from: effectiveFrom.value,
    effective_to: effectiveTo.value,
    evidence_ref_ids: evidence.value,
    current_assertion_id: holder.value,
    current_value: holderValue.value,
  });
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
    "subject_kind_of_fact",
    "subject_id",
    "predicate_code",
    "review_requirement",
    "value_type",
    "value",
    "qualifier",
    "effective_from",
    "effective_to",
    "evidence_ref_ids",
    "current_assertion_id",
    "current_value",
  ]);
  if (!known.ok) return known;
  const kind = oneOf(known.value.subject_kind, REVIEW_SUBJECT_KINDS);
  if (!kind.ok) return kind;
  const common = decodeCommon(known.value);
  if (!common.ok) return common;
  if (kind.value === "knowledge_assertion") {
    const ofFact = oneOf(known.value.subject_kind_of_fact, KNOWLEDGE_SUBJECT_KINDS);
    if (!ofFact.ok) return ofFact;
    const subjectId = requiredString(known.value.subject_id);
    if (!subjectId.ok) return subjectId;
    const predicateCode = requiredString(known.value.predicate_code);
    if (!predicateCode.ok) return predicateCode;
    const requirement = oneOf(known.value.review_requirement, KNOWLEDGE_REVIEW_REQUIREMENTS);
    if (!requirement.ok) return requirement;
    const candidate = decodeKnowledgeCandidate(known.value);
    if (!candidate.ok) return candidate;
    return ok({
      ...common.value,
      subject_kind: "knowledge_assertion",
      subject_kind_of_fact: ofFact.value,
      subject_id: subjectId.value,
      predicate_code: predicateCode.value,
      review_requirement: requirement.value,
      ...candidate.value,
    });
  }
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

function isKnownSubjectKind(value: string): value is ReviewSubjectKind {
  return (REVIEW_SUBJECT_KINDS as readonly string[]).includes(value);
}

/**
 * One row of a tolerant page (KLP R6 section 10.2, KLP-AC-135).
 *
 * * No string `review_case_id` or `subject_kind` -> `"dropped"`: counted by the
 *   caller, the rest of the page still decodes.
 * * A `subject_kind` this build does not know -> an inert `unknown` row.
 * * A known kind is held to its full contract exactly as before: a malformed
 *   capture, GoodNotes, memory, entity or Knowledge row still fails the page,
 *   because a known row that does not match its contract is a broken backend,
 *   not a newer one.
 */
function decodeTolerantRow(input: unknown): DecodeResult<ReviewCase> | "dropped" {
  const head = pick(input, ["review_case_id", "subject_kind"]);
  if (!head.ok) return "dropped";
  const reviewCaseId = head.value.review_case_id;
  const subjectKind = head.value.subject_kind;
  if (typeof reviewCaseId !== "string" || reviewCaseId.length === 0) return "dropped";
  if (typeof subjectKind !== "string" || subjectKind.length === 0) return "dropped";
  if (!isKnownSubjectKind(subjectKind)) {
    return ok({
      subject_kind: "unknown",
      review_case_id: reviewCaseId,
      reported_subject_kind: subjectKind,
    });
  }
  return decodeCase(input);
}

/**
 * `review.list` alone decodes its rows tolerantly; every other capability keeps
 * `decodeItems`, which aborts on the first bad row.
 */
export const decodeReviewList: Decoder<ReviewListResult> = (input) => {
  const known = pick(input, ["review_cases"]);
  if (!known.ok) return known;
  if (known.value.review_cases === undefined) return fail("a required array was omitted");
  const rows = requiredArray(known.value.review_cases);
  if (!rows.ok) return rows;
  const cases: ReviewCase[] = [];
  let dropped = 0;
  for (const item of rows.value) {
    const row = decodeTolerantRow(item);
    if (row === "dropped") {
      dropped += 1;
      continue;
    }
    if (!row.ok) return row;
    cases.push(row.value);
  }
  return ok({ review_cases: cases, dropped_row_count: dropped });
};
