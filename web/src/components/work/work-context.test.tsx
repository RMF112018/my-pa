import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CommitmentDetailView, TaskDetailView } from "@/components/work/work-detail";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK = {
  task_id: "tsk_aaaaaaaa11111111", title: "Coordinate review", description: null,
  lifecycle_state: "open", evidence_state: "accepted",
  origin_evidence_ref: "cap_origin0001origin0001", closure_evidence_ref: null,
  accepted_by_review_decision_id: "rdec_aaaaaaaa11111111", acceptance_kind: "review",
  closure_history_id: null, version: 2, priority: null, due_at: null, scheduled_at: null,
  deferred_until: null, archived_at: null, commitment_id: null, role: null,
  project_id: "prj_aaaaaaaa11111111", situation_id: "sit_aaaaaaaa11111111",
  opened_at: "2026-08-20T12:00:00Z", closed_at: null,
  created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
};

const COMMITMENT = {
  commitment_id: "cmt_aaaaaaaa11111111", title: "Return revised permit log", description: null,
  direction: "owed_to_principal", state: "open", counterparty_person_id: "per_aaaaaaaa11111111",
  counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Sam Rivera" },
  due_date: null, created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
  version: 2, evidence_state: "proposed", origin_evidence_ref: "cap_origin0002origin0002",
  closure_evidence_ref: null, accepted_by_review_decision_id: null, closed_at: null,
};

describe("Work detail context", () => {
  it("renders Project and Situation as unresolved references, not guessed names", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      return Response.json({ task: TASK });
    }));

    render(<TaskDetailView taskId={TASK.task_id} />);

    expect(await screen.findByText("Unresolved Project context")).toBeTruthy();
    expect(screen.getByText("Reference prj_aaaaaaaa11111111")).toBeTruthy();
    expect(screen.getByText("Unresolved Situation context")).toBeTruthy();
    expect(screen.getByText("Reference sit_aaaaaaaa11111111")).toBeTruthy();
    expect(screen.getByText("review")).toBeTruthy();
    expect(screen.getByText(/Review decision rdec_aaaaaaaa11111111/)).toBeTruthy();
  });

  it("renders a completed same-Principal follow-up Task returned with Commitment detail", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path === `/api/commitments/${COMMITMENT.commitment_id}`) return Response.json({
        commitment: COMMITMENT,
        follow_up_task: { ...TASK, title: "Ask Sam for the permit log", lifecycle_state: "completed" },
        counterparty_options: [COMMITMENT.counterparty],
      });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);

    render(<CommitmentDetailView commitmentId={COMMITMENT.commitment_id} />);

    const link = await screen.findByRole("link", { name: "Ask Sam for the permit log" });
    expect(link.getAttribute("href")).toBe(`/work/tasks/${TASK.task_id}`);
    expect(screen.getByText("Task state: completed")).toBeTruthy();
    expect(fetcher.mock.calls.some(([input]) => String(input).includes("waiting-on"))).toBe(false);
  });

  it.each([
    [{ follow_up_task: null }, "No follow-up Task is linked."],
    [{}, "Follow-up Task context is unavailable."],
  ])("distinguishes an explicit empty projection from unavailable", async (projection, expected) => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/history")) return Response.json({ history: [] });
      return Response.json({ commitment: COMMITMENT, ...projection, counterparty_options: [COMMITMENT.counterparty] });
    }));

    render(<CommitmentDetailView commitmentId={COMMITMENT.commitment_id} />);

    expect(await screen.findByText(expected)).toBeTruthy();
  });
});
