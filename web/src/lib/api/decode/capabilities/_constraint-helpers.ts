/**
 * Shared guards for the six Constraint read-capability decoders (PC-CM-IMP-WP08).
 *
 * Not a schema framework and not a renamer. Every field below is named twice on
 * purpose — once as the snake_case key `my_pa.application.service._constraint_payload`
 * dumps from the frozen read models, and once as the camelCase member the browser
 * tier reads — because there is no generic recursive converter in this repository
 * and adding one would silently admit fields nobody wrote down.
 *
 * Three rules are load-bearing:
 *
 * 1. **The backend-derived fields are required, never defaulted.** `is_overdue`,
 *    `is_due_soon`, `in_my_court`, `needs_attention`, `version`, the sync state
 *    and every Overview count are decided on the Project's own calendar by
 *    `my_pa.application.constraints`. A payload missing one is a decoding
 *    failure, not a `false`, a `0`, or an omitted key. Nothing here computes a
 *    value the gateway did not send.
 * 2. **`constraintCode` is text.** `"2.01"`, `"2.1"` and `"2.10"` are three
 *    different Codes. It is never parsed, coerced, or compared as a number.
 * 3. **The vocabularies are the backend's own.** `ConstraintSyncStateView` has
 *    exactly four members at this head; the six that need a connector call or a
 *    workbook read are not decodable, so no read can assert one.
 */
import { isFiniteInteger, ok, type DecodeResult } from "../primitives";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredInt,
  requiredNullableInt,
  requiredNullableString,
  requiredRecord,
  requiredString,
} from "./_read-helpers";

/** The seven stored lifecycle states. `reopen` is an operation, not a member. */
export const CONSTRAINT_LIFECYCLE_STATES = [
  "draft",
  "identified",
  "pending",
  "in_progress",
  "on_hold",
  "closed",
  "void",
] as const;
export type ConstraintLifecycleState = (typeof CONSTRAINT_LIFECYCLE_STATES)[number];

/** Data quality of the record. Never a lifecycle state. */
export const CONSTRAINT_RECORD_QUALITIES = ["normal", "legacy_incomplete"] as const;
export type ConstraintRecordQuality = (typeof CONSTRAINT_RECORD_QUALITIES)[number];

/** Why the backend says a record needs attention. Consumed, never inferred. */
export const CONSTRAINT_ATTENTION_REASONS = [
  "legacy_incomplete",
  "open_sync_conflict",
  "data_quality_exception",
] as const;
export type ConstraintAttentionReason = (typeof CONSTRAINT_ATTENTION_REASONS)[number];

/** The fields a normal Publish requires. The browser reads these; it never guesses. */
export const CONSTRAINT_FIELD_KEYS = [
  "project_id",
  "category_id",
  "constraint_code",
  "description",
  "date_identified",
  "due_date",
  "bic",
] as const;
export type ConstraintFieldKey = (typeof CONSTRAINT_FIELD_KEYS)[number];

/**
 * The four synchronisation states a read of persisted rows alone can establish.
 *
 * The frontend vocabulary names ten. The other six each require a connector
 * call, a workbook read or a live run comparison, which is later work and not
 * something a read plane may assert, so they are not decodable here.
 */
export const CONSTRAINT_SYNC_STATES = [
  "never_synced",
  "in_sync",
  "db_export_pending",
  "conflict",
] as const;
export type ConstraintSyncState = (typeof CONSTRAINT_SYNC_STATES)[number];

/** Where a Category sits. A Category is never published or closed. */
export const CONSTRAINT_CATEGORY_STATES = ["active", "inactive", "archived"] as const;
export type ConstraintCategoryState = (typeof CONSTRAINT_CATEGORY_STATES)[number];

/** The three ways a Constraint party can be named. Exactly three. */
export const CONSTRAINT_PARTY_KINDS = ["principal", "entity", "unresolved"] as const;
export type ConstraintPartyKind = (typeof CONSTRAINT_PARTY_KINDS)[number];

/** What this build normalised a Constraint mutation request into. */
export const CONSTRAINT_MUTATION_OPERATIONS = [
  "close",
  "create",
  "publish",
  "reopen",
  "transition",
  "update",
  "void",
] as const;
export type ConstraintMutationOperation = (typeof CONSTRAINT_MUTATION_OPERATIONS)[number];

/** Who or what asked for the mutation. */
export const CONSTRAINT_MUTATION_ACTORS = ["principal", "assistant", "system"] as const;
export type ConstraintMutationActor = (typeof CONSTRAINT_MUTATION_ACTORS)[number];

/** What became of the mutation once the backend finished interpreting it. */
export const CONSTRAINT_MUTATION_OUTCOMES = ["applied", "no_op", "rejected"] as const;
export type ConstraintMutationOutcome = (typeof CONSTRAINT_MUTATION_OUTCOMES)[number];

/** Which end of a Constraint relationship the read subject is. */
export const CONSTRAINT_RELATIONSHIP_DIRECTIONS = ["outgoing", "incoming"] as const;
export type ConstraintRelationshipDirection =
  (typeof CONSTRAINT_RELATIONSHIP_DIRECTIONS)[number];

/**
 * A required key whose value is a JSON number or `null`.
 *
 * `average_open_age_business_days` is `float | None` on the Python side, so the
 * integer guard would reject a legitimate `4.5`. `null` is a member because an
 * average of nothing is not zero, and a decoder that returned `0` there would be
 * publishing a number the backend refused to state.
 */
export function requiredNullableNumber(value: unknown): DecodeResult<number | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail("a required field was not the expected type");
  }
  return ok(value);
}

/** A required non-negative count. A negative total is not a count the backend keeps. */
export function requiredCount(value: unknown): DecodeResult<number> {
  const parsed = requiredInt(value);
  if (!parsed.ok) return parsed;
  if (parsed.value < 0) return fail("a required count was negative");
  return ok(parsed.value);
}

/** A required version. Versions start at 1; `0` and negatives are not versions. */
export function requiredVersion(value: unknown): DecodeResult<number> {
  if (value === undefined) return fail("a required field was missing");
  if (!isFiniteInteger(value) || value < 1) {
    return fail("a required version was missing or not a positive integer");
  }
  return ok(value);
}

/** Every member of a required array is a member of one closed vocabulary. */
export function requiredMembers<T extends string>(
  value: unknown,
  allowed: readonly T[],
): DecodeResult<readonly T[]> {
  return decodeItems(value, (item) => oneOf(item, allowed));
}

/** One BIC or Responsible party, as `PartyRefView` dumps it. */
export interface ConstraintPartyRef {
  readonly kind: ConstraintPartyKind;
  readonly partyRefId: string | null;
  readonly displayLabel: string;
  readonly entityId: string | null;
}

export function decodePartyRef(input: unknown): DecodeResult<ConstraintPartyRef> {
  const known = pick(input, ["kind", "party_ref_id", "display_label", "entity_id"]);
  if (!known.ok) return known;
  const kind = oneOf(known.value.kind, CONSTRAINT_PARTY_KINDS);
  if (!kind.ok) return kind;
  const partyRefId = requiredNullableString(known.value.party_ref_id);
  if (!partyRefId.ok) return partyRefId;
  const displayLabel = requiredString(known.value.display_label);
  if (!displayLabel.ok) return displayLabel;
  const entityId = requiredNullableString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (kind.value === "principal") {
    if (partyRefId.value !== "principal" || entityId.value !== null) {
      return fail("a principal party carried an invalid identity");
    }
  } else if (kind.value === "unresolved") {
    if (partyRefId.value !== null || entityId.value !== null) {
      return fail("an unresolved party carried a stable identity");
    }
  } else if (
    partyRefId.value === null ||
    entityId.value === null ||
    partyRefId.value !== entityId.value
  ) {
    return fail("an entity party carried inconsistent identity fields");
  }
  return ok({
    kind: kind.value,
    partyRefId: partyRefId.value,
    displayLabel: displayLabel.value,
    entityId: entityId.value,
  });
}

export function decodeParties(value: unknown): DecodeResult<readonly ConstraintPartyRef[]> {
  return decodeItems(value, decodePartyRef);
}

/** As much of a Category as a Register row carries. */
export interface ConstraintCategoryRef {
  readonly categoryId: string;
  readonly prefix: string;
  readonly title: string;
}

export function decodeCategoryRef(input: unknown): DecodeResult<ConstraintCategoryRef> {
  const known = pick(input, ["category_id", "prefix", "title"]);
  if (!known.ok) return known;
  const categoryId = requiredString(known.value.category_id);
  if (!categoryId.ok) return categoryId;
  const prefix = requiredString(known.value.prefix);
  if (!prefix.ok) return prefix;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  return ok({ categoryId: categoryId.value, prefix: prefix.value, title: title.value });
}

/** The Category key is required and may be `null`; a missing key is malformed. */
function decodeNullableCategory(
  record: Record<string, unknown>,
): DecodeResult<ConstraintCategoryRef | null> {
  const value = record.category;
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  return decodeCategoryRef(value);
}

/** What is known about one Constraint's synchronisation, from stored rows only. */
export interface ConstraintSyncSummary {
  readonly state: ConstraintSyncState;
  readonly lastVerifiedAt: string | null;
  readonly conflictCount: number;
}

export function decodeSyncSummary(input: unknown): DecodeResult<ConstraintSyncSummary> {
  const known = pick(input, ["state", "last_verified_at", "conflict_count"]);
  if (!known.ok) return known;
  const state = oneOf(known.value.state, CONSTRAINT_SYNC_STATES);
  if (!state.ok) return state;
  const lastVerifiedAt = requiredNullableString(known.value.last_verified_at);
  if (!lastVerifiedAt.ok) return lastVerifiedAt;
  const conflictCount = requiredCount(known.value.conflict_count);
  if (!conflictCount.ok) return conflictCount;
  return ok({
    state: state.value,
    lastVerifiedAt: lastVerifiedAt.value,
    conflictCount: conflictCount.value,
  });
}

/** The Project-level synchronisation roll-up the Overview carries. */
export interface ConstraintSyncHealth {
  readonly state: ConstraintSyncState;
  readonly openConflictCount: number;
  readonly lastVerifiedAt: string | null;
}

export function decodeSyncHealth(input: unknown): DecodeResult<ConstraintSyncHealth> {
  const known = pick(input, ["state", "open_conflict_count", "last_verified_at"]);
  if (!known.ok) return known;
  const state = oneOf(known.value.state, CONSTRAINT_SYNC_STATES);
  if (!state.ok) return state;
  const openConflictCount = requiredCount(known.value.open_conflict_count);
  if (!openConflictCount.ok) return openConflictCount;
  const lastVerifiedAt = requiredNullableString(known.value.last_verified_at);
  if (!lastVerifiedAt.ok) return lastVerifiedAt;
  return ok({
    state: state.value,
    openConflictCount: openConflictCount.value,
    lastVerifiedAt: lastVerifiedAt.value,
  });
}

/** One Register row: the stored fields plus every backend-derived flag. */
export interface ConstraintListEntry {
  readonly constraintId: string;
  readonly projectId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly category: ConstraintCategoryRef | null;
  readonly status: ConstraintLifecycleState;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly bic: readonly ConstraintPartyRef[];
  readonly responsible: readonly ConstraintPartyRef[];
  readonly reference: string | null;
  readonly daysElapsed: number | null;
  readonly version: number;
  readonly updatedAt: string;
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly recordQuality: ConstraintRecordQuality;
  readonly needsAttention: boolean;
  readonly syncState: ConstraintSyncState;
  readonly groupKeys: readonly string[];
}

const LIST_ENTRY_KEYS = [
  "constraint_id",
  "project_id",
  "constraint_code",
  "description",
  "category",
  "status",
  "date_identified",
  "due_date",
  "bic",
  "responsible",
  "reference",
  "days_elapsed",
  "version",
  "updated_at",
  "is_overdue",
  "is_due_soon",
  "in_my_court",
  "record_quality",
  "needs_attention",
  "sync_state",
  "group_keys",
] as const;

export function decodeConstraintListEntry(
  input: unknown,
): DecodeResult<ConstraintListEntry> {
  const known = pick(input, LIST_ENTRY_KEYS);
  if (!known.ok) return known;
  const record = known.value;
  const constraintId = requiredString(record.constraint_id);
  if (!constraintId.ok) return constraintId;
  const projectId = requiredNullableString(record.project_id);
  if (!projectId.ok) return projectId;
  // Text, always. `2.01` and `2.1` are two Codes, and a number cannot hold both.
  const constraintCode = requiredNullableString(record.constraint_code);
  if (!constraintCode.ok) return constraintCode;
  const description = requiredNullableString(record.description);
  if (!description.ok) return description;
  const category = decodeNullableCategory(record);
  if (!category.ok) return category;
  const status = oneOf(record.status, CONSTRAINT_LIFECYCLE_STATES);
  if (!status.ok) return status;
  const dateIdentified = requiredNullableString(record.date_identified);
  if (!dateIdentified.ok) return dateIdentified;
  const dueDate = requiredNullableString(record.due_date);
  if (!dueDate.ok) return dueDate;
  const bic = decodeParties(record.bic);
  if (!bic.ok) return bic;
  const responsible = decodeParties(record.responsible);
  if (!responsible.ok) return responsible;
  const reference = requiredNullableString(record.reference);
  if (!reference.ok) return reference;
  const daysElapsed = requiredNullableInt(record.days_elapsed);
  if (!daysElapsed.ok) return daysElapsed;
  const version = requiredVersion(record.version);
  if (!version.ok) return version;
  const updatedAt = requiredString(record.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const isOverdue = requiredBoolean(record.is_overdue);
  if (!isOverdue.ok) return isOverdue;
  const isDueSoon = requiredBoolean(record.is_due_soon);
  if (!isDueSoon.ok) return isDueSoon;
  const inMyCourt = requiredBoolean(record.in_my_court);
  if (!inMyCourt.ok) return inMyCourt;
  const recordQuality = oneOf(record.record_quality, CONSTRAINT_RECORD_QUALITIES);
  if (!recordQuality.ok) return recordQuality;
  const needsAttention = requiredBoolean(record.needs_attention);
  if (!needsAttention.ok) return needsAttention;
  const syncState = oneOf(record.sync_state, CONSTRAINT_SYNC_STATES);
  if (!syncState.ok) return syncState;
  const groupKeys = decodeItems(record.group_keys, (item) =>
    typeof item === "string" ? ok(item) : fail("a required array was not an array of strings"),
  );
  if (!groupKeys.ok) return groupKeys;
  return ok({
    constraintId: constraintId.value,
    projectId: projectId.value,
    constraintCode: constraintCode.value,
    description: description.value,
    category: category.value,
    status: status.value,
    dateIdentified: dateIdentified.value,
    dueDate: dueDate.value,
    bic: bic.value,
    responsible: responsible.value,
    reference: reference.value,
    daysElapsed: daysElapsed.value,
    version: version.value,
    updatedAt: updatedAt.value,
    isOverdue: isOverdue.value,
    isDueSoon: isDueSoon.value,
    inMyCourt: inMyCourt.value,
    recordQuality: recordQuality.value,
    needsAttention: needsAttention.value,
    syncState: syncState.value,
    groupKeys: groupKeys.value,
  });
}

/** How a CLOSED Constraint was closed. Both members stay null for a legacy row. */
export interface ConstraintCompletion {
  readonly completionDate: string | null;
  readonly closureCommentary: string | null;
}

function decodeCompletion(input: unknown): DecodeResult<ConstraintCompletion> {
  const known = pick(input, ["completion_date", "closure_commentary"]);
  if (!known.ok) return known;
  const completionDate = requiredNullableString(known.value.completion_date);
  if (!completionDate.ok) return completionDate;
  const closureCommentary = requiredNullableString(known.value.closure_commentary);
  if (!closureCommentary.ok) return closureCommentary;
  return ok({
    completionDate: completionDate.value,
    closureCommentary: closureCommentary.value,
  });
}

/** How a VOID Constraint was voided. */
export interface ConstraintVoid {
  readonly voidedDate: string | null;
  readonly voidReason: string | null;
}

function decodeVoid(input: unknown): DecodeResult<ConstraintVoid> {
  const known = pick(input, ["voided_date", "void_reason"]);
  if (!known.ok) return known;
  const voidedDate = requiredNullableString(known.value.voided_date);
  if (!voidedDate.ok) return voidedDate;
  const voidReason = requiredNullableString(known.value.void_reason);
  if (!voidReason.ok) return voidReason;
  return ok({ voidedDate: voidedDate.value, voidReason: voidReason.value });
}

/** One relationship, from the read subject's end. Navigation is by identity. */
export interface ConstraintRelationship {
  readonly relationshipId: string;
  readonly relationshipType: string;
  readonly direction: ConstraintRelationshipDirection;
  readonly relatedConstraintId: string;
  readonly relatedConstraintCode: string | null;
  readonly relatedStatus: ConstraintLifecycleState;
}

export function decodeRelationship(input: unknown): DecodeResult<ConstraintRelationship> {
  const known = pick(input, [
    "relationship_id",
    "relationship_type",
    "direction",
    "related_constraint_id",
    "related_constraint_code",
    "related_status",
  ]);
  if (!known.ok) return known;
  const relationshipId = requiredString(known.value.relationship_id);
  if (!relationshipId.ok) return relationshipId;
  const relationshipType = requiredString(known.value.relationship_type);
  if (!relationshipType.ok) return relationshipType;
  const direction = oneOf(known.value.direction, CONSTRAINT_RELATIONSHIP_DIRECTIONS);
  if (!direction.ok) return direction;
  const relatedConstraintId = requiredString(known.value.related_constraint_id);
  if (!relatedConstraintId.ok) return relatedConstraintId;
  const relatedConstraintCode = requiredNullableString(known.value.related_constraint_code);
  if (!relatedConstraintCode.ok) return relatedConstraintCode;
  const relatedStatus = oneOf(known.value.related_status, CONSTRAINT_LIFECYCLE_STATES);
  if (!relatedStatus.ok) return relatedStatus;
  return ok({
    relationshipId: relationshipId.value,
    relationshipType: relationshipType.value,
    direction: direction.value,
    relatedConstraintId: relatedConstraintId.value,
    relatedConstraintCode: relatedConstraintCode.value,
    relatedStatus: relatedStatus.value,
  });
}

/** One cited piece of evidence, as a validated reference and never as content. */
export interface ConstraintEvidenceLink {
  readonly evidenceLinkId: string;
  readonly evidenceKind: string;
  readonly evidenceRef: string;
  readonly role: string;
}

export function decodeEvidenceLink(input: unknown): DecodeResult<ConstraintEvidenceLink> {
  const known = pick(input, ["evidence_link_id", "evidence_kind", "evidence_ref", "role"]);
  if (!known.ok) return known;
  const evidenceLinkId = requiredString(known.value.evidence_link_id);
  if (!evidenceLinkId.ok) return evidenceLinkId;
  const evidenceKind = requiredString(known.value.evidence_kind);
  if (!evidenceKind.ok) return evidenceKind;
  const evidenceRef = requiredString(known.value.evidence_ref);
  if (!evidenceRef.ok) return evidenceRef;
  const role = requiredString(known.value.role);
  if (!role.ok) return role;
  return ok({
    evidenceLinkId: evidenceLinkId.value,
    evidenceKind: evidenceKind.value,
    evidenceRef: evidenceRef.value,
    role: role.value,
  });
}

/** One Constraint in full: every Register field plus what only a detail read shows. */
export interface ConstraintView {
  readonly constraintId: string;
  readonly projectId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly category: ConstraintCategoryRef | null;
  readonly status: ConstraintLifecycleState;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly bic: readonly ConstraintPartyRef[];
  readonly responsible: readonly ConstraintPartyRef[];
  readonly reference: string | null;
  readonly daysElapsed: number | null;
  readonly version: number;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly recordQuality: ConstraintRecordQuality;
  readonly needsAttention: boolean;
  readonly needsAttentionReasons: readonly ConstraintAttentionReason[];
  readonly missingFields: readonly ConstraintFieldKey[];
  readonly isPublished: boolean;
  readonly publishedAt: string | null;
  readonly currentUpdate: string | null;
  readonly completion: ConstraintCompletion | null;
  readonly void: ConstraintVoid | null;
  readonly sync: ConstraintSyncSummary;
  readonly relationships: readonly ConstraintRelationship[];
  readonly evidenceLinks: readonly ConstraintEvidenceLink[];
}

const VIEW_KEYS = [
  "constraint_id",
  "project_id",
  "constraint_code",
  "description",
  "category",
  "status",
  "date_identified",
  "due_date",
  "bic",
  "responsible",
  "reference",
  "days_elapsed",
  "version",
  "created_at",
  "updated_at",
  "is_overdue",
  "is_due_soon",
  "in_my_court",
  "record_quality",
  "needs_attention",
  "needs_attention_reasons",
  "missing_fields",
  "is_published",
  "published_at",
  "current_update",
  "completion",
  "void",
  "sync",
  "relationships",
  "evidence_links",
] as const;

export function decodeConstraintView(input: unknown): DecodeResult<ConstraintView> {
  const known = pick(input, VIEW_KEYS);
  if (!known.ok) return known;
  const record = known.value;
  const constraintId = requiredString(record.constraint_id);
  if (!constraintId.ok) return constraintId;
  const projectId = requiredNullableString(record.project_id);
  if (!projectId.ok) return projectId;
  const constraintCode = requiredNullableString(record.constraint_code);
  if (!constraintCode.ok) return constraintCode;
  const description = requiredNullableString(record.description);
  if (!description.ok) return description;
  const category = decodeNullableCategory(record);
  if (!category.ok) return category;
  const status = oneOf(record.status, CONSTRAINT_LIFECYCLE_STATES);
  if (!status.ok) return status;
  const dateIdentified = requiredNullableString(record.date_identified);
  if (!dateIdentified.ok) return dateIdentified;
  const dueDate = requiredNullableString(record.due_date);
  if (!dueDate.ok) return dueDate;
  const bic = decodeParties(record.bic);
  if (!bic.ok) return bic;
  const responsible = decodeParties(record.responsible);
  if (!responsible.ok) return responsible;
  const reference = requiredNullableString(record.reference);
  if (!reference.ok) return reference;
  const daysElapsed = requiredNullableInt(record.days_elapsed);
  if (!daysElapsed.ok) return daysElapsed;
  const version = requiredVersion(record.version);
  if (!version.ok) return version;
  const createdAt = requiredString(record.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(record.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const isOverdue = requiredBoolean(record.is_overdue);
  if (!isOverdue.ok) return isOverdue;
  const isDueSoon = requiredBoolean(record.is_due_soon);
  if (!isDueSoon.ok) return isDueSoon;
  const inMyCourt = requiredBoolean(record.in_my_court);
  if (!inMyCourt.ok) return inMyCourt;
  const recordQuality = oneOf(record.record_quality, CONSTRAINT_RECORD_QUALITIES);
  if (!recordQuality.ok) return recordQuality;
  const needsAttention = requiredBoolean(record.needs_attention);
  if (!needsAttention.ok) return needsAttention;
  const needsAttentionReasons = requiredMembers(
    record.needs_attention_reasons,
    CONSTRAINT_ATTENTION_REASONS,
  );
  if (!needsAttentionReasons.ok) return needsAttentionReasons;
  const missingFields = requiredMembers(record.missing_fields, CONSTRAINT_FIELD_KEYS);
  if (!missingFields.ok) return missingFields;
  const isPublished = requiredBoolean(record.is_published);
  if (!isPublished.ok) return isPublished;
  const publishedAt = requiredNullableString(record.published_at);
  if (!publishedAt.ok) return publishedAt;
  const currentUpdate = requiredNullableString(record.current_update);
  if (!currentUpdate.ok) return currentUpdate;
  if (record.completion === undefined) return fail("a required field was missing");
  const completion =
    record.completion === null ? ok(null) : decodeCompletion(record.completion);
  if (!completion.ok) return completion;
  if (record.void === undefined) return fail("a required field was missing");
  const voided = record.void === null ? ok(null) : decodeVoid(record.void);
  if (!voided.ok) return voided;
  const sync = decodeSyncSummary(record.sync);
  if (!sync.ok) return sync;
  const relationships = decodeItems(record.relationships, decodeRelationship);
  if (!relationships.ok) return relationships;
  const evidenceLinks = decodeItems(record.evidence_links, decodeEvidenceLink);
  if (!evidenceLinks.ok) return evidenceLinks;
  return ok({
    constraintId: constraintId.value,
    projectId: projectId.value,
    constraintCode: constraintCode.value,
    description: description.value,
    category: category.value,
    status: status.value,
    dateIdentified: dateIdentified.value,
    dueDate: dueDate.value,
    bic: bic.value,
    responsible: responsible.value,
    reference: reference.value,
    daysElapsed: daysElapsed.value,
    version: version.value,
    createdAt: createdAt.value,
    updatedAt: updatedAt.value,
    isOverdue: isOverdue.value,
    isDueSoon: isDueSoon.value,
    inMyCourt: inMyCourt.value,
    recordQuality: recordQuality.value,
    needsAttention: needsAttention.value,
    needsAttentionReasons: needsAttentionReasons.value,
    missingFields: missingFields.value,
    isPublished: isPublished.value,
    publishedAt: publishedAt.value,
    currentUpdate: currentUpdate.value,
    completion: completion.value,
    void: voided.value,
    sync: sync.value,
    relationships: relationships.value,
    evidenceLinks: evidenceLinks.value,
  });
}

/** One mutation receipt, projected to what a reader may see. */
export interface ConstraintHistoryEntry {
  readonly historyId: string;
  readonly operation: ConstraintMutationOperation;
  readonly actor: ConstraintMutationActor;
  readonly outcome: ConstraintMutationOutcome;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly revisionId: string | null;
  readonly safeFailureReason: string | null;
}

export function decodeConstraintHistoryEntry(
  input: unknown,
): DecodeResult<ConstraintHistoryEntry> {
  const known = pick(input, [
    "history_id",
    "operation",
    "actor",
    "outcome",
    "before_version",
    "after_version",
    "occurred_at",
    "revision_id",
    "safe_failure_reason",
  ]);
  if (!known.ok) return known;
  const historyId = requiredString(known.value.history_id);
  if (!historyId.ok) return historyId;
  const operation = oneOf(known.value.operation, CONSTRAINT_MUTATION_OPERATIONS);
  if (!operation.ok) return operation;
  const actor = oneOf(known.value.actor, CONSTRAINT_MUTATION_ACTORS);
  if (!actor.ok) return actor;
  const outcome = oneOf(known.value.outcome, CONSTRAINT_MUTATION_OUTCOMES);
  if (!outcome.ok) return outcome;
  // `before_version` is `0` for a `create`, so this is the one version field
  // that is a count rather than a version.
  const beforeVersion = requiredCount(known.value.before_version);
  if (!beforeVersion.ok) return beforeVersion;
  const afterVersion = requiredCount(known.value.after_version);
  if (!afterVersion.ok) return afterVersion;
  const occurredAt = requiredString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const revisionId = requiredNullableString(known.value.revision_id);
  if (!revisionId.ok) return revisionId;
  const safeFailureReason = requiredNullableString(known.value.safe_failure_reason);
  if (!safeFailureReason.ok) return safeFailureReason;
  return ok({
    historyId: historyId.value,
    operation: operation.value,
    actor: actor.value,
    outcome: outcome.value,
    beforeVersion: beforeVersion.value,
    afterVersion: afterVersion.value,
    occurredAt: occurredAt.value,
    revisionId: revisionId.value,
    safeFailureReason: safeFailureReason.value,
  });
}

/** One Constraint Category, with the flags a safe mutation UX will later need. */
export interface ConstraintCategory {
  readonly categoryId: string;
  readonly projectId: string;
  readonly prefix: string;
  readonly title: string;
  readonly description: string | null;
  readonly displayOrder: number;
  readonly state: ConstraintCategoryState;
  readonly nextSequence: number;
  readonly issuedCount: number;
  readonly version: number;
  readonly prefixLocked: boolean;
}

export function decodeConstraintCategory(
  input: unknown,
): DecodeResult<ConstraintCategory> {
  const known = pick(input, [
    "category_id",
    "project_id",
    "prefix",
    "title",
    "description",
    "display_order",
    "state",
    "next_sequence",
    "issued_count",
    "version",
    "prefix_locked",
  ]);
  if (!known.ok) return known;
  const categoryId = requiredString(known.value.category_id);
  if (!categoryId.ok) return categoryId;
  const projectId = requiredString(known.value.project_id);
  if (!projectId.ok) return projectId;
  const prefix = requiredString(known.value.prefix);
  if (!prefix.ok) return prefix;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const displayOrder = requiredCount(known.value.display_order);
  if (!displayOrder.ok) return displayOrder;
  const state = oneOf(known.value.state, CONSTRAINT_CATEGORY_STATES);
  if (!state.ok) return state;
  const nextSequence = requiredCount(known.value.next_sequence);
  if (!nextSequence.ok) return nextSequence;
  const issuedCount = requiredCount(known.value.issued_count);
  if (!issuedCount.ok) return issuedCount;
  const version = requiredVersion(known.value.version);
  if (!version.ok) return version;
  // Backend-published. Never inferred from whether a Register row exists.
  const prefixLocked = requiredBoolean(known.value.prefix_locked);
  if (!prefixLocked.ok) return prefixLocked;
  return ok({
    categoryId: categoryId.value,
    projectId: projectId.value,
    prefix: prefix.value,
    title: title.value,
    description: description.value,
    displayOrder: displayOrder.value,
    state: state.value,
    nextSequence: nextSequence.value,
    issuedCount: issuedCount.value,
    version: version.value,
    prefixLocked: prefixLocked.value,
  });
}

/**
 * The Project's Constraint position at one instant, on the Project's calendar.
 *
 * The two forbidden aliases are refused by *presence*, not merely by absence of
 * the canonical key: a payload that carries `average_open_age` alongside the
 * real field would otherwise decode, and the alias is the shape `CM-FE-AC-019`
 * exists to keep out of this tier.
 */
export interface ConstraintOverview {
  readonly projectId: string;
  readonly projectToday: string;
  readonly projectTimezone: string;
  readonly totalOpen: number;
  readonly overdue: number;
  readonly dueSoon: number;
  readonly dueSoonThrough: string;
  readonly averageOpenAgeBusinessDays: number | null;
  readonly inMyCourt: number;
  readonly onHold: number;
  readonly recentlyChanged: number;
  readonly recentlyClosed: number;
  readonly draft: number;
  readonly needsAttention: number;
  readonly syncHealth: ConstraintSyncHealth;
  readonly asOf: string;
}

/** Neither spelling of either alias is an accepted member. */
export const FORBIDDEN_OVERVIEW_ALIASES = [
  "average_open_age",
  "averageOpenAge",
  "synchronization_health",
  "synchronizationHealth",
] as const;

const OVERVIEW_KEYS = [
  "project_id",
  "project_today",
  "project_timezone",
  "total_open",
  "overdue",
  "due_soon",
  "due_soon_through",
  "average_open_age_business_days",
  "in_my_court",
  "on_hold",
  "recently_changed",
  "recently_closed",
  "draft",
  "needs_attention",
  "sync_health",
  "as_of",
] as const;

export function decodeConstraintOverview(
  input: unknown,
): DecodeResult<ConstraintOverview> {
  const raw = requiredRecord(input);
  if (!raw.ok) return raw;
  for (const alias of FORBIDDEN_OVERVIEW_ALIASES) {
    if (Object.prototype.hasOwnProperty.call(raw.value, alias)) {
      return fail("the overview used a name this tier does not accept");
    }
  }
  const record = pick(raw.value, OVERVIEW_KEYS);
  if (!record.ok) return record;
  const known = record.value;
  const projectId = requiredString(known.project_id);
  if (!projectId.ok) return projectId;
  const projectToday = requiredString(known.project_today);
  if (!projectToday.ok) return projectToday;
  const projectTimezone = requiredString(known.project_timezone);
  if (!projectTimezone.ok) return projectTimezone;
  const totalOpen = requiredCount(known.total_open);
  if (!totalOpen.ok) return totalOpen;
  const overdue = requiredCount(known.overdue);
  if (!overdue.ok) return overdue;
  const dueSoon = requiredCount(known.due_soon);
  if (!dueSoon.ok) return dueSoon;
  const dueSoonThrough = requiredString(known.due_soon_through);
  if (!dueSoonThrough.ok) return dueSoonThrough;
  const averageOpenAgeBusinessDays = requiredNullableNumber(
    known.average_open_age_business_days,
  );
  if (!averageOpenAgeBusinessDays.ok) return averageOpenAgeBusinessDays;
  const inMyCourt = requiredCount(known.in_my_court);
  if (!inMyCourt.ok) return inMyCourt;
  const onHold = requiredCount(known.on_hold);
  if (!onHold.ok) return onHold;
  const recentlyChanged = requiredCount(known.recently_changed);
  if (!recentlyChanged.ok) return recentlyChanged;
  const recentlyClosed = requiredCount(known.recently_closed);
  if (!recentlyClosed.ok) return recentlyClosed;
  const draft = requiredCount(known.draft);
  if (!draft.ok) return draft;
  const needsAttention = requiredCount(known.needs_attention);
  if (!needsAttention.ok) return needsAttention;
  const syncHealth = decodeSyncHealth(known.sync_health);
  if (!syncHealth.ok) return syncHealth;
  const asOf = requiredString(known.as_of);
  if (!asOf.ok) return asOf;
  return ok({
    projectId: projectId.value,
    projectToday: projectToday.value,
    projectTimezone: projectTimezone.value,
    totalOpen: totalOpen.value,
    overdue: overdue.value,
    dueSoon: dueSoon.value,
    dueSoonThrough: dueSoonThrough.value,
    averageOpenAgeBusinessDays: averageOpenAgeBusinessDays.value,
    inMyCourt: inMyCourt.value,
    onHold: onHold.value,
    recentlyChanged: recentlyChanged.value,
    recentlyClosed: recentlyClosed.value,
    draft: draft.value,
    needsAttention: needsAttention.value,
    syncHealth: syncHealth.value,
    asOf: asOf.value,
  });
}

/**
 * One Register page as the two list capabilities return it.
 *
 * Truncation and the next cursor are the gateway *disclosure*'s, not the
 * result's, so nothing here reconstructs them. The rows are the whole payload.
 */
export function decodeConstraintPage(
  input: unknown,
): DecodeResult<{ readonly constraints: readonly ConstraintListEntry[] }> {
  const known = pick(input, ["constraints"]);
  if (!known.ok) return known;
  if (known.value.constraints === undefined) return fail("a required array was omitted");
  const constraints = decodeItems(known.value.constraints, decodeConstraintListEntry);
  if (!constraints.ok) return constraints;
  return ok({ constraints: constraints.value });
}
