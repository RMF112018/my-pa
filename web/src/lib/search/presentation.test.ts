import { describe, expect, it } from "vitest";
import type { CaptureSearchMatch } from "@/lib/api/decode/capabilities/capture.search";
import type { CommitmentListEntry } from "@/lib/api/decode/capabilities/commitments.search";
import type { EntitySummary } from "@/lib/api/decode/capabilities/entities.search";
import type { KnowledgeSearchMatch } from "@/lib/api/decode/capabilities/knowledge.search";
import type { ReportSearchMatch } from "@/lib/api/decode/capabilities/reports.search";
import type { TaskListEntry } from "@/lib/api/decode/capabilities/tasks.search";
import {
  captureSearchHref,
  knowledgeSearchHref,
  presentFederatedHits,
  SEARCH_DOMAIN_ORDER,
  type FederatedHit,
} from "@/lib/search/presentation";

const TASK_A: TaskListEntry = {
  task_id: "tsk_aaaaaaaa11111111",
  title: "First task",
  lifecycle_state: "open",
  priority: "p2",
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 1,
};

const TASK_B: TaskListEntry = {
  ...TASK_A,
  task_id: "tsk_bbbbbbbb22222222",
  title: "Second task",
};

const COMMITMENT: CommitmentListEntry = {
  commitment_id: "cmt_aaaaaaaa11111111",
  direction: "owed_by_principal",
  state: "open",
  counterparty_person_id: null,
  title: "Follow up",
  description: null,
  due_date: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 1,
  counterparty: null,
};

const CAPTURE: CaptureSearchMatch = {
  capture_id: "cap_aaaaaaaa11111111",
  version_id: "capver_aaaaaaaa11111111",
  version_number: 2,
  character_count: 48,
  recorded_at: "2026-01-01T00:00:00Z",
};

const REPORT: ReportSearchMatch = {
  report_id: "rpt_aaaaaaaa11111111",
  title: "Morning brief",
  snippet: "collector candidates",
  cycle_run_id: "micr_aaaaaaaa11111111",
  stage: "collector",
  artifact_kind: "collector_candidates",
};

const ENTITY: EntitySummary = {
  entity_id: "ent_aaaaaaaa11111111",
  entity_type: "person",
  canonical_name: "pat synthetic",
  display_name: "Pat Synthetic",
  status: "active",
  affiliated_organizations: [],
  project_roles: [],
};

const KNOWLEDGE: KnowledgeSearchMatch = {
  knowledge_id: "kno_aaaaaaaa11111111",
  label: "Stored note",
  snippet: "a lexical snippet",
  rank: "strong",
  source_id: "src_aaaaaaaa11111111",
  source_object_id: "sobj_aaaaaaaa11111111",
  version_id: "kver_aaaaaaaa11111111",
};

describe("federated search presentation", () => {
  it("groups in deterministic domain order and preserves per-domain upstream order", () => {
    const hits: FederatedHit[] = [
      { domain: "entities", item: ENTITY },
      { domain: "tasks", item: TASK_B },
      { domain: "knowledge", item: KNOWLEDGE },
      { domain: "tasks", item: TASK_A },
      { domain: "commitments", item: COMMITMENT },
      { domain: "capture", item: CAPTURE },
      { domain: "reports", item: REPORT },
    ];
    const groups = presentFederatedHits(hits, "enr_aaaaaaaa11111111");
    expect(groups.map((group) => group.domain)).toEqual([...SEARCH_DOMAIN_ORDER]);
    expect(groups.find((group) => group.domain === "tasks")?.hits.map((hit) => hit.key)).toEqual([
      TASK_B.task_id,
      TASK_A.task_id,
    ]);
    expect(groups.every((group) => !("score" in group) && group.hits.every((hit) => !("score" in hit)))).toBe(
      true,
    );
  });

  it("builds a capture href from IDs only and never copies capture text", () => {
    const secret = "SECRET_CAPTURE_BODY_MUST_NOT_LEAK";
    const hit = {
      domain: "capture",
      item: { ...CAPTURE, text: secret },
    } as FederatedHit;
    const groups = presentFederatedHits([hit]);
    const presented = groups[0]?.hits[0];
    expect(captureSearchHref(CAPTURE.capture_id, CAPTURE.version_id)).toBe(
      "/knowledge?captureId=cap_aaaaaaaa11111111&versionId=capver_aaaaaaaa11111111",
    );
    expect(presented?.href).toBe(
      "/knowledge?captureId=cap_aaaaaaaa11111111&versionId=capver_aaaaaaaa11111111",
    );
    expect(presented?.href).toContain("captureId=");
    expect(presented?.href).toContain("versionId=");
    expect(presented?.href).not.toContain("text=");
    expect(JSON.stringify(groups)).not.toContain(secret);
    expect(JSON.stringify(groups)).not.toContain("SECRET");
  });

  it("omits a knowledge href unless the search request actually had enrollmentId", () => {
    const without = presentFederatedHits([{ domain: "knowledge", item: KNOWLEDGE }]);
    expect(knowledgeSearchHref(KNOWLEDGE.knowledge_id, undefined)).toBeNull();
    expect(knowledgeSearchHref(KNOWLEDGE.knowledge_id, "")).toBeNull();
    expect(without[0]?.hits[0]?.href).toBeNull();
    expect(without[0]?.hits[0]?.label).toBe(KNOWLEDGE.label);
    expect(without[0]?.hits[0]?.rank).toBe("strong");

    const withEnrollment = presentFederatedHits(
      [{ domain: "knowledge", item: KNOWLEDGE }],
      "enr_aaaaaaaa11111111",
    );
    expect(withEnrollment[0]?.hits[0]?.href).toBe(
      "/knowledge?knowledgeId=kno_aaaaaaaa11111111&enrollmentId=enr_aaaaaaaa11111111",
    );
  });

  it("maps identity hrefs for tasks, commitments, reports, and entities", () => {
    const groups = presentFederatedHits([
      { domain: "tasks", item: TASK_A },
      { domain: "commitments", item: COMMITMENT },
      { domain: "reports", item: REPORT },
      { domain: "entities", item: ENTITY },
    ]);
    expect(groups.map((group) => group.hits[0]?.href)).toEqual([
      "/work/tasks/tsk_aaaaaaaa11111111",
      "/work/commitments/cmt_aaaaaaaa11111111",
      "/intelligence/reports/rpt_aaaaaaaa11111111",
      "/people/ent_aaaaaaaa11111111",
    ]);
  });

  it("keeps capture and knowledge rows visible when a truthful href cannot be built", () => {
    const capture = presentFederatedHits([
      { domain: "capture", item: { ...CAPTURE, version_id: "" } },
    ]);
    expect(capture[0]?.hits[0]?.href).toBeNull();
    expect(capture[0]?.hits[0]?.label).toBe(CAPTURE.capture_id);

    const knowledge = presentFederatedHits([{ domain: "knowledge", item: KNOWLEDGE }]);
    expect(knowledge[0]?.hits[0]?.href).toBeNull();
    expect(knowledge[0]?.hits[0]?.detail).toBe(KNOWLEDGE.snippet);
  });
});
