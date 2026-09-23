/**
 * Safe projections and invariants for the 13 Constraint authoring decoders (R01-WP09).
 *
 * **The raw mutation wire is not the read projection, and it is not safe.** The
 * handlers serialise the domain dataclasses with `_constraint_payload`, which is
 * `asdict` and drops nothing, so a Constraint record carries the owning
 * Principal's identifier and a receipt carries that identifier plus
 * `idempotency_key`, `request_digest`, `client_context`, `correlation_id` and
 * `recorded_at`. Every projection below
 * is therefore built from an allowlist: `pick` copies only the named keys, the
 * output object is written out member by member, and a key the gateway adds
 * later is dropped rather than passed through. None of those six names appears
 * in any output type here, and `constraints.authoring.decode.test.ts` asserts
 * that none of them survives serialisation.
 *
 * **The disposition decides what the versions must say** (artifact 17 §9):
 *
 * - `applied`: the receipt names this record, its outcome is `applied`, it
 *   advanced the version by exactly one (`_mutate` writes `before + 1`), and the
 *   record is the version the receipt produced.
 * - `no_op`: the receipt names this record, its outcome is `no_op`, it moved no
 *   version, and the record is that version.
 * - `replayed`: the receipt names this record and is internally consistent, but
 *   the record is **not** required to be the receipt's version. A replay answers
 *   with the *current* record beside the *original* keyed receipt, so a record
 *   that moved on since is the normal case, not a contract failure. It may never
 *   be older than the receipt, because versions only grow.
 *
 * Unknown dispositions, outcomes, operations, actors and states are refused, not
 * mapped: the vocabularies below are transcribed from the Python enums at this
 * head (`ConstraintMutationDisposition`, `ConstraintMutationOutcome`,
 * `ConstraintMutationOperation`, `ConstraintCategoryMutationOperation`,
 * `ConstraintMutationActor`, `ConstraintOrigin`, …). Every refusal is an
 * `upstream_contract_invalid` result; `invokeGateway` maps it to a 503.
 */
import { ok, type DecodeResult } from "../primitives";
import {
  CONSTRAINT_CATEGORY_STATES,
  CONSTRAINT_LIFECYCLE_STATES,
  CONSTRAINT_MUTATION_ACTORS,
  CONSTRAINT_MUTATION_OPERATIONS,
  CONSTRAINT_MUTATION_OUTCOMES,
  CONSTRAINT_PARTY_KINDS,
  CONSTRAINT_RECORD_QUALITIES,
  requiredCount,
  requiredVersion,
  type ConstraintCategoryState,
  type ConstraintLifecycleState,
  type ConstraintMutationActor,
  type ConstraintMutationOperation,
  type ConstraintMutationOutcome,
  type ConstraintPartyKind,
  type ConstraintRecordQuality,
} from "./_constraint-helpers";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

/** `ConstraintMutationDisposition`: what the caller is told became of the request. */
export const CONSTRAINT_MUTATION_DISPOSITIONS = ["applied", "no_op", "replayed"] as const;
export type ConstraintMutationDisposition = (typeof CONSTRAINT_MUTATION_DISPOSITIONS)[number];

/**
 * The two dispositions a composite answer can carry. Close + Follow-up and a
 * reorder return `applied` or `replayed` and never `no_op`: neither has a
 * "nothing changed" branch (`close_with_follow_up` and `reorder_categories`
 * construct only those two), so `no_op` there is refused as a shape the
 * capability does not emit.
 */
export const COMPOSITE_DISPOSITIONS = ["applied", "replayed"] as const;
export type CompositeDisposition = (typeof COMPOSITE_DISPOSITIONS)[number];

/** `ConstraintOrigin`: where the record came from. Immutable once set. */
export const CONSTRAINT_ORIGINS = ["product", "legacy_workbook_import"] as const;
export type ConstraintOrigin = (typeof CONSTRAINT_ORIGINS)[number];

/** `ConstraintCategoryMutationOperation`. A Category is never published or closed. */
export const CONSTRAINT_CATEGORY_OPERATIONS = ["archive", "create", "update"] as const;
export type ConstraintCategoryOperation = (typeof CONSTRAINT_CATEGORY_OPERATIONS)[number];

// `validate_identifier`: a known prefix, `_`, then 8-64 ASCII alphanumerics.
const ID_SUFFIX = "[A-Za-z0-9]{8,64}";

function identifierPattern(prefix: string): RegExp {
  return new RegExp(`^${prefix}_${ID_SUFFIX}$`);
}

const CONSTRAINT_ID = identifierPattern("cst");
const PROJECT_ID = identifierPattern("prj");
const CATEGORY_ID = identifierPattern("ccat");
const ENTITY_ID = identifierPattern("ent");
const CONSTRAINT_HISTORY_ID = identifierPattern("chst");
const CATEGORY_HISTORY_ID = identifierPattern("cchst");
const REVISION_ID = identifierPattern("crev");
const RELATIONSHIP_ID = identifierPattern("crel");

/** `date.isoformat()`: a calendar date and nothing else. Never re-derived here. */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
/** `datetime.isoformat()` of a UTC-normalised instant: a date, `T`, a time. */
const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

function requiredMatching(value: unknown, pattern: RegExp): DecodeResult<string> {
  const text = requiredString(value);
  if (!text.ok) return text;
  if (!pattern.test(text.value)) return fail("a required field was not the expected shape");
  return text;
}

function nullableMatching(value: unknown, pattern: RegExp): DecodeResult<string | null> {
  const text = requiredNullableString(value);
  if (!text.ok || text.value === null) return text;
  if (!pattern.test(text.value)) return fail("a required field was not the expected shape");
  return text;
}

/** A canonical `crel_` relationship identifier. */
export function requiredRelationshipId(value: unknown): DecodeResult<string> {
  return requiredMatching(value, RELATIONSHIP_ID);
}

/**
 * One BIC or Responsible party as the *domain* `PartyRef` dumps it.
 *
 * Not the read plane's `PartyRefView` (`party_ref_id`/`display_label`): the
 * mutation wire is `asdict(PartyRef)`, which is `{kind, entity_id, label}`.
 * The pairing rules are `PartyRef.__post_init__`'s, restated so a record the
 * domain could not have built is refused: `entity` needs an `ent_` identity,
 * the other two carry none; `unresolved` needs non-blank wording; `principal`
 * carries no label of its own; any label present is non-blank.
 */
export interface ConstraintMutationPartyRef {
  readonly kind: ConstraintPartyKind;
  readonly entityId: string | null;
  readonly label: string | null;
}

export function decodeMutationPartyRef(input: unknown): DecodeResult<ConstraintMutationPartyRef> {
  const known = pick(input, ["kind", "entity_id", "label"]);
  if (!known.ok) return known;
  const kind = oneOf(known.value.kind, CONSTRAINT_PARTY_KINDS);
  if (!kind.ok) return kind;
  const entityId = nullableMatching(known.value.entity_id, ENTITY_ID);
  if (!entityId.ok) return entityId;
  const label = requiredNullableString(known.value.label);
  if (!label.ok) return label;
  if ((kind.value === "entity") !== (entityId.value !== null)) {
    return fail("a party carried an identity its kind does not allow");
  }
  if (label.value !== null && label.value.trim() === "") {
    return fail("a party label was blank");
  }
  if (kind.value === "unresolved" && label.value === null) {
    return fail("an unresolved party carried no wording");
  }
  if (kind.value === "principal" && label.value !== null) {
    return fail("a principal party carried a label");
  }
  return ok({ kind: kind.value, entityId: entityId.value, label: label.value });
}

function decodeMutationParties(
  value: unknown,
): DecodeResult<readonly ConstraintMutationPartyRef[]> {
  return decodeItems(value, decodeMutationPartyRef);
}

/**
 * The 22 safe members of a `ProjectConstraint`. The owning Principal's
 * identifier is the one dataclass field not listed, and it is not listed on
 * purpose: this tier never reads or republishes it.
 */
export interface ConstraintMutationRecord {
  readonly constraintId: string;
  readonly lifecycleState: ConstraintLifecycleState;
  readonly origin: ConstraintOrigin;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly version: number;
  readonly projectId: string | null;
  readonly categoryId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly reference: string | null;
  readonly currentUpdate: string | null;
  readonly bic: readonly ConstraintMutationPartyRef[];
  readonly responsible: readonly ConstraintMutationPartyRef[];
  readonly completionDate: string | null;
  readonly closureCommentary: string | null;
  readonly voidedDate: string | null;
  readonly voidReason: string | null;
  readonly recordQuality: ConstraintRecordQuality;
  readonly publishedAt: string | null;
}

const RECORD_KEYS = [
  "constraint_id",
  "lifecycle_state",
  "origin",
  "created_at",
  "updated_at",
  "version",
  "project_id",
  "category_id",
  "constraint_code",
  "description",
  "date_identified",
  "due_date",
  "reference",
  "current_update",
  "bic",
  "responsible",
  "completion_date",
  "closure_commentary",
  "voided_date",
  "void_reason",
  "record_quality",
  "published_at",
] as const;

export function decodeConstraintMutationRecord(
  input: unknown,
): DecodeResult<ConstraintMutationRecord> {
  const known = pick(input, RECORD_KEYS);
  if (!known.ok) return known;
  const record = known.value;
  const constraintId = requiredMatching(record.constraint_id, CONSTRAINT_ID);
  if (!constraintId.ok) return constraintId;
  const lifecycleState = oneOf(record.lifecycle_state, CONSTRAINT_LIFECYCLE_STATES);
  if (!lifecycleState.ok) return lifecycleState;
  const origin = oneOf(record.origin, CONSTRAINT_ORIGINS);
  if (!origin.ok) return origin;
  const createdAt = requiredMatching(record.created_at, ISO_INSTANT);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredMatching(record.updated_at, ISO_INSTANT);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredVersion(record.version);
  if (!version.ok) return version;
  const projectId = nullableMatching(record.project_id, PROJECT_ID);
  if (!projectId.ok) return projectId;
  const categoryId = nullableMatching(record.category_id, CATEGORY_ID);
  if (!categoryId.ok) return categoryId;
  // Text, always: `2.01` and `2.1` are two Codes.
  const constraintCode = requiredNullableString(record.constraint_code);
  if (!constraintCode.ok) return constraintCode;
  const description = requiredNullableString(record.description);
  if (!description.ok) return description;
  const dateIdentified = nullableMatching(record.date_identified, ISO_DATE);
  if (!dateIdentified.ok) return dateIdentified;
  const dueDate = nullableMatching(record.due_date, ISO_DATE);
  if (!dueDate.ok) return dueDate;
  const reference = requiredNullableString(record.reference);
  if (!reference.ok) return reference;
  const currentUpdate = requiredNullableString(record.current_update);
  if (!currentUpdate.ok) return currentUpdate;
  const bic = decodeMutationParties(record.bic);
  if (!bic.ok) return bic;
  const responsible = decodeMutationParties(record.responsible);
  if (!responsible.ok) return responsible;
  const completionDate = nullableMatching(record.completion_date, ISO_DATE);
  if (!completionDate.ok) return completionDate;
  const closureCommentary = requiredNullableString(record.closure_commentary);
  if (!closureCommentary.ok) return closureCommentary;
  const voidedDate = nullableMatching(record.voided_date, ISO_DATE);
  if (!voidedDate.ok) return voidedDate;
  const voidReason = requiredNullableString(record.void_reason);
  if (!voidReason.ok) return voidReason;
  const recordQuality = oneOf(record.record_quality, CONSTRAINT_RECORD_QUALITIES);
  if (!recordQuality.ok) return recordQuality;
  const publishedAt = nullableMatching(record.published_at, ISO_INSTANT);
  if (!publishedAt.ok) return publishedAt;
  return ok({
    constraintId: constraintId.value,
    lifecycleState: lifecycleState.value,
    origin: origin.value,
    createdAt: createdAt.value,
    updatedAt: updatedAt.value,
    version: version.value,
    projectId: projectId.value,
    categoryId: categoryId.value,
    constraintCode: constraintCode.value,
    description: description.value,
    dateIdentified: dateIdentified.value,
    dueDate: dueDate.value,
    reference: reference.value,
    currentUpdate: currentUpdate.value,
    bic: bic.value,
    responsible: responsible.value,
    completionDate: completionDate.value,
    closureCommentary: closureCommentary.value,
    voidedDate: voidedDate.value,
    voidReason: voidReason.value,
    recordQuality: recordQuality.value,
    publishedAt: publishedAt.value,
  });
}

/**
 * The 11 safe members of a `ConstraintHistoryEntry`. The six withheld are the
 * request's own identity and telemetry, not facts about the Constraint.
 */
export interface ConstraintMutationReceipt {
  readonly historyId: string;
  readonly constraintId: string;
  readonly operation: ConstraintMutationOperation;
  readonly actor: ConstraintMutationActor;
  readonly outcome: ConstraintMutationOutcome;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly projectId: string | null;
  readonly revisionId: string | null;
  readonly safeFailureReason: string | null;
}

const RECEIPT_KEYS = [
  "history_id",
  "constraint_id",
  "operation",
  "actor",
  "outcome",
  "before_version",
  "after_version",
  "occurred_at",
  "project_id",
  "revision_id",
  "safe_failure_reason",
] as const;

/**
 * `_check_versions`, restated: an applied receipt advanced the version, any
 * other outcome left it where it was. True of every stored receipt, so it holds
 * for a replayed one too.
 */
function versionsConsistent(
  outcome: ConstraintMutationOutcome,
  beforeVersion: number,
  afterVersion: number,
): boolean {
  return outcome === "applied" ? afterVersion > beforeVersion : afterVersion === beforeVersion;
}

export function decodeConstraintMutationReceipt(
  input: unknown,
): DecodeResult<ConstraintMutationReceipt> {
  const known = pick(input, RECEIPT_KEYS);
  if (!known.ok) return known;
  const receipt = known.value;
  const historyId = requiredMatching(receipt.history_id, CONSTRAINT_HISTORY_ID);
  if (!historyId.ok) return historyId;
  const constraintId = requiredMatching(receipt.constraint_id, CONSTRAINT_ID);
  if (!constraintId.ok) return constraintId;
  const operation = oneOf(receipt.operation, CONSTRAINT_MUTATION_OPERATIONS);
  if (!operation.ok) return operation;
  const actor = oneOf(receipt.actor, CONSTRAINT_MUTATION_ACTORS);
  if (!actor.ok) return actor;
  const outcome = oneOf(receipt.outcome, CONSTRAINT_MUTATION_OUTCOMES);
  if (!outcome.ok) return outcome;
  // `before_version` is `0` for a `create`, so both are counts, not versions.
  const beforeVersion = requiredCount(receipt.before_version);
  if (!beforeVersion.ok) return beforeVersion;
  const afterVersion = requiredCount(receipt.after_version);
  if (!afterVersion.ok) return afterVersion;
  if (!versionsConsistent(outcome.value, beforeVersion.value, afterVersion.value)) {
    return fail("a receipt's versions contradicted its outcome");
  }
  const occurredAt = requiredMatching(receipt.occurred_at, ISO_INSTANT);
  if (!occurredAt.ok) return occurredAt;
  const projectId = nullableMatching(receipt.project_id, PROJECT_ID);
  if (!projectId.ok) return projectId;
  const revisionId = nullableMatching(receipt.revision_id, REVISION_ID);
  if (!revisionId.ok) return revisionId;
  const safeFailureReason = requiredNullableString(receipt.safe_failure_reason);
  if (!safeFailureReason.ok) return safeFailureReason;
  return ok({
    historyId: historyId.value,
    constraintId: constraintId.value,
    operation: operation.value,
    actor: actor.value,
    outcome: outcome.value,
    beforeVersion: beforeVersion.value,
    afterVersion: afterVersion.value,
    occurredAt: occurredAt.value,
    projectId: projectId.value,
    revisionId: revisionId.value,
    safeFailureReason: safeFailureReason.value,
  });
}

/**
 * The disposition invariant between one version-bearing record and its receipt.
 *
 * Shared by the single-record decoders and both halves of Close + Follow-up, so
 * "what `applied` means" is written once. Identity checks stay with the caller,
 * because which identities must agree differs by shape.
 */
export function checkDisposition(
  disposition: ConstraintMutationDisposition,
  record: { readonly version: number },
  receipt: {
    readonly outcome: ConstraintMutationOutcome;
    readonly beforeVersion: number;
    readonly afterVersion: number;
  },
): DecodeResult<true> {
  if (disposition === "applied") {
    if (receipt.outcome !== "applied") return fail("an applied answer carried another outcome");
    if (receipt.afterVersion !== receipt.beforeVersion + 1) {
      return fail("an applied receipt did not advance the version by one");
    }
    if (record.version !== receipt.afterVersion) {
      return fail("an applied record was not the version its receipt produced");
    }
    return ok(true);
  }
  if (disposition === "no_op") {
    if (receipt.outcome !== "no_op") return fail("a no-op answer carried another outcome");
    if (receipt.afterVersion !== receipt.beforeVersion) {
      return fail("a no-op receipt moved the version");
    }
    if (record.version !== receipt.afterVersion) {
      return fail("a no-op record was not the version its receipt recorded");
    }
    return ok(true);
  }
  // `replayed`: the current record beside the original receipt. Newer is normal;
  // older is impossible, because a version never goes backwards.
  if (record.version < receipt.afterVersion) {
    return fail("a replayed record was older than its receipt");
  }
  return ok(true);
}

/** `{disposition, constraint, receipt}`, projected. */
export interface ConstraintMutationResult {
  readonly disposition: ConstraintMutationDisposition;
  readonly constraint: ConstraintMutationRecord;
  readonly receipt: ConstraintMutationReceipt;
}

/** The shared decoder for the eight single-record Constraint capabilities. */
export function decodeConstraintMutationResult(
  input: unknown,
): DecodeResult<ConstraintMutationResult> {
  const known = pick(input, ["disposition", "constraint", "receipt"]);
  if (!known.ok) return known;
  const disposition = oneOf(known.value.disposition, CONSTRAINT_MUTATION_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const constraint = decodeConstraintMutationRecord(known.value.constraint);
  if (!constraint.ok) return constraint;
  const receipt = decodeConstraintMutationReceipt(known.value.receipt);
  if (!receipt.ok) return receipt;
  if (receipt.value.constraintId !== constraint.value.constraintId) {
    return fail("a receipt named a different Constraint");
  }
  if (disposition.value !== "replayed" && receipt.value.projectId !== constraint.value.projectId) {
    return fail("a receipt named a different Project");
  }
  const invariant = checkDisposition(disposition.value, constraint.value, receipt.value);
  if (!invariant.ok) return invariant;
  return ok({
    disposition: disposition.value,
    constraint: constraint.value,
    receipt: receipt.value,
  });
}

/** Close + Follow-up: both records, both receipts, and the edge between them. */
export interface ConstraintFollowUpResult {
  readonly disposition: CompositeDisposition;
  readonly predecessor: ConstraintMutationRecord;
  readonly successor: ConstraintMutationRecord;
  readonly predecessorReceipt: ConstraintMutationReceipt;
  readonly successorReceipt: ConstraintMutationReceipt;
  readonly relationshipId: string;
}

export function decodeConstraintFollowUpResult(
  input: unknown,
): DecodeResult<ConstraintFollowUpResult> {
  const known = pick(input, [
    "disposition",
    "predecessor",
    "successor",
    "predecessor_receipt",
    "successor_receipt",
    "relationship_id",
  ]);
  if (!known.ok) return known;
  const disposition = oneOf(known.value.disposition, COMPOSITE_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const predecessor = decodeConstraintMutationRecord(known.value.predecessor);
  if (!predecessor.ok) return predecessor;
  const successor = decodeConstraintMutationRecord(known.value.successor);
  if (!successor.ok) return successor;
  const predecessorReceipt = decodeConstraintMutationReceipt(known.value.predecessor_receipt);
  if (!predecessorReceipt.ok) return predecessorReceipt;
  const successorReceipt = decodeConstraintMutationReceipt(known.value.successor_receipt);
  if (!successorReceipt.ok) return successorReceipt;
  const relationshipId = requiredRelationshipId(known.value.relationship_id);
  if (!relationshipId.ok) return relationshipId;
  if (predecessor.value.constraintId === successor.value.constraintId) {
    return fail("a follow-up named its predecessor as its own successor");
  }
  if (predecessorReceipt.value.constraintId !== predecessor.value.constraintId) {
    return fail("the predecessor receipt named a different Constraint");
  }
  if (successorReceipt.value.constraintId !== successor.value.constraintId) {
    return fail("the successor receipt named a different Constraint");
  }
  const before = checkDisposition(disposition.value, predecessor.value, predecessorReceipt.value);
  if (!before.ok) return before;
  const after = checkDisposition(disposition.value, successor.value, successorReceipt.value);
  if (!after.ok) return after;
  return ok({
    disposition: disposition.value,
    predecessor: predecessor.value,
    successor: successor.value,
    predecessorReceipt: predecessorReceipt.value,
    successorReceipt: successorReceipt.value,
    relationshipId: relationshipId.value,
  });
}

/**
 * The 10 safe members of a domain `ConstraintCategory`. It has no `version`
 * field at all — the version lives on the allocator row and in the receipt —
 * so none is read here. The owning Principal's identifier is the one field
 * withheld.
 */
export interface ConstraintCategoryMutationRecord {
  readonly categoryId: string;
  readonly projectId: string;
  readonly prefix: string;
  readonly title: string;
  readonly state: ConstraintCategoryState;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly description: string | null;
  readonly displayOrder: number;
  readonly prefixLockedAt: string | null;
}

const CATEGORY_KEYS = [
  "category_id",
  "project_id",
  "prefix",
  "title",
  "state",
  "created_at",
  "updated_at",
  "description",
  "display_order",
  "prefix_locked_at",
] as const;

export function decodeCategoryMutationRecord(
  input: unknown,
): DecodeResult<ConstraintCategoryMutationRecord> {
  const known = pick(input, CATEGORY_KEYS);
  if (!known.ok) return known;
  const record = known.value;
  const categoryId = requiredMatching(record.category_id, CATEGORY_ID);
  if (!categoryId.ok) return categoryId;
  const projectId = requiredMatching(record.project_id, PROJECT_ID);
  if (!projectId.ok) return projectId;
  const prefix = requiredString(record.prefix);
  if (!prefix.ok) return prefix;
  const title = requiredString(record.title);
  if (!title.ok) return title;
  const state = oneOf(record.state, CONSTRAINT_CATEGORY_STATES);
  if (!state.ok) return state;
  const createdAt = requiredMatching(record.created_at, ISO_INSTANT);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredMatching(record.updated_at, ISO_INSTANT);
  if (!updatedAt.ok) return updatedAt;
  const description = requiredNullableString(record.description);
  if (!description.ok) return description;
  const displayOrder = requiredCount(record.display_order);
  if (!displayOrder.ok) return displayOrder;
  const prefixLockedAt = nullableMatching(record.prefix_locked_at, ISO_INSTANT);
  if (!prefixLockedAt.ok) return prefixLockedAt;
  return ok({
    categoryId: categoryId.value,
    projectId: projectId.value,
    prefix: prefix.value,
    title: title.value,
    state: state.value,
    createdAt: createdAt.value,
    updatedAt: updatedAt.value,
    description: description.value,
    displayOrder: displayOrder.value,
    prefixLockedAt: prefixLockedAt.value,
  });
}

/** The 10 safe members of a `ConstraintCategoryHistoryEntry`. No revision ledger exists. */
export interface ConstraintCategoryMutationReceipt {
  readonly historyId: string;
  readonly projectId: string;
  readonly categoryId: string;
  readonly operation: ConstraintCategoryOperation;
  readonly actor: ConstraintMutationActor;
  readonly outcome: ConstraintMutationOutcome;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly safeFailureReason: string | null;
}

const CATEGORY_RECEIPT_KEYS = [
  "history_id",
  "project_id",
  "category_id",
  "operation",
  "actor",
  "outcome",
  "before_version",
  "after_version",
  "occurred_at",
  "safe_failure_reason",
] as const;

export function decodeCategoryMutationReceipt(
  input: unknown,
): DecodeResult<ConstraintCategoryMutationReceipt> {
  const known = pick(input, CATEGORY_RECEIPT_KEYS);
  if (!known.ok) return known;
  const receipt = known.value;
  const historyId = requiredMatching(receipt.history_id, CATEGORY_HISTORY_ID);
  if (!historyId.ok) return historyId;
  const projectId = requiredMatching(receipt.project_id, PROJECT_ID);
  if (!projectId.ok) return projectId;
  const categoryId = requiredMatching(receipt.category_id, CATEGORY_ID);
  if (!categoryId.ok) return categoryId;
  const operation = oneOf(receipt.operation, CONSTRAINT_CATEGORY_OPERATIONS);
  if (!operation.ok) return operation;
  const actor = oneOf(receipt.actor, CONSTRAINT_MUTATION_ACTORS);
  if (!actor.ok) return actor;
  const outcome = oneOf(receipt.outcome, CONSTRAINT_MUTATION_OUTCOMES);
  if (!outcome.ok) return outcome;
  const beforeVersion = requiredCount(receipt.before_version);
  if (!beforeVersion.ok) return beforeVersion;
  const afterVersion = requiredCount(receipt.after_version);
  if (!afterVersion.ok) return afterVersion;
  if (!versionsConsistent(outcome.value, beforeVersion.value, afterVersion.value)) {
    return fail("a receipt's versions contradicted its outcome");
  }
  const occurredAt = requiredMatching(receipt.occurred_at, ISO_INSTANT);
  if (!occurredAt.ok) return occurredAt;
  const safeFailureReason = requiredNullableString(receipt.safe_failure_reason);
  if (!safeFailureReason.ok) return safeFailureReason;
  return ok({
    historyId: historyId.value,
    projectId: projectId.value,
    categoryId: categoryId.value,
    operation: operation.value,
    actor: actor.value,
    outcome: outcome.value,
    beforeVersion: beforeVersion.value,
    afterVersion: afterVersion.value,
    occurredAt: occurredAt.value,
    safeFailureReason: safeFailureReason.value,
  });
}

/**
 * A Category as one mutation left it, with the version that mutation produced.
 *
 * `version` is the receipt's `afterVersion`, because the domain record carries
 * none. It is a *mutation* version: the right `expectedVersion` for the next
 * write only until the canonical `constraint_categories.list` is refetched,
 * which is the authority. For a replay it is the original attempt's version,
 * not necessarily the current one.
 */
export interface ConstraintCategoryWithVersion extends ConstraintCategoryMutationRecord {
  readonly version: number;
}

/** `{disposition, category, receipt}`, projected. */
export interface ConstraintCategoryMutationResult {
  readonly disposition: ConstraintMutationDisposition;
  readonly category: ConstraintCategoryWithVersion;
  readonly receipt: ConstraintCategoryMutationReceipt;
}

/** The shared decoder for the three single-Category capabilities. */
export function decodeCategoryMutationResult(
  input: unknown,
): DecodeResult<ConstraintCategoryMutationResult> {
  const known = pick(input, ["disposition", "category", "receipt"]);
  if (!known.ok) return known;
  const disposition = oneOf(known.value.disposition, CONSTRAINT_MUTATION_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const category = decodeCategoryMutationRecord(known.value.category);
  if (!category.ok) return category;
  const receipt = decodeCategoryMutationReceipt(known.value.receipt);
  if (!receipt.ok) return receipt;
  // A Category never moves Project, so both identities hold for every disposition.
  if (receipt.value.categoryId !== category.value.categoryId) {
    return fail("a receipt named a different Category");
  }
  if (receipt.value.projectId !== category.value.projectId) {
    return fail("a receipt named a different Project");
  }
  if (disposition.value === "applied") {
    if (receipt.value.outcome !== "applied") {
      return fail("an applied answer carried another outcome");
    }
    if (receipt.value.afterVersion !== receipt.value.beforeVersion + 1) {
      return fail("an applied receipt did not advance the version by one");
    }
  } else if (disposition.value === "no_op") {
    if (receipt.value.outcome !== "no_op") return fail("a no-op answer carried another outcome");
    if (receipt.value.afterVersion !== receipt.value.beforeVersion) {
      return fail("a no-op receipt moved the version");
    }
  }
  const version = requiredVersion(receipt.value.afterVersion);
  if (!version.ok) return version;
  return ok({
    disposition: disposition.value,
    category: { ...category.value, version: version.value },
    receipt: receipt.value,
  });
}

/**
 * One atomic reorder: every Category in its new order, and the receipts.
 *
 * The categories carry no `version` here. `applied` writes one receipt per
 * Category and a consumer can pair them positionally; `replayed` returns only
 * the one keyed receipt, so no per-Category version exists to publish.
 */
export interface ConstraintCategoryReorderResult {
  readonly disposition: CompositeDisposition;
  readonly categories: readonly ConstraintCategoryMutationRecord[];
  readonly receipts: readonly ConstraintCategoryMutationReceipt[];
}

export function decodeCategoryReorderResult(
  input: unknown,
): DecodeResult<ConstraintCategoryReorderResult> {
  const known = pick(input, ["disposition", "categories", "receipts"]);
  if (!known.ok) return known;
  const disposition = oneOf(known.value.disposition, COMPOSITE_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const categories = decodeItems(known.value.categories, decodeCategoryMutationRecord);
  if (!categories.ok) return categories;
  const receipts = decodeItems(known.value.receipts, decodeCategoryMutationReceipt);
  if (!receipts.ok) return receipts;
  const ordered = categories.value;
  // `ReorderConstraintCategories` refuses an empty or repeating sequence, and
  // the answer is the whole Project's scheme, so both hold for every disposition.
  const first = ordered[0];
  if (first === undefined) return fail("a reorder answered with no categories");
  if (new Set(ordered.map((category) => category.categoryId)).size !== ordered.length) {
    return fail("a reorder named one category twice");
  }
  const projectId = first.projectId;
  if (ordered.some((category) => category.projectId !== projectId)) {
    return fail("a reorder spanned more than one Project");
  }
  if (receipts.value.some((receipt) => receipt.projectId !== projectId)) {
    return fail("a reorder receipt named a different Project");
  }
  if (disposition.value === "applied") {
    if (receipts.value.length !== ordered.length) {
      return fail("an applied reorder did not receipt every category");
    }
    for (const [index, category] of ordered.entries()) {
      const receipt = receipts.value[index];
      if (receipt === undefined || receipt.categoryId !== category.categoryId) {
        return fail("an applied reorder's receipts were not aligned with its categories");
      }
      if (receipt.outcome !== "applied") {
        return fail("an applied reorder carried another outcome");
      }
      if (receipt.afterVersion !== receipt.beforeVersion + 1) {
        return fail("an applied reorder receipt did not advance the version by one");
      }
      // `reorder_categories` writes `display_order=position` over
      // `enumerate(wanted)`: zero-based, and exactly the array index.
      if (category.displayOrder !== index) {
        return fail("an applied reorder's display order was not its position");
      }
    }
  } else {
    // `_replayed_reorder`: the current scheme in the requested order, plus the
    // single receipt the caller's key was recorded on — the first Category's.
    // Count alignment is not required and display orders may have moved since.
    const [only, ...rest] = receipts.value;
    if (only === undefined || rest.length > 0) {
      return fail("a replayed reorder did not carry exactly one receipt");
    }
    if (only.categoryId !== first.categoryId) {
      return fail("a replayed reorder receipt was not the first category's");
    }
    if (only.outcome !== "applied" || only.afterVersion !== only.beforeVersion + 1) {
      return fail("a replayed reorder receipt was not a successful one");
    }
  }
  return ok({ disposition: disposition.value, categories: ordered, receipts: receipts.value });
}
