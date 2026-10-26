import { closed } from "../primitives";
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
 */
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

export const RECORD_FAMILIES = ["situation", "meeting", "meeting_note_version", "task", "commitment", "constraint", "capture_version"] as const;
export type RecordFamily = (typeof RECORD_FAMILIES)[number];
/** `RECORD_FAMILY_ID_KINDS`: the identifier prefix each family's root carries. */
const FAMILY_PREFIX: Readonly<Record<RecordFamily, string>> = {
  situation: "sit", meeting: "mtg", meeting_note_version: "mnote", task: "tsk",
  commitment: "cmt", constraint: "cst", capture_version: "capver",
};
/** Python `domain/lineage/vocabulary.py` `ISSUE_STATES` (S2 admits `closed`). */
export const ISSUE_STATES = ["open", "active", "suspended", "closed"] as const;
/** Python `RelationType`: the 3 S1 relations, the 4 S2 adds (S2 section 3.1) and S3's 1 (S3 section 3.1). */
export const RELATION_TYPES = [
  "issue_member", "originated_from", "discusses",
  "delegated_from", "escalated_from", "blocks", "created_to_resolve",
  "related_context",
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
 * A node carries `meeting_id` only as a note version, `title` and `state` only
 * as an Issue, and `availability` only as a Capture version; Python omits the
 * keys a family does not carry, so each family has its own closed shape. Every
 * family carries its path step (S3).
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
export type LineageNode = {
  readonly family: RecordFamily;
  readonly record_id: string;
  readonly depth: number;
  readonly meeting_id?: string;
  readonly title?: string;
  readonly state?: (typeof ISSUE_STATES)[number];
  readonly availability?: "available" | "archived";
  readonly reached_from: Decoded<typeof recordRef> | null;
  readonly reached_via: LineagePathEdge | null;
};
const node: Decoder<LineageNode> = (input) => {
  const family = (input as { family?: unknown } | null)?.family;
  const shape = family === "meeting_note_version" || family === "situation" || family === "capture_version"
    ? NODE_SHAPES[family] : NODE_SHAPES.plain;
  const result = shape(input);
  if (!result.ok) return result;
  const value = result.value as LineageNode;
  if ((value.reached_from === null) !== (value.reached_via === null)) return invalid();
  return prefixed(value.record_id, FAMILY_PREFIX[value.family]) ? result : invalid();
};

const virtualEdge = checked(
  strictObject({ edge_type: enumeration(["meeting_note_version_of"]), from: recordRef, to: recordRef }),
  (value) => value.from.family === "meeting_note_version" && value.to.family === "meeting",
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
