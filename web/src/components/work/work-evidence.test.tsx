import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskDetailView } from "@/components/work/work-detail";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Work evidence", () => {
  it("shows server metadata and reveals closure evidence only after explicit action", async () => {
    const origin = "cap_origin0001origin0001";
    const closure = "cap_closure001closure001";
    const closureHistory = "tsh_closure001closure001";
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === "/api/tasks/tsk_aaaaaaaa11111111") {
        return Response.json({
          task: {
            task_id: "tsk_aaaaaaaa11111111",
            title: "Close the permit review",
            description: null,
            lifecycle_state: "completed",
            evidence_state: "accepted",
            origin_evidence_ref: origin,
            closure_evidence_ref: closure,
            accepted_by_review_decision_id: "rdec_aaaaaaaa11111111",
            acceptance_kind: "review",
            closure_history_id: closureHistory,
            version: 3,
            priority: null,
            due_at: null,
            scheduled_at: null,
            deferred_until: null,
            archived_at: null,
            commitment_id: null,
            role: null,
            project_id: null,
            situation_id: null,
            opened_at: "2026-08-20T12:00:00Z",
            closed_at: "2026-08-22T12:00:00Z",
            created_at: "2026-08-20T12:00:00Z",
            updated_at: "2026-08-22T12:00:00Z",
          },
        });
      }
      if (path.includes("/history")) {
        return Response.json({
          history: [{
            history_id: closureHistory,
            action: "transitioned",
            actor: "principal",
            outcome: "applied",
            before_version: 2,
            after_version: 3,
            occurred_at: "2026-08-22T12:00:00Z",
            recorded_at: "2026-08-22T12:00:00Z",
          }],
        });
      }
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      if (path === "/api/reveal") {
        return Response.json({
          shape: "backend",
          state: "unavailable",
          result: {
            state: "unavailable",
            gap: "derivation_has_not_completed_for_every_version",
            subject_kind: "capture",
            capture_id: closure,
            versions: [],
            spans: [],
            proposed: [],
            accepted: [],
            versions_with_completed_derivation: 0,
          },
          disclosure: {
            scope: "reveal:knowledge.reveal",
            coverage: "unavailable",
            freshnessAt: "2026-08-22T12:00:00Z",
            authority: "accepted",
            limitations: ["evidence_scope_was_not_searched"],
            truncated: false,
          },
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId="tsk_aaaaaaaa11111111" />);

    expect(await screen.findByText("Recorded origin evidence")).toBeTruthy();
    expect(screen.getByText("review")).toBeTruthy();
    expect(screen.getByText(/Review decision rdec_aaaaaaaa11111111/)).toBeTruthy();
    expect(screen.getByText(/History receipt tsh_closure001closure001/)).toBeTruthy();
    expect(screen.getByText("Closure receipt")).toBeTruthy();
    expect(fetcher.mock.calls.some(([path]) => String(path) === "/api/reveal")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "View closure evidence" }));
    expect(screen.getByRole("dialog", { name: "Why am I seeing this?" })).toBeTruthy();
    expect(fetcher.mock.calls.some(([path]) => String(path) === "/api/reveal")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await waitFor(() => expect(screen.getByTestId("reveal-unavailable")).toBeTruthy());
    const revealCall = fetcher.mock.calls.find(([path]) => String(path) === "/api/reveal");
    expect(JSON.parse(String(revealCall?.[1]?.body))).toEqual({ subjectId: closure });
  });

  it("states that closure evidence metadata is unavailable instead of inventing a reference", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      return Response.json({ task: {
        task_id: "tsk_bbbbbbbb22222222", title: "Legacy terminal task", description: null,
        lifecycle_state: "completed", evidence_state: "unavailable",
        origin_evidence_ref: "cap_origin0002origin0002", closure_evidence_ref: null,
        accepted_by_review_decision_id: null, acceptance_kind: null, closure_history_id: null,
        version: 1, priority: null, due_at: null, scheduled_at: null, deferred_until: null,
        archived_at: null, commitment_id: null, role: null, project_id: null, situation_id: null,
        opened_at: "2026-08-20T12:00:00Z", closed_at: "2026-08-22T12:00:00Z",
        created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
      } });
    }));

    render(<TaskDetailView taskId="tsk_bbbbbbbb22222222" />);
    expect(await screen.findByText("Task is terminal, but closure evidence metadata was unavailable.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "View closure evidence" })).toBeNull();
  });
});
