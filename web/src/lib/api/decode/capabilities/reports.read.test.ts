// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsRead } from "./reports.read";

const ARTIFACT = {
  report_id: "rpt_aaaaaaaa11111111",
  report_run_id: "rrun_aaaaaaaa11111111",
  cycle_run_id: "micr_aaaaaaaa11111111",
  focus_area_id: "communications",
  stage: "collector",
  artifact_kind: "collector_candidates",
  source_lane: null,
  report_date: "2026-08-20",
  title: "E2E morning brief collector",
  artifact_state: "final",
  content_sha256: "a".repeat(64),
  content_bytes: 48,
  committed_at: "2026-08-20T12:00:00Z",
  version: 1,
  supersedes_report_id: null,
  dependency_report_ids: [],
  provenance: [
    {
      source_system: "synthetic",
      source_ref: "src_aaaaaaaa11111111",
      relation: "supports",
      source_url: null,
    },
  ],
  body_markdown: "# Morning Brief\n\n- scraped item one",
  structured_content: { lane: "persisted", marker: "not-from-markdown" },
};

describe("decodeReportsRead", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeReportsRead(ARTIFACT);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.structured_content).toEqual({
        lane: "persisted",
        marker: "not-from-markdown",
      });
      expect(decoded.value.body_markdown).toBe("# Morning Brief\n\n- scraped item one");
    }
  });

  it("accepts a payload that omits body_markdown and structured_content", () => {
    const { body_markdown: _body, structured_content: _structured, ...rest } = ARTIFACT;
    const decoded = decodeReportsRead(rest);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.body_markdown).toBeUndefined();
      expect(decoded.value.structured_content).toBeUndefined();
    }
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReportsRead({ ...ARTIFACT, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when a required field is missing", () => {
    const { report_id: _, ...rest } = ARTIFACT;
    expect(decodeReportsRead(rest).ok).toBe(false);
  });

  it("does not treat an omitted provenance array as empty success", () => {
    const { provenance: _, ...rest } = ARTIFACT;
    expect(decodeReportsRead(rest).ok).toBe(false);
    const empty = decodeReportsRead({ ...ARTIFACT, provenance: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.provenance).toEqual([]);
  });

  it("fails closed when structured_content is an array", () => {
    expect(decodeReportsRead({ ...ARTIFACT, structured_content: ["scraped"] }).ok).toBe(false);
  });

  it("fails closed when structured_content is a string", () => {
    expect(decodeReportsRead({ ...ARTIFACT, structured_content: "# Morning Brief" }).ok).toBe(
      false,
    );
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeReportsRead({ ...ARTIFACT, stage: "planner" }).ok).toBe(false);
    expect(decodeReportsRead({ ...ARTIFACT, artifact_kind: "brief" }).ok).toBe(false);
    expect(decodeReportsRead({ ...ARTIFACT, artifact_state: "draft" }).ok).toBe(false);
  });
});
