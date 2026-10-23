import { closed } from "../primitives";
import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, boolean, enumeration, identifier, integer, timestamp, type Decoded } from "./continuity.projects.create";
import {
  ISSUE_STATES, LINEAGE_COMPLETENESS, LINK_LIFECYCLE_STATES, RELATION_TYPES,
  issueTitle, lineageCursor, recordRef,
} from "./records.lineage";

/*
 * `issues.timeline` (record lineage S3 contract section 7.3), decoded strictly.
 *
 * Every entry carries every key, and a key that is not its kind's is `null`; a
 * value outside a closed set, an unknown key or another kind's key refuses the
 * whole answer. A native entry names its Record Event's own columns and never a
 * field value (`historical_fields_partial: true`), except a Constraint event
 * whose stored revision snapshot gives `recorded_fields` (its lifecycle state
 * and ball-in-court parties, rendered as `constraints.read` renders `bic`). No
 * entry carries an evidence anchor, a Project name or a count. The Python
 * models are `contracts/v1/issue_timeline.py`.
 */
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

/** Python `TimelineEntryKind`, in the section 7.3 table order. */
export const TIMELINE_ENTRY_KINDS = [
  "issue_revision", "project_link", "membership", "association", "handoff", "handoff_correction", "native_event",
] as const;
export type TimelineEntryKind = (typeof TIMELINE_ENTRY_KINDS)[number];
/** Python `HandoffCorrectionAction`. */
export const HANDOFF_CORRECTION_ACTIONS = ["retime", "void"] as const;
/** The Record Event families an Issue member is read by (a note by its Meeting, a Capture version by its Capture). */
const NATIVE_FAMILIES = ["task", "commitment", "constraint", "meeting", "capture"] as const;
const NATIVE_PREFIX: Readonly<Record<(typeof NATIVE_FAMILIES)[number], string>> = {
  task: "tsk", commitment: "cmt", constraint: "cst", meeting: "mtg", capture: "cap",
};
/** `ConstraintLifecycleState` as a stored revision records it. */
const CONSTRAINT_LIFECYCLE_STATES = ["draft", "identified", "pending", "in_progress", "on_hold", "closed", "void"] as const;
const MEMBER_ROLES = ["origin_evidence", "discussion", "work", "constraint", "supporting_evidence", "reference"] as const;

/** The identifier prefix of each kind's `entry_id` (the row's own identifier). */
const ENTRY_PREFIX: Readonly<Record<TimelineEntryKind, string>> = {
  issue_revision: "irs", project_link: "ipme", membership: "irv", association: "irv",
  handoff: "ihnd", handoff_correction: "ihcr", native_event: "rcev",
};
/** The keys each kind carries; every other kind key is `null`. */
const KIND_KEYS: Readonly<Record<TimelineEntryKind, readonly string[]>> = {
  issue_revision: ["issue_version", "state", "title", "closed_at", "outcome"],
  project_link: ["project_id", "membership_revision_no", "link_state"],
  membership: ["link_id", "revision_no", "relation_type", "member_role", "lifecycle_state", "from", "to"],
  association: ["link_id", "revision_no", "relation_type", "member_role", "lifecycle_state", "from", "to"],
  handoff: ["handoff_id", "commitment_id", "sequence_no", "from_holder", "to_holder", "voided"],
  handoff_correction: ["handoff_id", "correction_id", "correction_action", "corrected_effective_at"],
  native_event: ["native", "recorded_fields"],
};
/** Kind keys that may stay `null` even on their own kind. */
const OPTIONAL_KEYS = new Set(["closed_at", "outcome", "member_role", "corrected_effective_at", "recorded_fields"]);
const ALL_KIND_KEYS = [...new Set(Object.values(KIND_KEYS).flat())];

function prefixed(value: string, prefix: string): boolean {
  return new RegExp(`^${prefix}_[A-Za-z0-9]{8,64}$`).exec(value)?.[0] === value;
}

const holder = checked(
  strictObject({ kind: enumeration(["principal", "entity"]), entity_id: nullable(identifier("ent")) }),
  (value) => (value.kind === "principal") === (value.entity_id === null),
);

const party = checked(strictObject({
  kind: enumeration(["principal", "entity", "unresolved"]),
  party_ref_id: nullable(text(1)),
  display_label: text(1),
  entity_id: nullable(identifier("ent")),
}), (value) => value.kind === "principal"
  ? value.party_ref_id === "principal" && value.entity_id === null
  : value.kind === "unresolved"
    ? value.party_ref_id === null && value.entity_id === null
    : value.entity_id !== null && value.party_ref_id === value.entity_id);

const recordedFields = strictObject({
  lifecycle_state: enumeration(CONSTRAINT_LIFECYCLE_STATES),
  ball_in_court: arrayOf(party, 32),
});

const native = checked(strictObject({
  record_family: enumeration(NATIVE_FAMILIES),
  record_id: text(),
  event_kind: enumeration(["created", "updated", "state_changed"]),
  record_version: integer(1),
  changed_fields: arrayOf(text(1, 128), 64),
  source_capability: text(1, 128),
}), (value) => prefixed(value.record_id, NATIVE_PREFIX[value.record_family]));

const entryShape = strictObject({
  entry_id: text(),
  kind: enumeration(TIMELINE_ENTRY_KINDS),
  plane: enumeration(["lineage", "native"]),
  at: timestamp,
  recorded_at: timestamp,
  subject: nullable(recordRef),
  action: text(1, 64),
  historical_fields_partial: boolean,
  issue_version: nullable(integer(1)),
  state: nullable(enumeration(ISSUE_STATES)),
  title: nullable(issueTitle),
  closed_at: nullable(timestamp),
  outcome: nullable(text(1, 2000)),
  project_id: nullable(identifier("prj")),
  membership_revision_no: nullable(integer(1)),
  link_state: nullable(enumeration(["active", "ended"])),
  link_id: nullable(identifier("irl")),
  revision_no: nullable(integer(1)),
  relation_type: nullable(enumeration(RELATION_TYPES)),
  member_role: nullable(enumeration(MEMBER_ROLES)),
  lifecycle_state: nullable(enumeration(LINK_LIFECYCLE_STATES)),
  from: nullable(recordRef),
  to: nullable(recordRef),
  handoff_id: nullable(identifier("ihnd")),
  commitment_id: nullable(identifier("cmt")),
  sequence_no: nullable(integer(1)),
  from_holder: nullable(holder),
  to_holder: nullable(holder),
  voided: nullable(boolean),
  correction_id: nullable(identifier("ihcr")),
  correction_action: nullable(enumeration(HANDOFF_CORRECTION_ACTIONS)),
  corrected_effective_at: nullable(timestamp),
  native: nullable(native),
  recorded_fields: nullable(recordedFields),
});
export type TimelineEntry = Decoded<typeof entryShape>;

const entry: Decoder<TimelineEntry> = (input) => {
  const result = entryShape(input);
  if (!result.ok) return result;
  const value = result.value;
  const keys = value as unknown as Record<string, unknown>;
  const own = KIND_KEYS[value.kind];
  if (!prefixed(value.entry_id, ENTRY_PREFIX[value.kind])) return invalid();
  if (ALL_KIND_KEYS.some((key) => !own.includes(key) && keys[key] !== null)) return invalid();
  if (own.some((key) => !OPTIONAL_KEYS.has(key) && keys[key] === null)) return invalid();
  const isNative = value.kind === "native_event";
  if (isNative !== (value.plane === "native")) return invalid();
  if (!isNative && value.historical_fields_partial) return invalid();
  if (isNative && value.historical_fields_partial !== (value.recorded_fields === null)) return invalid();
  if (value.recorded_fields !== null && value.native?.record_family !== "constraint") return invalid();
  if (value.kind === "membership" && value.relation_type !== "issue_member") return invalid();
  if (value.kind === "association" && value.relation_type === "issue_member") return invalid();
  return result;
};

const timeline = checked(strictObject({
  issue_id: identifier("sit"),
  known_at: nullable(timestamp),
  valid_at: nullable(timestamp),
  lineage_valid_at: nullable(timestamp),
  entries: arrayOf(entry, 100),
  complete_state: enumeration(LINEAGE_COMPLETENESS),
  qualifiers: arrayOf(enumeration(LINEAGE_COMPLETENESS), LINEAGE_COMPLETENESS.length),
  next_cursor: lineageCursor,
}), (value) => value.qualifiers.length >= 1 && value.qualifiers[0] === value.complete_state);

export type IssuesTimelineResult = Decoded<typeof timeline>;
export const decodeIssuesTimeline: Decoder<IssuesTimelineResult> = timeline;
