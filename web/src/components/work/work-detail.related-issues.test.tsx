import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { CommitmentDetailView, TaskDetailView } from "@/components/work/work-detail";

/*
 * AT-024 (S1, mounting): the Task and Commitment detail views each carry the
 * one related-Issue panel, fed by one lineage read for that record.
 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK = {
  task_id: "tsk_aaaaaaaa11111111", title: "Coordinate review", description: null,
  lifecycle_state: "open", evidence_state: "accepted",
  origin_kind: "evidence",
  origin_evidence_ref: "cap_origin0001origin0001", closure_evidence_ref: null,
  accepted_by_review_decision_id: "rdec_aaaaaaaa11111111", acceptance_kind: "review",
  closure_history_id: null, version: 2, priority: null, due_at: null, scheduled_at: null,
  deferred_until: null, archived_at: null, commitment_id: null, role: null,
  project_id: null, situation_id: null,
  opened_at: "2026-08-20T12:00:00Z", closed_at: null,
  created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
};

const COMMITMENT = {
  commitment_id: "cmt_aaaaaaaa11111111", title: "Return revised permit log", description: null,
  direction: "owed_to_principal", state: "open", counterparty_entity_id: "ent_aaaaaaaa11111111",
  counterparty: { entity_id: "ent_aaaaaaaa11111111", display_name: "Sam Rivera" },
  due_date: null, created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
  version: 2, evidence_state: "proposed", origin_evidence_ref: "cap_origin0002origin0002",
  closure_evidence_ref: null, accepted_by_review_decision_id: null, closed_at: null,
};

function lineageFor(family: "task" | "commitment", recordId: string) {
  const lineage = structuredClone(fixtures["records.lineage"]);
  const root = { family, record_id: recordId };
  lineage.root = root;
  lineage.nodes[0] = { family, record_id: recordId, depth: 0 };
  lineage.typed_edges[0]!.to = root;
  lineage.typed_edges[1]!.from = root;
  return { shape: "backend", ...lineage, disclosure: {} };
}

describe("related-Issue panel mounts", () => {
  it("mounts the related-Issue panel on the Task detail", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/records/task/${TASK.task_id}/related-issues`) return Response.json(lineageFor("task", TASK.task_id));
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path.includes("/comments")) return Response.json({ comments: [] });
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      if (path === `/api/tasks/${TASK.task_id}`) return Response.json({ task: TASK });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK.task_id} />);
    const panel = await screen.findByRole("region", { name: "Related Issues" });
    expect(await within(panel).findByText("Member of this Issue as work")).toBeInTheDocument();
    expect(within(panel).getByText(/Issue: Synthetic Issue/)).toBeInTheDocument();
    const lineageReads = fetcher.mock.calls.filter(([input]) => String(input).includes("/related-issues"));
    expect(lineageReads).toHaveLength(1);
  });

  it("mounts the related-Issue panel on the Commitment detail", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/records/commitment/${COMMITMENT.commitment_id}/related-issues`) return Response.json(lineageFor("commitment", COMMITMENT.commitment_id));
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path === `/api/commitments/${COMMITMENT.commitment_id}`) return Response.json({
        commitment: COMMITMENT,
        counterparty_options: [COMMITMENT.counterparty],
      });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);

    render(<CommitmentDetailView commitmentId={COMMITMENT.commitment_id} />);
    const panel = await screen.findByRole("region", { name: "Related Issues" });
    expect(await within(panel).findByText("Originated from a Meeting note version")).toBeInTheDocument();
    const lineageReads = fetcher.mock.calls.filter(([input]) => String(input).includes("/related-issues"));
    expect(lineageReads).toHaveLength(1);
  });
});
