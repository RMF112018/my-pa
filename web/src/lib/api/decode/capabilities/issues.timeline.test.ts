// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeIssuesTimeline, HANDOFF_CORRECTION_ACTIONS, TIMELINE_ENTRY_KINDS } from "./issues.timeline";

/*
 * AT-024 (S3, web decoders): `issues.timeline` (S3 contract section 7.3). The
 * canonical page is the committed Python dump (`_issues_timeline` in
 * `tests/contract/test_bff_success_decoder_parity.py`), so a renamed key fails
 * both sides; the closed sets are pinned to the server vocabulary from the
 * Python side by `tests/architecture/test_record_lineage_s3_scope.py`.
 */
const canonical = fixtures["issues.timeline"];
type Json = Record<string, unknown>;
function payload(): Json { return structuredClone(canonical) as Json; }
function entries(value: Json): Json[] { return value.entries as Json[]; }
const decode = decodeIssuesTimeline;

describe("issues.timeline strict canonical success", () => {
  it("decodes an Issue timeline page", () => {
    expect(decode(canonical)).toEqual({ ok: true, value: canonical });
    const kinds = entries(payload()).map((entry) => entry.kind);
    expect(new Set(kinds)).toEqual(new Set(TIMELINE_ENTRY_KINDS));
    expect([...TIMELINE_ENTRY_KINDS]).toEqual([
      "issue_revision", "project_link", "membership", "association", "handoff", "handoff_correction", "native_event",
    ]);
    expect([...HANDOFF_CORRECTION_ACTIONS]).toEqual(["retime", "void"]);
    // An as-of page: no native entries, partial, no cursor.
    const asOf = payload();
    asOf.entries = entries(asOf).filter((entry) => entry.plane === "lineage");
    Object.assign(asOf, { complete_state: "partial_native_history", qualifiers: ["partial_native_history"], next_cursor: null });
    expect(decode(asOf).ok).toBe(true);
    // A restart page discloses nothing.
    const restart = payload();
    Object.assign(restart, { entries: [], complete_state: "scope_changed_restart_required", qualifiers: ["scope_changed_restart_required"], next_cursor: null });
    expect(decode(restart).ok).toBe(true);
    // A voided handoff and a void correction.
    const voided = payload();
    const handoff = entries(voided).find((entry) => entry.kind === "handoff")!;
    handoff.voided = true;
    const correction = entries(voided).find((entry) => entry.kind === "handoff_correction")!;
    Object.assign(correction, { action: "void", correction_action: "void", corrected_effective_at: null });
    expect(decode(voided).ok).toBe(true);
  });

  it("refuses an unknown timeline entry kind", () => {
    for (const kind of ["decision", "record_event", "Native_event", "", "irec"]) {
      const value = payload(); entries(value)[0]!.kind = kind;
      expect(decode(value).ok, kind).toBe(false);
    }
    for (const plane of ["projection", "Native"]) {
      const value = payload(); entries(value)[0]!.plane = plane;
      expect(decode(value).ok, plane).toBe(false);
    }
  });

  it("refuses unknown keys, another kind's keys and a missing key", () => {
    for (const [index, entry] of entries(payload()).entries()) {
      for (const key of ["unexpected", "principal_id", "evidence", "project_name", "hidden_count"]) {
        const value = payload(); entries(value)[index]![key] = "synthetic-private";
        expect(decode(value).ok, `${String(entry.kind)}.${key}`).toBe(false);
      }
      for (const key of Object.keys(entry)) {
        const value = payload(); delete entries(value)[index]![key];
        expect(decode(value).ok, `${String(entry.kind)} without ${key}`).toBe(false);
      }
    }
    // A Project link entry never carries a title; an Issue revision never a link.
    const project = payload();
    entries(project).find((entry) => entry.kind === "project_link")!.title = "Synthetic Project name";
    expect(decode(project).ok).toBe(false);
    const revision = payload();
    entries(revision).find((entry) => entry.kind === "issue_revision")!.link_id = "irl_aaaaaaaa11111111";
    expect(decode(revision).ok).toBe(false);
  });

  it("holds the native entry rules", () => {
    // A partial native entry carries no field values.
    const partial = payload();
    const task = entries(partial).find((entry) => entry.kind === "native_event" && entry.recorded_fields === null)!;
    task.recorded_fields = { lifecycle_state: "pending", ball_in_court: [] };
    expect(decode(partial).ok).toBe(false);
    task.historical_fields_partial = false;
    // ... and only a Constraint event may carry recorded fields.
    expect(decode(partial).ok).toBe(false);
    // A lineage entry is never partial.
    const lineage = payload(); entries(lineage)[0]!.historical_fields_partial = true;
    expect(decode(lineage).ok).toBe(false);
    // The entry id carries its kind's prefix; the native record its family's.
    const id = payload(); entries(id)[0]!.entry_id = "rcev_aaaaaaaa11111111";
    expect(decode(id).ok).toBe(false);
    const native = payload();
    ((entries(native).find((entry) => entry.kind === "native_event")!.native) as Json).record_id = "cmt_aaaaaaaa11111111";
    expect(decode(native).ok).toBe(false);
  });

  it("refuses a malformed cursor and qualifiers that do not lead with the state", () => {
    for (const next of ["sit aaaaaaaa", "", "x".repeat(2049), 7]) {
      const value = payload(); value.next_cursor = next;
      expect(decode(value).ok, String(next)).toBe(false);
    }
    const qualifiers = payload(); qualifiers.qualifiers = ["truncated_budget"];
    expect(decode(qualifiers).ok).toBe(false);
  });
});
