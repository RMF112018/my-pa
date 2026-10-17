// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeRecordsLineage } from "./records.lineage";

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
    value.nodes = [{ family: "task", record_id: "tsk_aaaaaaaa11111111", depth: 0 }];
    value.typed_edges = [];
    value.virtual_native_edges = [];
    value.complete_state = "unresolved_ambiguity";
    expect(decode(value).ok).toBe(true);
    // A legacy Capture anchor and an archived Capture version node.
    const legacy = payload();
    const edge = (legacy.typed_edges as Json[])[1]!;
    edge.evidence = [{
      anchor_id: "ian_bbbbbbbb22222222", family: "capture", root_id: "cap_aaaaaaaa11111111",
      version_kind: "legacy_unversioned", version_id: null, source_version_no: null,
      passage_start_cp: null, passage_end_cp: null, role: "corroborates", availability: "archived",
    }];
    (legacy.nodes as Json[]).push({ family: "capture_version", record_id: "capver_aaaaaaaa11111111", depth: 1, availability: "archived" });
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

  it("refuses identifiers of the wrong family, a non-null cursor and an unknown completeness", () => {
    const root = payload(); (root.root as Json).record_id = "cmt_aaaaaaaa11111111";
    expect(decode(root).ok).toBe(false);
    const anchor = payload(); ((anchor.typed_edges as Json[])[1]!.evidence as Json[])[0]!.root_id = "cap_aaaaaaaa11111111";
    expect(decode(anchor).ok).toBe(false);
    const virtual = payload(); ((virtual.virtual_native_edges as Json[])[0]!.to as Json).family = "task";
    expect(decode(virtual).ok).toBe(false);
    const cursor = payload(); cursor.next_cursor = "sit_aaaaaaaa11111111";
    expect(decode(cursor).ok).toBe(false);
    const state = payload(); state.complete_state = "partial";
    expect(decode(state).ok).toBe(false);
  });
});
