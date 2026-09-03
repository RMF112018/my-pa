import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  knownPresent,
  oneOf,
  pick,
  requiredArray,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const SITUATION_STATES = ["open", "active", "suspended", "closed"] as const;

export type SituationState = (typeof SITUATION_STATES)[number];

export const FRAME_STATES = ["current", "saved", "archived"] as const;

export const DECISION_STATES = ["open", "closed"] as const;

export const CONTINUITY_TASK_STATES = ["open", "closed"] as const;

export const RELATIONSHIP_EVENT_TYPES = [
  "interaction",
  "meeting",
  "commitment",
  "observation",
  "affiliation_change",
  "project_link",
] as const;

export type RelationshipEventType = (typeof RELATIONSHIP_EVENT_TYPES)[number];

export interface SituationRow {
  readonly situation_id: string;
  readonly title: string;
  readonly state: SituationState;
  readonly description: string | null;
  readonly object_refs: readonly string[];
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly outcome: string | null;
}

export interface ContinuityFrame {
  readonly frame_id: string;
  readonly situation_id: string;
  readonly label: string;
  readonly state: (typeof FRAME_STATES)[number];
  readonly evidence_refs: readonly string[];
  readonly alternatives: readonly string[];
  readonly obligations: readonly string[];
  readonly uncertainty: string | null;
  readonly next_authority: string | null;
}

export interface ContinuityTrace {
  readonly trace_id: string;
  readonly object_id: string;
  readonly object_type: string;
  readonly source_events: readonly unknown[];
  readonly gaps: readonly unknown[];
}

export interface ContinuityWorkspaceCommitment {
  readonly commitment_id: string;
  readonly counterparty_person_id: string | null;
  readonly summary: string;
  readonly direction: string;
  readonly state: string;
  readonly due_at: string | null;
  readonly origin_evidence_ref: string;
}

export interface ContinuityWorkspaceDecision {
  readonly decision_id: string;
  readonly question: string;
  readonly state: (typeof DECISION_STATES)[number];
  readonly awaiting_authority_ref: string | null;
  readonly origin_evidence_ref: string;
}

export interface ContinuityWorkspaceTask {
  readonly task_id: string;
  readonly title: string;
  readonly state: (typeof CONTINUITY_TASK_STATES)[number];
  readonly due_at: string | null;
  readonly origin_evidence_ref: string;
}

export interface RelationshipEventRow {
  readonly event_id: string;
  readonly person_id: string;
  readonly event_type: RelationshipEventType;
  readonly occurred_at: string;
  readonly context: string | null;
  readonly source_ref: string | null;
}

export interface ContinuityWorkspace {
  readonly frames: readonly ContinuityFrame[];
  readonly traces: readonly ContinuityTrace[];
  readonly commitments: readonly ContinuityWorkspaceCommitment[];
  readonly decisions: readonly ContinuityWorkspaceDecision[];
  readonly tasks: readonly ContinuityWorkspaceTask[];
  readonly relationship_events: readonly RelationshipEventRow[];
}

export type ContinuitySituationsResult = {
  readonly situations: readonly SituationRow[];
} & Partial<ContinuityWorkspace>;

const SITUATION_KEYS = [
  "situation_id",
  "title",
  "state",
  "description",
  "object_refs",
  "opened_at",
  "closed_at",
  "outcome",
] as const;

const WORKSPACE_KEYS = [
  "frames",
  "traces",
  "commitments",
  "decisions",
  "tasks",
  "relationship_events",
] as const;

function decodeSituation(input: unknown): DecodeResult<SituationRow> {
  const known = pick(input, SITUATION_KEYS);
  if (!known.ok) return known;
  const situationId = requiredString(known.value.situation_id);
  if (!situationId.ok) return situationId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const state = oneOf(known.value.state, SITUATION_STATES);
  if (!state.ok) return state;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const objectRefs = requiredStringArray(known.value.object_refs);
  if (!objectRefs.ok) return objectRefs;
  const openedAt = requiredString(known.value.opened_at);
  if (!openedAt.ok) return openedAt;
  const closedAt = requiredNullableString(known.value.closed_at);
  if (!closedAt.ok) return closedAt;
  const outcome = requiredNullableString(known.value.outcome);
  if (!outcome.ok) return outcome;
  return ok({
    situation_id: situationId.value,
    title: title.value,
    state: state.value,
    description: description.value,
    object_refs: objectRefs.value,
    opened_at: openedAt.value,
    closed_at: closedAt.value,
    outcome: outcome.value,
  });
}

function decodeFrame(input: unknown): DecodeResult<ContinuityFrame> {
  const known = pick(input, [
    "frame_id",
    "situation_id",
    "label",
    "state",
    "evidence_refs",
    "alternatives",
    "obligations",
    "uncertainty",
    "next_authority",
  ]);
  if (!known.ok) return known;
  const frameId = requiredString(known.value.frame_id);
  if (!frameId.ok) return frameId;
  const situationId = requiredString(known.value.situation_id);
  if (!situationId.ok) return situationId;
  const label = requiredString(known.value.label);
  if (!label.ok) return label;
  const state = oneOf(known.value.state, FRAME_STATES);
  if (!state.ok) return state;
  const evidenceRefs = requiredStringArray(known.value.evidence_refs);
  if (!evidenceRefs.ok) return evidenceRefs;
  const alternatives = requiredStringArray(known.value.alternatives);
  if (!alternatives.ok) return alternatives;
  const obligations = requiredStringArray(known.value.obligations);
  if (!obligations.ok) return obligations;
  const uncertainty = requiredNullableString(known.value.uncertainty);
  if (!uncertainty.ok) return uncertainty;
  const nextAuthority = requiredNullableString(known.value.next_authority);
  if (!nextAuthority.ok) return nextAuthority;
  return ok({
    frame_id: frameId.value,
    situation_id: situationId.value,
    label: label.value,
    state: state.value,
    evidence_refs: evidenceRefs.value,
    alternatives: alternatives.value,
    obligations: obligations.value,
    uncertainty: uncertainty.value,
    next_authority: nextAuthority.value,
  });
}

function decodeTrace(input: unknown): DecodeResult<ContinuityTrace> {
  const known = pick(input, [
    "trace_id",
    "object_id",
    "object_type",
    "source_events",
    "gaps",
  ]);
  if (!known.ok) return known;
  const traceId = requiredString(known.value.trace_id);
  if (!traceId.ok) return traceId;
  const objectId = requiredString(known.value.object_id);
  if (!objectId.ok) return objectId;
  const objectType = requiredString(known.value.object_type);
  if (!objectType.ok) return objectType;
  const sourceEvents = requiredArray(known.value.source_events);
  if (!sourceEvents.ok) return sourceEvents;
  const gaps = requiredArray(known.value.gaps);
  if (!gaps.ok) return gaps;
  return ok({
    trace_id: traceId.value,
    object_id: objectId.value,
    object_type: objectType.value,
    source_events: sourceEvents.value,
    gaps: gaps.value,
  });
}

function decodeWorkspaceCommitment(
  input: unknown,
): DecodeResult<ContinuityWorkspaceCommitment> {
  const known = pick(input, [
    "commitment_id",
    "counterparty_person_id",
    "summary",
    "direction",
    "state",
    "due_at",
    "origin_evidence_ref",
  ]);
  if (!known.ok) return known;
  const commitmentId = requiredString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const counterpartyPersonId = requiredNullableString(known.value.counterparty_person_id);
  if (!counterpartyPersonId.ok) return counterpartyPersonId;
  const summary = requiredString(known.value.summary);
  if (!summary.ok) return summary;
  const direction = requiredString(known.value.direction);
  if (!direction.ok) return direction;
  const state = requiredString(known.value.state);
  if (!state.ok) return state;
  const dueAt = requiredNullableString(known.value.due_at);
  if (!dueAt.ok) return dueAt;
  const origin = requiredString(known.value.origin_evidence_ref);
  if (!origin.ok) return origin;
  return ok({
    commitment_id: commitmentId.value,
    counterparty_person_id: counterpartyPersonId.value,
    summary: summary.value,
    direction: direction.value,
    state: state.value,
    due_at: dueAt.value,
    origin_evidence_ref: origin.value,
  });
}

function decodeWorkspaceDecision(input: unknown): DecodeResult<ContinuityWorkspaceDecision> {
  const known = pick(input, [
    "decision_id",
    "question",
    "state",
    "awaiting_authority_ref",
    "origin_evidence_ref",
  ]);
  if (!known.ok) return known;
  const decisionId = requiredString(known.value.decision_id);
  if (!decisionId.ok) return decisionId;
  const question = requiredString(known.value.question);
  if (!question.ok) return question;
  const state = oneOf(known.value.state, DECISION_STATES);
  if (!state.ok) return state;
  const awaiting = requiredNullableString(known.value.awaiting_authority_ref);
  if (!awaiting.ok) return awaiting;
  const origin = requiredString(known.value.origin_evidence_ref);
  if (!origin.ok) return origin;
  return ok({
    decision_id: decisionId.value,
    question: question.value,
    state: state.value,
    awaiting_authority_ref: awaiting.value,
    origin_evidence_ref: origin.value,
  });
}

function decodeWorkspaceTask(input: unknown): DecodeResult<ContinuityWorkspaceTask> {
  const known = pick(input, ["task_id", "title", "state", "due_at", "origin_evidence_ref"]);
  if (!known.ok) return known;
  const taskId = requiredString(known.value.task_id);
  if (!taskId.ok) return taskId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const state = oneOf(known.value.state, CONTINUITY_TASK_STATES);
  if (!state.ok) return state;
  const dueAt = requiredNullableString(known.value.due_at);
  if (!dueAt.ok) return dueAt;
  const origin = requiredString(known.value.origin_evidence_ref);
  if (!origin.ok) return origin;
  return ok({
    task_id: taskId.value,
    title: title.value,
    state: state.value,
    due_at: dueAt.value,
    origin_evidence_ref: origin.value,
  });
}

function decodeRelationshipEvent(input: unknown): DecodeResult<RelationshipEventRow> {
  const known = pick(input, [
    "event_id",
    "person_id",
    "event_type",
    "occurred_at",
    "context",
    "source_ref",
  ]);
  if (!known.ok) return known;
  const eventId = requiredString(known.value.event_id);
  if (!eventId.ok) return eventId;
  const personId = requiredString(known.value.person_id);
  if (!personId.ok) return personId;
  const eventType = oneOf(known.value.event_type, RELATIONSHIP_EVENT_TYPES);
  if (!eventType.ok) return eventType;
  const occurredAt = requiredString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const context = requiredNullableString(known.value.context);
  if (!context.ok) return context;
  const sourceRef = requiredNullableString(known.value.source_ref);
  if (!sourceRef.ok) return sourceRef;
  return ok({
    event_id: eventId.value,
    person_id: personId.value,
    event_type: eventType.value,
    occurred_at: occurredAt.value,
    context: context.value,
    source_ref: sourceRef.value,
  });
}

function decodeWorkspace(record: Record<string, unknown>): DecodeResult<ContinuityWorkspace> {
  const frames = decodeItems(record.frames, decodeFrame);
  if (!frames.ok) return frames;
  const traces = decodeItems(record.traces, decodeTrace);
  if (!traces.ok) return traces;
  const commitments = decodeItems(record.commitments, decodeWorkspaceCommitment);
  if (!commitments.ok) return commitments;
  const decisions = decodeItems(record.decisions, decodeWorkspaceDecision);
  if (!decisions.ok) return decisions;
  const tasks = decodeItems(record.tasks, decodeWorkspaceTask);
  if (!tasks.ok) return tasks;
  const events = decodeItems(record.relationship_events, decodeRelationshipEvent);
  if (!events.ok) return events;
  return ok({
    frames: frames.value,
    traces: traces.value,
    commitments: commitments.value,
    decisions: decisions.value,
    tasks: tasks.value,
    relationship_events: events.value,
  });
}

export const decodeContinuitySituations: Decoder<ContinuitySituationsResult> = (input) => {
  const known = pick(input, ["situations", ...WORKSPACE_KEYS]);
  if (!known.ok) return known;
  if (known.value.situations === undefined) {
    return fail("a required array was omitted");
  }
  const situations = decodeItems(known.value.situations, decodeSituation);
  if (!situations.ok) return situations;
  const present = WORKSPACE_KEYS.filter((key) => knownPresent(known.value, key));
  if (present.length === 0) {
    return ok({ situations: situations.value });
  }
  if (present.length !== WORKSPACE_KEYS.length) {
    return fail("continuity workspace fields must arrive together");
  }
  const workspace = decodeWorkspace(known.value);
  if (!workspace.ok) return workspace;
  return ok({ situations: situations.value, ...workspace.value });
};
