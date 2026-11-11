import { closed, ok } from "../primitives";
import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, boolean, integer, enumeration, identifier, timestamp, type Decoded } from "./continuity.projects.create";

/*
 * `records.lineage` (record lineage S1 contract sections 7.1 and 7.2), decoded
 * strictly: every object is reconstructed from its named keys and an unknown
 * key — a source, passage or evidence-set digest included — refuses the whole answer. The
 * Python models are `contracts/v1/record_lineage.py`.
 *
 * S2 (contract section 7.4) widens exactly two closed sets in lockstep with the
 * server vocabulary: `relation_type` admits the four S2 relations and an Issue
 * `state` admits `closed`. A value outside them still refuses the whole answer.
 *
 * S3 (contract sections 3, 7.1 and 7.2) widens in lockstep again: a link may be
 * `contested`, an anchor `restricted`, the answer `restricted_evidence` or
 * `scope_changed_restart_required`; the answer states its `qualifiers` and the
 * cuts it was read at (`known_at`, `valid_at`, `lineage_valid_at`,
 * `native_cut_at`), `next_cursor` is an opaque base64url token or `null`, and
 * every node states the path step that reached it (`reached_from`,
 * `reached_via`, both `null` on the root).
 *
 * S3.1 (contract sections 4.3 and 7.6) widens in lockstep once more: an
 * association's `acceptance_basis` admits `client_identified` (a connected
 * client's unreviewed fact), and it states the client's unverified
 * `user_directed_claim` and the writing OAuth client (`asserting_client_id`,
 * `null` for the human channel and for every remote reader).
 *
 * Schedule Scenarios S6-3 (schedule scenarios contract section 15.11.3a) widens
 * in lockstep: a node of one of the 6 Schedule families carries a `schedule`
 * summary with exactly its family's keys (every key present, `null` included),
 * and never another family; a virtual edge admits the 8 Schedule edge types,
 * each between exactly its two endpoint families; a path step stays the
 * `meeting_note_version_of` step only (a Schedule edge is never traversed).
 */
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

/** Python `RecordFamily`: S1's 7 and the 6 Schedule Scenarios S6-3 families (contract section 5.1). */
export const RECORD_FAMILIES = [
  "situation", "meeting", "meeting_note_version", "task", "commitment", "constraint", "capture_version",
  "schedule_publication", "schedule_activity", "schedule_baseline", "scenario", "scenario_version", "scenario_output",
] as const;
export type RecordFamily = (typeof RECORD_FAMILIES)[number];
/** `RECORD_FAMILY_ID_KINDS`: the identifier prefix each family's root carries. */
const FAMILY_PREFIX: Readonly<Record<RecordFamily, string>> = {
  situation: "sit", meeting: "mtg", meeting_note_version: "mnote", task: "tsk",
  commitment: "cmt", constraint: "cst", capture_version: "capver",
  schedule_publication: "spub", schedule_activity: "sact", schedule_baseline: "sbl",
  scenario: "sscn", scenario_version: "sscv", scenario_output: "ssco",
};
/** Python `domain/lineage/vocabulary.py` `ISSUE_STATES` (S2 admits `closed`). */
export const ISSUE_STATES = ["open", "active", "suspended", "closed"] as const;
/**
 * Python `RelationType`: the 3 S1 relations, the 4 S2 adds (S2 section 3.1), S3's 1 (S3 section 3.1)
 * and the 3 Schedule Scenarios S6-3 adds (schedule scenarios contract section 5.2).
 */
export const RELATION_TYPES = [
  "issue_member", "originated_from", "discusses",
  "delegated_from", "escalated_from", "blocks", "created_to_resolve",
  "related_context",
  "concerns", "delays", "mitigates",
] as const;
/** Python `LinkLifecycleState` (S3 adds `contested`, S3 section 3). */
export const LINK_LIFECYCLE_STATES = ["active", "ended", "contested"] as const;
/** Python `EvidenceAvailability` as a read sends it (S3 adds `restricted`). */
export const EVIDENCE_AVAILABILITIES = ["available", "archived", "legacy_unversioned", "restricted"] as const;
/** Python `LineageCompleteness` (S3 adds `restricted_evidence`, `scope_changed_restart_required`). */
export const LINEAGE_COMPLETENESS = [
  "complete", "truncated_budget", "unresolved_ambiguity", "partial_native_history",
  "restricted_evidence", "scope_changed_restart_required",
] as const;
export type LineageCompleteness = (typeof LINEAGE_COMPLETENESS)[number];
const MAX_ISSUE_TITLE_CHARACTERS = 500;
/** S3 section 5: an opaque cursor is unpadded base64url, at most 2048 characters. */
const LINEAGE_CURSOR = /^[A-Za-z0-9_-]{1,2048}$/;
/** Python `AcceptanceBasis` (S3.1 adds `client_identified`, S3.1 section 4.1). */
export const ACCEPTANCE_BASES = ["user_confirmed", "client_identified"] as const;
export type AcceptanceBasis = (typeof ACCEPTANCE_BASES)[number];
/** Python `MAX_ASSERTING_CLIENT_ID_CHARACTERS`: an OAuth client id, 1..256 characters. */
export const assertingClientId: Decoder<string | null> = nullable(text(1, 256));

function prefixed(value: string, prefix: string): boolean {
  return new RegExp(`^${prefix}_[A-Za-z0-9]{8,64}$`).exec(value)?.[0] === value;
}

export const recordRef = checked(
  strictObject({ family: enumeration(RECORD_FAMILIES), record_id: text() }),
  (value) => prefixed(value.record_id, FAMILY_PREFIX[value.family]),
);

/** The anchor's source root and version must carry their family's prefixes. */
const ANCHOR_PREFIX = {
  meeting_note_version: { root: "mtg", version: "mnote" },
  capture_version: { root: "cap", version: "capver" },
  capture: { root: "cap", version: null },
} as const;

export const evidenceAnchor = checked(strictObject({
  anchor_id: identifier("ian"),
  family: enumeration(["meeting_note_version", "capture_version", "capture"]),
  root_id: text(),
  version_kind: enumeration(["immutable_version", "legacy_unversioned"]),
  version_id: nullable(text()),
  source_version_no: nullable(integer(1)),
  passage_start_cp: nullable(integer(0)),
  passage_end_cp: nullable(integer(1)),
  role: enumeration(["origin", "corroborates", "contradicts", "discussion", "handoff", "resolution"]),
  availability: enumeration(EVIDENCE_AVAILABILITIES),
}), (value) => {
  const expected = ANCHOR_PREFIX[value.family];
  if (!prefixed(value.root_id, expected.root)) return false;
  if (expected.version === null) return value.version_id === null;
  return value.version_id === null || prefixed(value.version_id, expected.version);
});

export const association = strictObject({
  link_id: identifier("irl"),
  kind: enumeration(["issue_membership", "semantic"]),
  relation_type: enumeration(RELATION_TYPES),
  from: recordRef,
  to: recordRef,
  member_role: nullable(enumeration(["origin_evidence", "discussion", "work", "constraint", "supporting_evidence", "reference"])),
  context_issue_id: nullable(identifier("sit")),
  revision_no: integer(1),
  lifecycle_state: enumeration(LINK_LIFECYCLE_STATES),
  acceptance_basis: enumeration(ACCEPTANCE_BASES),
  authority_class: text(1),
  user_directed_claim: boolean,
  asserting_client_id: assertingClientId,
  evidence: arrayOf(evidenceAnchor, 32),
  created_at: timestamp,
  recorded_at: timestamp,
});

export const issueTitle = text(1, MAX_ISSUE_TITLE_CHARACTERS);
const issueMatch = strictObject({ issue_id: identifier("sit"), title: issueTitle, state: enumeration(ISSUE_STATES) });

/*
 * S3 section 7.1: how a node was first reached -- a typed link, or the native
 * `meeting_note_version_of` step -- each with exactly its own keys.
 */
const PATH_SHAPES = {
  typed: strictObject({ edge: enumeration(["typed"]), link_id: identifier("irl") }),
  virtual: strictObject({ edge: enumeration(["virtual"]), edge_type: enumeration(["meeting_note_version_of"]) }),
};
export type LineagePathEdge =
  | { readonly edge: "typed"; readonly link_id: string }
  | { readonly edge: "virtual"; readonly edge_type: "meeting_note_version_of" };
const pathEdge: Decoder<LineagePathEdge> = (input) => {
  const edge = (input as { edge?: unknown } | null)?.edge;
  return edge === "virtual" ? PATH_SHAPES.virtual(input) : PATH_SHAPES.typed(input);
};

/*
 * Schedule Scenarios S6-3 (contract section 15.11.3a item 1): a Schedule node's
 * `schedule` summary -- its labels (`data_class`, `authority`, `authoritative`,
 * `reportable`, always `false`, and `trust`) and its family's few fields, never
 * a name, client text, provenance or another record's identifier.
 */
/** The label values a Schedule node carries (section 15.6.3, the node-only row of R10-S06). */
export const SCHEDULE_DATA_CLASSES = [
  "schedule_publication", "schedule_activity", "schedule_baseline", "schedule_scenario",
  "schedule_scenario_output",
] as const;
export const SCHEDULE_AUTHORITIES = [
  "source_bound_derived", "operator_approved", "proposed", "client_authored", "client_asserted",
] as const;
export const SCHEDULE_TRUST_LEVELS = ["source_bound_derived", "model_proposed"] as const;
/** Python `SchedulePublicationStatus`, `BaselineStatus`, `BaselineType`, `VersionLabel`, `OutputKind`. */
const PUBLICATION_STATUSES = ["queued", "processing", "complete", "partial", "review_required", "failed"] as const;
const BASELINE_STATUSES = ["proposed", "approved", "ineligible", "rejected", "withdrawn", "revoked"] as const;
const BASELINE_TYPES = ["contract", "approved_update"] as const;
const VERSION_LABELS = ["what_if", "update", "simulation_input"] as const;
const OUTPUT_KINDS = ["monte_carlo", "criticality", "sensitivity"] as const;
const isoDate = checked(text(10, 10), (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const day = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value;
});
const no = checked(boolean, (value) => !value);
function labels<const C extends string, const A extends readonly string[], const T extends string>(
  dataClass: C, authorities: A, trust: T, authoritative: Decoder<boolean> = no,
) {
  return {
    data_class: enumeration([dataClass] as const), authority: enumeration(authorities),
    authoritative, reportable: no, trust: enumeration([trust] as const),
  };
}
const SOURCE = ["source_bound_derived"] as const;
const SCHEDULE_SHAPES = {
  schedule_publication: strictObject({
    ...labels("schedule_publication", SOURCE, "source_bound_derived"),
    data_date: nullable(isoDate), status: enumeration(PUBLICATION_STATUSES),
    series_kind: enumeration(["standard", "intake"]),
  }),
  schedule_activity: strictObject({
    ...labels("schedule_activity", SOURCE, "source_bound_derived"),
    published_activity_id: text(1, 256),
  }),
  schedule_baseline: checked(strictObject({
    ...labels("schedule_baseline", ["operator_approved", "proposed"] as const, "model_proposed", boolean),
    status: enumeration(BASELINE_STATUSES), label: nullable(text(1, 32)),
    effective_type: nullable(enumeration(BASELINE_TYPES)),
  }), (value) => (value.authority === "operator_approved") === (value.effective_type !== null) &&
    value.authoritative === (value.status === "approved")),
  scenario: strictObject({
    ...labels("schedule_scenario", ["client_authored"] as const, "model_proposed"),
    origin_kind: enumeration(["publication", "version"]),
  }),
  scenario_version: strictObject({
    ...labels("schedule_scenario", ["client_authored"] as const, "model_proposed"),
    version_no: integer(1), version_label: enumeration(VERSION_LABELS),
  }),
  scenario_output: strictObject({
    ...labels("schedule_scenario_output", ["client_asserted"] as const, "model_proposed"),
    kind: enumeration(OUTPUT_KINDS), iterations: integer(1),
  }),
};
type ScheduleFamily = keyof typeof SCHEDULE_SHAPES;
export type ScheduleNodeSummary = Decoded<(typeof SCHEDULE_SHAPES)[ScheduleFamily]>;
function isScheduleFamily(family: unknown): family is ScheduleFamily {
  return typeof family === "string" && Object.hasOwn(SCHEDULE_SHAPES, family);
}

/*
 * A node carries `meeting_id` only as a note version, `title` and `state` only
 * as an Issue, `availability` only as a Capture version, and `schedule` only as
 * one of the 6 Schedule families (S6-3); Python omits the keys a family does
 * not carry, so each family has its own closed shape. Every family carries its
 * path step (S3).
 */
const nodeBase = {
  family: enumeration(RECORD_FAMILIES), record_id: text(), depth: integer(0, 4),
  reached_from: nullable(recordRef), reached_via: nullable(pathEdge),
};
const NODE_SHAPES = {
  plain: strictObject(nodeBase),
  meeting_note_version: strictObject({ ...nodeBase, meeting_id: identifier("mtg") }),
  situation: strictObject({ ...nodeBase, title: issueTitle, state: enumeration(ISSUE_STATES) }),
  capture_version: strictObject({ ...nodeBase, availability: enumeration(["available", "archived"]) }),
};
const SCHEDULE_NODE_SHAPES: Readonly<Record<ScheduleFamily, Decoder<unknown>>> = {
  schedule_publication: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.schedule_publication }),
  schedule_activity: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.schedule_activity }),
  schedule_baseline: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.schedule_baseline }),
  scenario: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.scenario }),
  scenario_version: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.scenario_version }),
  scenario_output: strictObject({ ...nodeBase, schedule: SCHEDULE_SHAPES.scenario_output }),
};
export type LineageNode = {
  readonly family: RecordFamily;
  readonly record_id: string;
  readonly depth: number;
  readonly meeting_id?: string;
  readonly title?: string;
  readonly state?: (typeof ISSUE_STATES)[number];
  readonly availability?: "available" | "archived";
  readonly schedule?: ScheduleNodeSummary;
  readonly reached_from: Decoded<typeof recordRef> | null;
  readonly reached_via: LineagePathEdge | null;
};
const node: Decoder<LineageNode> = (input) => {
  const family = (input as { family?: unknown } | null)?.family;
  const shape: Decoder<unknown> = isScheduleFamily(family) ? SCHEDULE_NODE_SHAPES[family]
    : family === "meeting_note_version" || family === "situation" || family === "capture_version"
      ? NODE_SHAPES[family] : NODE_SHAPES.plain;
  const result = shape(input);
  if (!result.ok) return invalid();
  const value = result.value as LineageNode;
  if ((value.reached_from === null) !== (value.reached_via === null)) return invalid();
  return prefixed(value.record_id, FAMILY_PREFIX[value.family]) ? ok(value) : invalid();
};

/** Python `NATIVE_VIRTUAL_EDGE_ENDPOINTS`: each native edge's `(from, to)` families (15.11.3a item 2). */
export const NATIVE_VIRTUAL_EDGE_ENDPOINTS = {
  meeting_note_version_of: ["meeting_note_version", "meeting"],
  scenario_version_of: ["scenario_version", "scenario"],
  scenario_version_parent: ["scenario_version", "scenario_version"],
  scenario_based_on_publication: ["scenario", "schedule_publication"],
  scenario_based_on_baseline: ["scenario", "schedule_baseline"],
  scenario_forked_from_version: ["scenario", "scenario_version"],
  scenario_output_of: ["scenario_output", "scenario_version"],
  schedule_baseline_designates: ["schedule_baseline", "schedule_publication"],
  schedule_baseline_supersedes: ["schedule_baseline", "schedule_baseline"],
} as const satisfies Readonly<Record<string, readonly [RecordFamily, RecordFamily]>>;
/** Python `NativeVirtualEdge`: the note-version edge and the 8 Schedule Scenarios S6-3 edges. */
export const NATIVE_VIRTUAL_EDGES = [
  "meeting_note_version_of",
  "scenario_version_of", "scenario_version_parent", "scenario_based_on_publication",
  "scenario_based_on_baseline", "scenario_forked_from_version", "scenario_output_of",
  "schedule_baseline_designates", "schedule_baseline_supersedes",
] as const satisfies readonly (keyof typeof NATIVE_VIRTUAL_EDGE_ENDPOINTS)[];
export type NativeVirtualEdge = (typeof NATIVE_VIRTUAL_EDGES)[number];

const virtualEdge = checked(
  strictObject({ edge_type: enumeration(NATIVE_VIRTUAL_EDGES), from: recordRef, to: recordRef }),
  (value) => {
    const [from, to] = NATIVE_VIRTUAL_EDGE_ENDPOINTS[value.edge_type];
    return value.from.family === from && value.to.family === to;
  },
);

/** S3: `next_cursor` is an opaque base64url token (at most 2048 characters) or `null`. */
export const lineageCursor: Decoder<string | null> = nullable(checked(text(1, 2048), (value) => LINEAGE_CURSOR.test(value)));

const lineage = checked(strictObject({
  root: recordRef,
  selected_issue_id: nullable(identifier("sit")),
  issues_matching_root: arrayOf(issueMatch, 20),
  nodes: arrayOf(node, 250),
  typed_edges: arrayOf(association, 400),
  virtual_native_edges: arrayOf(virtualEdge, 400),
  complete_state: enumeration(LINEAGE_COMPLETENESS),
  qualifiers: arrayOf(enumeration(LINEAGE_COMPLETENESS), LINEAGE_COMPLETENESS.length),
  known_at: nullable(timestamp),
  valid_at: nullable(timestamp),
  lineage_valid_at: nullable(timestamp),
  native_cut_at: nullable(timestamp),
  next_cursor: lineageCursor,
}), (value) => value.typed_edges.length + value.virtual_native_edges.length <= 400 &&
  value.qualifiers.length >= 1 && value.qualifiers[0] === value.complete_state);

export type RecordRefView = Decoded<typeof recordRef>;
export type EvidenceAnchorView = Decoded<typeof evidenceAnchor>;
export type AssociationView = Decoded<typeof association>;
export type RecordsLineageResult = Decoded<typeof lineage>;
export const decodeRecordsLineage: Decoder<RecordsLineageResult> = lineage;
