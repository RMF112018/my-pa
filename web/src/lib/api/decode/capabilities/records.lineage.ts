import { closed } from "../primitives";
import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, integer, enumeration, identifier, digest, timestamp, type Decoded } from "./continuity.projects.create";

/*
 * `records.lineage` (record lineage S1 contract sections 7.1 and 7.2), decoded
 * strictly: every object is reconstructed from its named keys and an unknown
 * key — a source or passage digest included — refuses the whole answer. The
 * Python models are `contracts/v1/record_lineage.py`.
 */
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

export const RECORD_FAMILIES = ["situation", "meeting", "meeting_note_version", "task", "commitment", "constraint", "capture_version"] as const;
export type RecordFamily = (typeof RECORD_FAMILIES)[number];
/** `RECORD_FAMILY_ID_KINDS`: the identifier prefix each family's root carries. */
const FAMILY_PREFIX: Readonly<Record<RecordFamily, string>> = {
  situation: "sit", meeting: "mtg", meeting_note_version: "mnote", task: "tsk",
  commitment: "cmt", constraint: "cst", capture_version: "capver",
};
const ISSUE_STATES = ["open", "active", "suspended"] as const;
const MAX_ISSUE_TITLE_CHARACTERS = 500;

function prefixed(value: string, prefix: string): boolean {
  return new RegExp(`^${prefix}_[A-Za-z0-9]{8,64}$`).exec(value)?.[0] === value;
}

const recordRef = checked(
  strictObject({ family: enumeration(RECORD_FAMILIES), record_id: text() }),
  (value) => prefixed(value.record_id, FAMILY_PREFIX[value.family]),
);

/** The anchor's source root and version must carry their family's prefixes. */
const ANCHOR_PREFIX = {
  meeting_note_version: { root: "mtg", version: "mnote" },
  capture_version: { root: "cap", version: "capver" },
  capture: { root: "cap", version: null },
} as const;

const evidenceAnchor = checked(strictObject({
  anchor_id: identifier("ian"),
  family: enumeration(["meeting_note_version", "capture_version", "capture"]),
  root_id: text(),
  version_kind: enumeration(["immutable_version", "legacy_unversioned"]),
  version_id: nullable(text()),
  source_version_no: nullable(integer(1)),
  passage_start_cp: nullable(integer(0)),
  passage_end_cp: nullable(integer(1)),
  role: enumeration(["origin", "corroborates", "contradicts", "discussion", "handoff", "resolution"]),
  availability: enumeration(["available", "archived", "legacy_unversioned"]),
}), (value) => {
  const expected = ANCHOR_PREFIX[value.family];
  if (!prefixed(value.root_id, expected.root)) return false;
  if (expected.version === null) return value.version_id === null;
  return value.version_id === null || prefixed(value.version_id, expected.version);
});

const association = strictObject({
  link_id: identifier("irl"),
  kind: enumeration(["issue_membership", "semantic"]),
  relation_type: enumeration(["issue_member", "originated_from", "discusses"]),
  from: recordRef,
  to: recordRef,
  member_role: nullable(enumeration(["origin_evidence", "discussion", "work", "constraint", "supporting_evidence", "reference"])),
  context_issue_id: nullable(identifier("sit")),
  revision_no: integer(1),
  lifecycle_state: enumeration(["active", "ended"]),
  acceptance_basis: enumeration(["user_confirmed"]),
  authority_class: text(1),
  evidence_set_digest: digest,
  evidence: arrayOf(evidenceAnchor, 32),
  created_at: timestamp,
  recorded_at: timestamp,
});

const issueTitle = text(1, MAX_ISSUE_TITLE_CHARACTERS);
const issueMatch = strictObject({ issue_id: identifier("sit"), title: issueTitle, state: enumeration(ISSUE_STATES) });

/*
 * A node carries `meeting_id` only as a note version, `title` and `state` only
 * as an Issue, and `availability` only as a Capture version; Python omits the
 * keys a family does not carry, so each family has its own closed shape.
 */
const nodeBase = { family: enumeration(RECORD_FAMILIES), record_id: text(), depth: integer(0, 4) };
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
};
const node: Decoder<LineageNode> = (input) => {
  const family = (input as { family?: unknown } | null)?.family;
  const shape = family === "meeting_note_version" || family === "situation" || family === "capture_version"
    ? NODE_SHAPES[family] : NODE_SHAPES.plain;
  const result = shape(input);
  if (!result.ok) return result;
  return prefixed(result.value.record_id, FAMILY_PREFIX[result.value.family]) ? result : invalid();
};

const virtualEdge = checked(
  strictObject({ edge_type: enumeration(["meeting_note_version_of"]), from: recordRef, to: recordRef }),
  (value) => value.from.family === "meeting_note_version" && value.to.family === "meeting",
);

/** S1 always answers `next_cursor: null`; anything else is not this contract. */
const nullCursor: Decoder<null> = (input) => input === null ? { ok: true, value: null } : invalid();

const lineage = checked(strictObject({
  root: recordRef,
  selected_issue_id: nullable(identifier("sit")),
  issues_matching_root: arrayOf(issueMatch, 20),
  nodes: arrayOf(node, 250),
  typed_edges: arrayOf(association, 400),
  virtual_native_edges: arrayOf(virtualEdge, 400),
  complete_state: enumeration(["complete", "truncated_budget", "unresolved_ambiguity", "partial_native_history"]),
  next_cursor: nullCursor,
}), (value) => value.typed_edges.length + value.virtual_native_edges.length <= 400);

export type EvidenceAnchorView = Decoded<typeof evidenceAnchor>;
export type AssociationView = Decoded<typeof association>;
export type RecordsLineageResult = Decoded<typeof lineage>;
export const decodeRecordsLineage: Decoder<RecordsLineageResult> = lineage;
