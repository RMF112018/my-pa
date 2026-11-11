// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import {
  ACCEPTANCE_BASES, decodeRecordsLineage, ISSUE_STATES, LINK_LIFECYCLE_STATES, NATIVE_VIRTUAL_EDGE_ENDPOINTS,
  NATIVE_VIRTUAL_EDGES, RECORD_FAMILIES, RELATION_TYPES, SCHEDULE_AUTHORITIES, SCHEDULE_DATA_CLASSES,
  SCHEDULE_TRUST_LEVELS,
} from "./records.lineage";

const canonical = fixtures["records.lineage"];
type Json = Record<string, unknown>;
function payload(): Json { return structuredClone(canonical) as Json; }
type Path = readonly (string | number)[];
function at(input: Json, path: Path): Json {
  let value: unknown = input;
  for (const key of path) value = (value as Record<string | number, unknown>)[key];
  return value as Json;
}
function objects(value: unknown, path: Path = []): Path[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => objects(item, [...path, index]));
  if (value === null || typeof value !== "object") return [];
  return [path, ...Object.entries(value).flatMap(([key, item]) => objects(item, [...path, key]))];
}
const decode = decodeRecordsLineage;

describe("records.lineage strict canonical success", () => {
  it("decodes the S1 lineage response", () => {
    expect(decode(canonical)).toEqual({ ok: true, value: canonical });
    const value = payload();
    // Ambiguity: candidates only, no selection and no traversal.
    value.selected_issue_id = null;
    value.issues_matching_root = [
      { issue_id: "sit_aaaaaaaa11111111", title: "First", state: "open" },
      { issue_id: "sit_bbbbbbbb22222222", title: "Second", state: "active" },
    ];
    // S3 lockstep: every node states its path step (`null` on the root).
    value.nodes = [{ family: "task", record_id: "tsk_aaaaaaaa11111111", depth: 0, reached_from: null, reached_via: null }];
    value.typed_edges = [];
    value.virtual_native_edges = [];
    value.complete_state = "unresolved_ambiguity";
    value.qualifiers = ["unresolved_ambiguity"];
    expect(decode(value).ok).toBe(true);
    // A legacy Capture anchor and an archived Capture version node.
    const legacy = payload();
    const edge = (legacy.typed_edges as Json[])[1]!;
    edge.evidence = [{
      anchor_id: "ian_bbbbbbbb22222222", family: "capture", root_id: "cap_aaaaaaaa11111111",
      version_kind: "legacy_unversioned", version_id: null, source_version_no: null,
      passage_start_cp: null, passage_end_cp: null, role: "corroborates", availability: "archived",
    }];
    (legacy.nodes as Json[]).push({
      family: "capture_version", record_id: "capver_aaaaaaaa11111111", depth: 1, availability: "archived",
      reached_from: { family: "task", record_id: "tsk_aaaaaaaa11111111" },
      reached_via: { edge: "typed", link_id: "irl_bbbbbbbb22222222" },
    });
    expect(decode(legacy).ok).toBe(true);
  });

  it("refuses an unknown key", () => {
    for (const path of objects(canonical)) {
      for (const key of ["unexpected", "principal_id", "source_sha256", "passage_sha256", "body_markdown", "hidden_count"]) {
        const value = payload(); at(value, path)[key] = "synthetic-private";
        expect(decode(value).ok, `${path.join(".")}.${key}`).toBe(false);
      }
    }
  });

  it("requires every key the family carries and refuses another family's keys", () => {
    for (const path of objects(canonical)) {
      for (const key of Object.keys(at(payload(), path))) {
        const value = payload(); delete at(value, path)[key];
        expect(decode(value).ok, `${path.join(".")}.${key}`).toBe(false);
      }
    }
    const task = payload(); (task.nodes as Json[])[0]!.title = "Not an Issue";
    expect(decode(task).ok).toBe(false);
    const issue = payload(); (issue.nodes as Json[])[2]!.meeting_id = "mtg_aaaaaaaa11111111";
    expect(decode(issue).ok).toBe(false);
  });

  it("decodes the S2 relation types and a closed Issue", () => {
    // The closed sets are exactly the server vocabulary (S2 section 7.4); the
    // Python side of the equality is `test_record_lineage_s2_scope.py`. S3 widens
    // the server vocabulary by `related_context` (S3 section 3.1), and Schedule
    // Scenarios S6-3 by `concerns`, `delays` and `mitigates`, in lockstep.
    expect([...RELATION_TYPES]).toEqual([
      "issue_member", "originated_from", "discusses",
      "delegated_from", "escalated_from", "blocks", "created_to_resolve",
      "related_context",
      "concerns", "delays", "mitigates",
    ]);
    expect([...ISSUE_STATES]).toEqual(["open", "active", "suspended", "closed"]);
    for (const [relation, from, to] of [
      ["delegated_from", { family: "commitment", record_id: "cmt_aaaaaaaa11111111" }, { family: "task", record_id: "tsk_aaaaaaaa11111111" }],
      ["escalated_from", { family: "constraint", record_id: "cst_aaaaaaaa11111111" }, { family: "task", record_id: "tsk_aaaaaaaa11111111" }],
      ["blocks", { family: "task", record_id: "tsk_aaaaaaaa11111111" }, { family: "constraint", record_id: "cst_aaaaaaaa11111111" }],
      ["created_to_resolve", { family: "task", record_id: "tsk_aaaaaaaa11111111" }, { family: "situation", record_id: "sit_aaaaaaaa11111111" }],
    ] as const) {
      const value = payload();
      const edge = (value.typed_edges as Json[])[1]!;
      Object.assign(edge, { relation_type: relation, from, to });
      const decoded = decode(value);
      expect(decoded, relation).toEqual({ ok: true, value });
    }
    const closedIssue = payload();
    (closedIssue.nodes as Json[])[2]!.state = "closed";
    (closedIssue.issues_matching_root as Json[])[0]!.state = "closed";
    expect(decode(closedIssue)).toEqual({ ok: true, value: closedIssue });
  });

  it("refuses a relation type outside the S2 vocabulary", () => {
    // `related_context` joined the server vocabulary in S3 (S3 section 3.1); a
    // relation outside it still refuses the whole answer.
    for (const relation of ["follows_up", "Blocks", "", "contested", "Related_context"]) {
      const value = payload(); (value.typed_edges as Json[])[1]!.relation_type = relation;
      expect(decode(value).ok, relation).toBe(false);
    }
    for (const state of ["contested", "archived", "Closed"]) {
      const node = payload(); (node.nodes as Json[])[2]!.state = state;
      expect(decode(node).ok, state).toBe(false);
      const match = payload(); (match.issues_matching_root as Json[])[0]!.state = state;
      expect(decode(match).ok, state).toBe(false);
    }
  });

  it("refuses identifiers of the wrong family, a non-null cursor and an unknown completeness", () => {
    const root = payload(); (root.root as Json).record_id = "cmt_aaaaaaaa11111111";
    expect(decode(root).ok).toBe(false);
    const anchor = payload(); ((anchor.typed_edges as Json[])[1]!.evidence as Json[])[0]!.root_id = "cap_aaaaaaaa11111111";
    expect(decode(anchor).ok).toBe(false);
    const virtual = payload(); ((virtual.virtual_native_edges as Json[])[0]!.to as Json).family = "task";
    expect(decode(virtual).ok).toBe(false);
    // S3 lockstep (section 5): `next_cursor` may be an opaque base64url token,
    // so the refused cursor is one that is not.
    for (const next of ["sit aaaaaaaa", "", "x".repeat(2049), 7]) {
      const cursor = payload(); cursor.next_cursor = next;
      expect(decode(cursor).ok, String(next)).toBe(false);
    }
    const state = payload(); state.complete_state = "partial";
    expect(decode(state).ok).toBe(false);
  });
  it("decodes an S3 lineage page with a cursor and path steps", () => {
    // AT-024 (S3, web decoders): a paged answer (S3 sections 5, 7.1 and 7.2).
    const value = payload();
    Object.assign(value, {
      next_cursor: "eyJ2IjoxLCJwIjoibm9kZSJ9_-",
      complete_state: "restricted_evidence",
      qualifiers: ["restricted_evidence"],
    });
    // A contested related context between two members, and a restricted anchor.
    const edge = (value.typed_edges as Json[])[1]!;
    Object.assign(edge, {
      relation_type: "related_context", lifecycle_state: "contested",
      from: { family: "meeting", record_id: "mtg_aaaaaaaa11111111" },
      to: { family: "task", record_id: "tsk_aaaaaaaa11111111" },
    });
    (edge.evidence as Json[])[0]!.availability = "restricted";
    expect(decode(value)).toEqual({ ok: true, value });
    // Every node states how it was reached; following `reached_from` ends at the root.
    const nodes = (payload().nodes as Json[]);
    const root = payload().root as Json;
    for (const node of nodes) {
      let step: Json | undefined = node;
      for (let hops = 0; step !== undefined && step.reached_from !== null && hops < 5; hops += 1) {
        const from: Json = step.reached_from as Json;
        step = nodes.find((candidate) => candidate.family === from.family && candidate.record_id === from.record_id);
      }
      expect(step).toBeDefined();
      expect({ family: step!.family, record_id: step!.record_id }).toEqual(root);
    }
    // A path step carries exactly its edge kind's keys, and a root carries none.
    const typedKey = payload(); ((typedKey.nodes as Json[])[1]!.reached_via as Json).edge_type = "meeting_note_version_of";
    expect(decode(typedKey).ok).toBe(false);
    const half = payload(); (half.nodes as Json[])[1]!.reached_via = null;
    expect(decode(half).ok).toBe(false);
    // The qualifiers lead with the complete_state and the cuts are instants or null.
    const lead = payload(); lead.qualifiers = ["truncated_budget", "complete"];
    expect(decode(lead).ok).toBe(false);
    const cut = payload(); cut.known_at = "yesterday";
    expect(decode(cut).ok).toBe(false);
  });

  it("refuses a lifecycle state outside the S3 vocabulary", () => {
    // The S3 closed sets are exactly the server vocabulary (pinned from the
    // Python side by `test_record_lineage_s3_scope.py`).
    expect([...LINK_LIFECYCLE_STATES]).toEqual(["active", "ended", "contested"]);
    for (const state of ["disputed", "Contested", "proposed", "", "superseded"]) {
      const value = payload(); (value.typed_edges as Json[])[1]!.lifecycle_state = state;
      expect(decode(value).ok, state).toBe(false);
    }
    for (const availability of ["redacted", "withdrawn", "unavailable", "Restricted"]) {
      const value = payload(); ((value.typed_edges as Json[])[1]!.evidence as Json[])[0]!.availability = availability;
      expect(decode(value).ok, availability).toBe(false);
    }
    for (const completeness of ["source_not_integrated", "not_reportable", "historical_fields_partial"]) {
      const value = payload(); Object.assign(value, { complete_state: completeness, qualifiers: [completeness] });
      expect(decode(value).ok, completeness).toBe(false);
    }
  });

  it("decodes the S3.1 provenance labels and refuses values outside them", () => {
    // S3.1 (contract sections 4.3 and 7.6): a connected client's unreviewed
    // fact, its unverified claim and the writing client (local readers only).
    expect([...ACCEPTANCE_BASES]).toEqual(["user_confirmed", "client_identified"]);
    const client = payload();
    Object.assign((client.typed_edges as Json[])[1]!, {
      acceptance_basis: "client_identified", authority_class: "ordinary_reviewer",
      user_directed_claim: true, asserting_client_id: "synthetic-client-0001",
    });
    expect(decode(client)).toEqual({ ok: true, value: client });
    for (const basis of ["attested", "client_confirmed", "User_confirmed", ""]) {
      const value = payload(); (value.typed_edges as Json[])[1]!.acceptance_basis = basis;
      expect(decode(value).ok, basis).toBe(false);
    }
    for (const claim of ["true", 1, null]) {
      const value = payload(); (value.typed_edges as Json[])[1]!.user_directed_claim = claim;
      expect(decode(value).ok, String(claim)).toBe(false);
    }
    for (const id of ["", "x".repeat(257), 7]) {
      const value = payload(); (value.typed_edges as Json[])[1]!.asserting_client_id = id;
      expect(decode(value).ok, String(id)).toBe(false);
    }
    for (const key of ["user_directed_claim", "asserting_client_id"]) {
      const value = payload(); delete (value.typed_edges as Json[])[1]![key];
      expect(decode(value).ok, key).toBe(false);
    }
  });

  it("decodes the S6-3 Schedule node summaries and virtual edges, and nothing else", () => {
    // Schedule scenarios contract section 15.11.3a: the closed sets are exactly
    // the server vocabulary (`NATIVE_VIRTUAL_EDGE_ENDPOINTS`, the node labels of
    // section 15.6.3); every summary key is present, `null` included.
    expect([...NATIVE_VIRTUAL_EDGES]).toEqual(Object.keys(NATIVE_VIRTUAL_EDGE_ENDPOINTS));
    expect(NATIVE_VIRTUAL_EDGES).toHaveLength(9);
    expect([...SCHEDULE_DATA_CLASSES]).toEqual([
      "schedule_publication", "schedule_activity", "schedule_baseline", "schedule_scenario", "schedule_scenario_output",
    ]);
    expect([...SCHEDULE_AUTHORITIES]).toContain("source_bound_derived");
    expect([...SCHEDULE_TRUST_LEVELS]).toEqual(["source_bound_derived", "model_proposed"]);
    const id = (family: string): string => ({
      schedule_publication: "spub_aaaaaaaa11111111", schedule_activity: "sact_aaaaaaaa11111111",
      schedule_baseline: "sbl_aaaaaaaa11111111", scenario: "sscn_aaaaaaaa11111111",
      scenario_version: "sscv_aaaaaaaa11111111", scenario_output: "ssco_aaaaaaaa11111111",
      meeting_note_version: "mnote_aaaaaaaa11111111", meeting: "mtg_aaaaaaaa11111111",
    } as Record<string, string>)[family] ?? "x";
    const model = { authoritative: false, reportable: false, trust: "model_proposed" };
    const source = { authority: "source_bound_derived", authoritative: false, reportable: false, trust: "source_bound_derived" };
    const summaries: Record<string, Json> = {
      schedule_publication: { data_class: "schedule_publication", ...source, data_date: "2026-05-04", status: "complete", series_kind: "standard" },
      schedule_activity: { data_class: "schedule_activity", ...source, published_activity_id: "A100" },
      schedule_baseline: { data_class: "schedule_baseline", authority: "proposed", ...model, status: "proposed", label: null, effective_type: null },
      scenario: { data_class: "schedule_scenario", authority: "client_authored", ...model, origin_kind: "publication" },
      scenario_version: { data_class: "schedule_scenario", authority: "client_authored", ...model, version_no: 2, version_label: "what_if" },
      scenario_output: { data_class: "schedule_scenario_output", authority: "client_asserted", ...model, kind: "monte_carlo", iterations: 1000 },
    };
    const withNode = (family: string, schedule: Json | undefined): Json => {
      const value = payload();
      const node: Json = {
        family, record_id: id(family), depth: 1,
        reached_from: value.root, reached_via: { edge: "typed", link_id: "irl_aaaaaaaa11111111" },
      };
      if (schedule !== undefined) node.schedule = schedule;
      (value.nodes as Json[]).push(node);
      return value;
    };
    for (const [family, schedule] of Object.entries(summaries)) {
      const value = withNode(family, schedule);
      expect(decode(value), family).toEqual({ ok: true, value });
      // Required on its family, exact keys, never another family's summary.
      expect(decode(withNode(family, undefined)).ok, family).toBe(false);
      expect(decode(withNode(family, { ...schedule, name: "Synthetic" })).ok, family).toBe(false);
      expect(decode(withNode(family, { ...schedule, reportable: true })).ok, family).toBe(false);
      for (const key of Object.keys(schedule)) {
        const missing = { ...schedule }; delete missing[key];
        expect(decode(withNode(family, missing)).ok, `${family}.${key}`).toBe(false);
      }
      for (const [other, otherSchedule] of Object.entries(summaries)) {
        if (other !== family) expect(decode(withNode(family, otherSchedule)).ok, `${family}<-${other}`).toBe(false);
      }
    }
    expect(decode(withNode("task", summaries.scenario)).ok).toBe(false);
    // A revoked Baseline keeps its type and label; `operator_approved` iff typed.
    const revoked = { ...summaries.schedule_baseline, authority: "operator_approved", status: "revoked", label: "BL-1", effective_type: "contract" };
    expect(decode(withNode("schedule_baseline", revoked)).ok).toBe(true);
    expect(decode(withNode("schedule_baseline", { ...revoked, authority: "proposed" })).ok).toBe(false);
    expect(decode(withNode("schedule_baseline", { ...revoked, authoritative: true })).ok).toBe(false);
    expect(decode(withNode("schedule_baseline", { ...revoked, status: "approved", authoritative: true })).ok).toBe(true);
    // Every Schedule edge between exactly its two families; a Schedule edge is never a path step.
    for (const [edgeType, [from, to]] of Object.entries(NATIVE_VIRTUAL_EDGE_ENDPOINTS)) {
      for (const source of RECORD_FAMILIES) {
        const value = payload();
        value.virtual_native_edges = [{ edge_type: edgeType, from: { family: source, record_id: id(source) }, to: { family: to, record_id: id(to) } }];
        expect(decode(value).ok, `${edgeType}:${source}`).toBe(source === from && id(source) !== "x");
      }
      if (edgeType !== "meeting_note_version_of") {
        const step = payload(); (step.nodes as Json[])[1]!.reached_via = { edge: "virtual", edge_type: edgeType };
        expect(decode(step).ok, edgeType).toBe(false);
      }
    }
    const unknownEdge = payload(); ((unknownEdge.virtual_native_edges as Json[])[0]!).edge_type = "scenario_child_of";
    expect(decode(unknownEdge).ok).toBe(false);
  });
});
