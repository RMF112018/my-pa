/**
 * Shared guards for the 18 read-capability decoders. Not a schema framework:
 * each decoder still names its own keys and required arrays.
 */
import {
  closed,
  ignoreUnknownKeys,
  isBoolean,
  isFiniteInteger,
  isRecord,
  isString,
  isStringArray,
  ok,
  type DecodeResult,
} from "../primitives";

export const INVALID = "upstream_contract_invalid";

export function fail(message: string): DecodeResult<never> {
  return closed(INVALID, message);
}

export function oneOf<T extends string>(
  value: unknown,
  allowed: readonly T[],
): DecodeResult<T> {
  if (isString(value)) {
    for (const candidate of allowed) {
      if (value === candidate) return ok(candidate);
    }
  }
  return fail("a required field was not an allowed value");
}

export function requiredRecord(value: unknown): DecodeResult<Record<string, unknown>> {
  if (!isRecord(value)) return fail("a required object was missing or unreadable");
  return ok(value);
}

export function requiredString(value: unknown): DecodeResult<string> {
  if (value === undefined) return fail("a required field was missing");
  if (!isString(value)) return fail("a required field was not the expected type");
  return ok(value);
}

/** Required key whose JSON value may be `null`. Missing is a contract failure. */
export function requiredNullableString(value: unknown): DecodeResult<string | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isString(value)) return fail("a required field was not the expected type");
  return ok(value);
}

export function requiredBoolean(value: unknown): DecodeResult<boolean> {
  if (value === undefined) return fail("a required field was missing");
  if (!isBoolean(value)) return fail("a required field was not the expected type");
  return ok(value);
}

export function requiredInt(value: unknown): DecodeResult<number> {
  if (value === undefined) return fail("a required field was missing");
  if (!isFiniteInteger(value)) return fail("a required field was not the expected type");
  return ok(value);
}

export function requiredNullableInt(value: unknown): DecodeResult<number | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isFiniteInteger(value)) return fail("a required field was not the expected type");
  return ok(value);
}

export function requiredStringArray(value: unknown): DecodeResult<readonly string[]> {
  if (value === undefined) return fail("a required array was omitted");
  if (!isStringArray(value)) return fail("a required array was not an array of strings");
  return ok(value);
}

export function requiredArray(value: unknown): DecodeResult<readonly unknown[]> {
  if (value === undefined) return fail("a required array was omitted");
  if (!Array.isArray(value)) return fail("a required field was not an array");
  return ok(value);
}

export function decodeItems<T>(
  value: unknown,
  decodeItem: (item: unknown) => DecodeResult<T>,
): DecodeResult<readonly T[]> {
  const rows = requiredArray(value);
  if (!rows.ok) return rows;
  const decoded: T[] = [];
  for (const item of rows.value) {
    const row = decodeItem(item);
    if (!row.ok) return row;
    decoded.push(row.value);
  }
  return ok(decoded);
}

export function pick(
  input: unknown,
  keys: readonly string[],
): DecodeResult<Record<string, unknown>> {
  const record = requiredRecord(input);
  if (!record.ok) return record;
  return ok(ignoreUnknownKeys(record.value, keys));
}

export function knownPresent(
  record: Record<string, unknown>,
  key: string,
): boolean {
  return Object.prototype.hasOwnProperty.call(record, key) && record[key] !== undefined;
}

export const TASK_LIFECYCLE_STATES = [
  "open",
  "in_progress",
  "waiting",
  "blocked",
  "completed",
  "cancelled",
] as const;

export type TaskLifecycleState = (typeof TASK_LIFECYCLE_STATES)[number];

export const TASK_PRIORITIES = ["p1", "p2", "p3", "p4"] as const;

export type TaskPriority = (typeof TASK_PRIORITIES)[number];

export const EVIDENCE_STATES = ["proposed", "accepted"] as const;

export type ContinuityEvidenceState = (typeof EVIDENCE_STATES)[number];

export const ACCEPTANCE_KINDS = ["none", "review", "direct_principal"] as const;

export type ContinuityAcceptanceKind = (typeof ACCEPTANCE_KINDS)[number];

export const TASK_ROLES = ["follow_up"] as const;

export type TaskRole = (typeof TASK_ROLES)[number];

export const TASK_MUTATION_ACTIONS = [
  "create",
  "update",
  "update_title",
  "update_description",
  "transition_lifecycle",
  "set_priority",
  "schedule",
  "defer",
  "archive",
  "unarchive",
  "set_recurrence",
  "cancel_recurrence",
  "link_commitment",
  "set_role",
] as const;

export const TASK_MUTATION_ACTORS = ["principal", "assistant", "system"] as const;

export const TASK_MUTATION_OUTCOMES = ["applied", "rejected", "no_op"] as const;

export const COMMITMENT_DIRECTIONS = ["owed_by_principal", "owed_to_principal"] as const;

export type CommitmentDirection = (typeof COMMITMENT_DIRECTIONS)[number];

export const COMMITMENT_STATES = ["open", "closed"] as const;

export type CommitmentState = (typeof COMMITMENT_STATES)[number];

export const COMMITMENT_MUTATION_ACTIONS = ["create", "update", "close"] as const;

export function requiredNullablePriority(
  value: unknown,
): DecodeResult<TaskPriority | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  return oneOf(value, TASK_PRIORITIES);
}

export function requiredNullableEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
): DecodeResult<T | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  return oneOf(value, allowed);
}

export interface CounterpartyProjection {
  readonly person_id: string;
  readonly display_name: string;
}

export function decodeCounterparty(
  value: unknown,
): DecodeResult<CounterpartyProjection | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  const known = pick(value, ["person_id", "display_name"]);
  if (!known.ok) return known;
  const personId = requiredString(known.value.person_id);
  if (!personId.ok) return personId;
  const displayName = requiredString(known.value.display_name);
  if (!displayName.ok) return displayName;
  return ok({ person_id: personId.value, display_name: displayName.value });
}

export function decodeCounterpartyOptions(
  value: unknown,
): DecodeResult<readonly CounterpartyProjection[]> {
  return decodeItems(value, (item) => {
    const decoded = decodeCounterparty(item);
    if (!decoded.ok) return decoded;
    if (decoded.value === null) return fail("a counterparty option was null");
    return ok(decoded.value);
  });
}

export interface TaskListEntry {
  readonly task_id: string;
  readonly title: string;
  readonly lifecycle_state: TaskLifecycleState;
  readonly priority: TaskPriority | null;
  readonly due_at: string | null;
  readonly scheduled_at: string | null;
  readonly deferred_until: string | null;
  readonly archived_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
}

const TASK_LIST_KEYS = [
  "task_id",
  "title",
  "lifecycle_state",
  "priority",
  "due_at",
  "scheduled_at",
  "deferred_until",
  "archived_at",
  "created_at",
  "updated_at",
  "version",
] as const;

export function decodeTaskListEntry(input: unknown): DecodeResult<TaskListEntry> {
  const known = pick(input, TASK_LIST_KEYS);
  if (!known.ok) return known;
  const taskId = requiredString(known.value.task_id);
  if (!taskId.ok) return taskId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const lifecycle = oneOf(known.value.lifecycle_state, TASK_LIFECYCLE_STATES);
  if (!lifecycle.ok) return lifecycle;
  const priority = requiredNullablePriority(known.value.priority);
  if (!priority.ok) return priority;
  const dueAt = requiredNullableString(known.value.due_at);
  if (!dueAt.ok) return dueAt;
  const scheduledAt = requiredNullableString(known.value.scheduled_at);
  if (!scheduledAt.ok) return scheduledAt;
  const deferredUntil = requiredNullableString(known.value.deferred_until);
  if (!deferredUntil.ok) return deferredUntil;
  const archivedAt = requiredNullableString(known.value.archived_at);
  if (!archivedAt.ok) return archivedAt;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  return ok({
    task_id: taskId.value,
    title: title.value,
    lifecycle_state: lifecycle.value,
    priority: priority.value,
    due_at: dueAt.value,
    scheduled_at: scheduledAt.value,
    deferred_until: deferredUntil.value,
    archived_at: archivedAt.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
    version: version.value,
  });
}

export function decodeTaskListPage(input: unknown): DecodeResult<{ tasks: readonly TaskListEntry[] }> {
  const known = pick(input, ["tasks"]);
  if (!known.ok) return known;
  const tasks = decodeItems(known.value.tasks, decodeTaskListEntry);
  if (!tasks.ok) return tasks;
  return ok({ tasks: tasks.value });
}

export interface TaskView extends TaskListEntry {
  readonly description: string | null;
  readonly evidence_state: ContinuityEvidenceState;
  readonly origin_evidence_ref: string;
  readonly closure_evidence_ref: string | null;
  readonly accepted_by_review_decision_id: string | null;
  readonly acceptance_kind: ContinuityAcceptanceKind | null;
  readonly closure_history_id: string | null;
  readonly project_id: string | null;
  readonly situation_id: string | null;
  readonly recurrence_id: string | null;
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly commitment_id: string | null;
  readonly role: TaskRole | null;
}

const TASK_VIEW_KEYS = [
  ...TASK_LIST_KEYS,
  "description",
  "evidence_state",
  "origin_evidence_ref",
  "closure_evidence_ref",
  "accepted_by_review_decision_id",
  "acceptance_kind",
  "closure_history_id",
  "project_id",
  "situation_id",
  "recurrence_id",
  "opened_at",
  "closed_at",
  "commitment_id",
  "role",
] as const;

export function decodeTaskView(input: unknown): DecodeResult<TaskView> {
  const known = pick(input, TASK_VIEW_KEYS);
  if (!known.ok) return known;
  const entry = decodeTaskListEntry(known.value);
  if (!entry.ok) return entry;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const evidence = oneOf(known.value.evidence_state, EVIDENCE_STATES);
  if (!evidence.ok) return evidence;
  const origin = requiredString(known.value.origin_evidence_ref);
  if (!origin.ok) return origin;
  const closureRef = requiredNullableString(known.value.closure_evidence_ref);
  if (!closureRef.ok) return closureRef;
  const acceptedBy = requiredNullableString(known.value.accepted_by_review_decision_id);
  if (!acceptedBy.ok) return acceptedBy;
  const acceptance = requiredNullableEnum(known.value.acceptance_kind, ACCEPTANCE_KINDS);
  if (!acceptance.ok) return acceptance;
  const closureHistory = requiredNullableString(known.value.closure_history_id);
  if (!closureHistory.ok) return closureHistory;
  const projectId = requiredNullableString(known.value.project_id);
  if (!projectId.ok) return projectId;
  const situationId = requiredNullableString(known.value.situation_id);
  if (!situationId.ok) return situationId;
  const recurrenceId = requiredNullableString(known.value.recurrence_id);
  if (!recurrenceId.ok) return recurrenceId;
  const openedAt = requiredString(known.value.opened_at);
  if (!openedAt.ok) return openedAt;
  const closedAt = requiredNullableString(known.value.closed_at);
  if (!closedAt.ok) return closedAt;
  const commitmentId = requiredNullableString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const role = requiredNullableEnum(known.value.role, TASK_ROLES);
  if (!role.ok) return role;
  return ok({
    ...entry.value,
    description: description.value,
    evidence_state: evidence.value,
    origin_evidence_ref: origin.value,
    closure_evidence_ref: closureRef.value,
    accepted_by_review_decision_id: acceptedBy.value,
    acceptance_kind: acceptance.value,
    closure_history_id: closureHistory.value,
    project_id: projectId.value,
    situation_id: situationId.value,
    recurrence_id: recurrenceId.value,
    opened_at: openedAt.value,
    closed_at: closedAt.value,
    commitment_id: commitmentId.value,
    role: role.value,
  });
}

export interface TaskHistoryEntry {
  readonly history_id: string;
  readonly task_id: string;
  readonly action: (typeof TASK_MUTATION_ACTIONS)[number];
  readonly actor: (typeof TASK_MUTATION_ACTORS)[number];
  readonly outcome: (typeof TASK_MUTATION_OUTCOMES)[number];
  readonly before_version: number;
  readonly after_version: number;
  readonly occurred_at: string;
  readonly recorded_at: string;
}

const TASK_HISTORY_KEYS = [
  "history_id",
  "task_id",
  "action",
  "actor",
  "outcome",
  "before_version",
  "after_version",
  "occurred_at",
  "recorded_at",
] as const;

export function decodeTaskHistoryEntry(input: unknown): DecodeResult<TaskHistoryEntry> {
  const known = pick(input, TASK_HISTORY_KEYS);
  if (!known.ok) return known;
  const historyId = requiredString(known.value.history_id);
  if (!historyId.ok) return historyId;
  const taskId = requiredString(known.value.task_id);
  if (!taskId.ok) return taskId;
  const action = oneOf(known.value.action, TASK_MUTATION_ACTIONS);
  if (!action.ok) return action;
  const actor = oneOf(known.value.actor, TASK_MUTATION_ACTORS);
  if (!actor.ok) return actor;
  const outcome = oneOf(known.value.outcome, TASK_MUTATION_OUTCOMES);
  if (!outcome.ok) return outcome;
  const before = requiredInt(known.value.before_version);
  if (!before.ok) return before;
  const after = requiredInt(known.value.after_version);
  if (!after.ok) return after;
  const occurredAt = requiredString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    history_id: historyId.value,
    task_id: taskId.value,
    action: action.value,
    actor: actor.value,
    outcome: outcome.value,
    before_version: before.value,
    after_version: after.value,
    occurred_at: occurredAt.value,
    recorded_at: recordedAt.value,
  });
}

export interface CommitmentView {
  readonly commitment_id: string;
  readonly direction: CommitmentDirection;
  readonly state: CommitmentState;
  readonly counterparty_person_id: string | null;
  readonly title: string;
  readonly description: string | null;
  readonly due_date: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
  readonly evidence_state: ContinuityEvidenceState;
  readonly origin_evidence_ref: string;
  readonly closure_evidence_ref: string | null;
  readonly accepted_by_review_decision_id: string | null;
  readonly closed_at: string | null;
  readonly counterparty: CounterpartyProjection | null;
}

const COMMITMENT_VIEW_KEYS = [
  "commitment_id",
  "direction",
  "state",
  "counterparty_person_id",
  "title",
  "description",
  "due_date",
  "created_at",
  "updated_at",
  "version",
  "evidence_state",
  "origin_evidence_ref",
  "closure_evidence_ref",
  "accepted_by_review_decision_id",
  "closed_at",
  "counterparty",
] as const;

export function decodeCommitmentView(input: unknown): DecodeResult<CommitmentView> {
  const known = pick(input, COMMITMENT_VIEW_KEYS);
  if (!known.ok) return known;
  const commitmentId = requiredString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const direction = oneOf(known.value.direction, COMMITMENT_DIRECTIONS);
  if (!direction.ok) return direction;
  const state = oneOf(known.value.state, COMMITMENT_STATES);
  if (!state.ok) return state;
  const counterpartyPersonId = requiredNullableString(known.value.counterparty_person_id);
  if (!counterpartyPersonId.ok) return counterpartyPersonId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const dueDate = requiredNullableString(known.value.due_date);
  if (!dueDate.ok) return dueDate;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const evidence = oneOf(known.value.evidence_state, EVIDENCE_STATES);
  if (!evidence.ok) return evidence;
  const origin = requiredString(known.value.origin_evidence_ref);
  if (!origin.ok) return origin;
  const closureRef = requiredNullableString(known.value.closure_evidence_ref);
  if (!closureRef.ok) return closureRef;
  const acceptedBy = requiredNullableString(known.value.accepted_by_review_decision_id);
  if (!acceptedBy.ok) return acceptedBy;
  const closedAt = requiredNullableString(known.value.closed_at);
  if (!closedAt.ok) return closedAt;
  const counterparty = decodeCounterparty(known.value.counterparty);
  if (!counterparty.ok) return counterparty;
  return ok({
    commitment_id: commitmentId.value,
    direction: direction.value,
    state: state.value,
    counterparty_person_id: counterpartyPersonId.value,
    title: title.value,
    description: description.value,
    due_date: dueDate.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
    version: version.value,
    evidence_state: evidence.value,
    origin_evidence_ref: origin.value,
    closure_evidence_ref: closureRef.value,
    accepted_by_review_decision_id: acceptedBy.value,
    closed_at: closedAt.value,
    counterparty: counterparty.value,
  });
}

export interface CommitmentListEntry {
  readonly commitment_id: string;
  readonly direction: CommitmentDirection;
  readonly state: CommitmentState;
  readonly counterparty_person_id: string | null;
  readonly title: string;
  readonly description: string | null;
  readonly due_date: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
  readonly counterparty: CounterpartyProjection | null;
}

const COMMITMENT_LIST_KEYS = [
  "commitment_id",
  "direction",
  "state",
  "counterparty_person_id",
  "title",
  "description",
  "due_date",
  "created_at",
  "updated_at",
  "version",
  "counterparty",
] as const;

export function decodeCommitmentListEntry(input: unknown): DecodeResult<CommitmentListEntry> {
  const known = pick(input, COMMITMENT_LIST_KEYS);
  if (!known.ok) return known;
  const commitmentId = requiredString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const direction = oneOf(known.value.direction, COMMITMENT_DIRECTIONS);
  if (!direction.ok) return direction;
  const state = oneOf(known.value.state, COMMITMENT_STATES);
  if (!state.ok) return state;
  const counterpartyPersonId = requiredNullableString(known.value.counterparty_person_id);
  if (!counterpartyPersonId.ok) return counterpartyPersonId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const dueDate = requiredNullableString(known.value.due_date);
  if (!dueDate.ok) return dueDate;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const counterparty = decodeCounterparty(known.value.counterparty);
  if (!counterparty.ok) return counterparty;
  return ok({
    commitment_id: commitmentId.value,
    direction: direction.value,
    state: state.value,
    counterparty_person_id: counterpartyPersonId.value,
    title: title.value,
    description: description.value,
    due_date: dueDate.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
    version: version.value,
    counterparty: counterparty.value,
  });
}

export function decodeCommitmentListPage(
  input: unknown,
): DecodeResult<{
  commitments: readonly CommitmentListEntry[];
  counterparty_options: readonly CounterpartyProjection[];
  counterparty_options_truncated: boolean;
}> {
  const known = pick(input, [
    "commitments",
    "counterparty_options",
    "counterparty_options_truncated",
  ]);
  if (!known.ok) return known;
  const commitments = decodeItems(known.value.commitments, decodeCommitmentListEntry);
  if (!commitments.ok) return commitments;
  const options = decodeCounterpartyOptions(known.value.counterparty_options);
  if (!options.ok) return options;
  const truncated = requiredBoolean(known.value.counterparty_options_truncated);
  if (!truncated.ok) return truncated;
  return ok({
    commitments: commitments.value,
    counterparty_options: options.value,
    counterparty_options_truncated: truncated.value,
  });
}

export interface CommitmentHistoryEntry {
  readonly history_id: string;
  readonly commitment_id: string;
  readonly action: (typeof COMMITMENT_MUTATION_ACTIONS)[number];
  readonly actor: (typeof TASK_MUTATION_ACTORS)[number];
  readonly outcome: (typeof TASK_MUTATION_OUTCOMES)[number];
  readonly before_version: number;
  readonly after_version: number;
  readonly occurred_at: string;
  readonly recorded_at: string;
}

const COMMITMENT_HISTORY_KEYS = [
  "history_id",
  "commitment_id",
  "action",
  "actor",
  "outcome",
  "before_version",
  "after_version",
  "occurred_at",
  "recorded_at",
] as const;

export function decodeCommitmentHistoryEntry(
  input: unknown,
): DecodeResult<CommitmentHistoryEntry> {
  const known = pick(input, COMMITMENT_HISTORY_KEYS);
  if (!known.ok) return known;
  const historyId = requiredString(known.value.history_id);
  if (!historyId.ok) return historyId;
  const commitmentId = requiredString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const action = oneOf(known.value.action, COMMITMENT_MUTATION_ACTIONS);
  if (!action.ok) return action;
  const actor = oneOf(known.value.actor, TASK_MUTATION_ACTORS);
  if (!actor.ok) return actor;
  const outcome = oneOf(known.value.outcome, TASK_MUTATION_OUTCOMES);
  if (!outcome.ok) return outcome;
  const before = requiredInt(known.value.before_version);
  if (!before.ok) return before;
  const after = requiredInt(known.value.after_version);
  if (!after.ok) return after;
  const occurredAt = requiredString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    history_id: historyId.value,
    commitment_id: commitmentId.value,
    action: action.value,
    actor: actor.value,
    outcome: outcome.value,
    before_version: before.value,
    after_version: after.value,
    occurred_at: occurredAt.value,
    recorded_at: recordedAt.value,
  });
}
