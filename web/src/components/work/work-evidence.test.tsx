import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
            origin_kind: "evidence",
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
      if (path.includes("/comments")) return Response.json({ comments: [] });
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
    await screen.findByTestId("task-technical-details");

    // Diagnostics are collapsed by default and history is not read on open.
    expect(screen.queryByText(new RegExp(closure))).toBeNull();
    expect(screen.queryAllByText(new RegExp(closureHistory))).toHaveLength(0);
    expect(fetcher.mock.calls.some(([path]) => String(path).includes("/history"))).toBe(false);

    await userEvent.click(screen.getByText("Technical details"));

    // Every diagnostic the previous primary-flow panel exposed is still reachable.
    expect(await screen.findByText(new RegExp(closure))).toBeTruthy();
    expect(screen.getByText(new RegExp(origin))).toBeTruthy();
    expect(screen.getByText(/rdec_aaaaaaaa11111111/)).toBeTruthy();
    // The closure history id appears both as provenance and on its history row.
    expect((await screen.findAllByText(new RegExp(closureHistory))).length).toBeGreaterThan(0);
    expect(screen.getByText("Closure receipt")).toBeTruthy();
    await waitFor(() =>
      expect(fetcher.mock.calls.some(([path]) => String(path).includes("/history"))).toBe(true),
    );
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
      if (path.includes("/comments")) return Response.json({ comments: [] });
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      return Response.json({ task: {
        task_id: "tsk_bbbbbbbb22222222", title: "Legacy terminal task", description: null,
        lifecycle_state: "completed", evidence_state: "unavailable",
        origin_kind: "evidence",
        origin_evidence_ref: "cap_origin0002origin0002", closure_evidence_ref: null,
        accepted_by_review_decision_id: null, acceptance_kind: null, closure_history_id: null,
        version: 1, priority: null, due_at: null, scheduled_at: null, deferred_until: null,
        archived_at: null, commitment_id: null, role: null, project_id: null, situation_id: null,
        opened_at: "2026-08-20T12:00:00Z", closed_at: "2026-08-22T12:00:00Z",
        created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
      } });
    }));

    render(<TaskDetailView taskId="tsk_bbbbbbbb22222222" />);
    await screen.findByTestId("task-technical-details");

    // Primary UX states the terminal outcome in product language.
    expect(screen.getByText("This task is closed.")).toBeTruthy();

    await userEvent.click(screen.getByText("Technical details"));

    // The diagnostic states the absence rather than inventing a reference, and
    // offers no reveal path for evidence that was never recorded.
    const identity = await screen.findByRole("region", { name: "Provenance" });
    const closureRow = within(identity).getByText("Closure evidence ref").parentElement;
    expect(closureRow?.textContent).not.toMatch(/cap_/);
    expect(screen.queryByRole("button", { name: "View closure evidence" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy closure evidence reference" })).toBeNull();
  });

  it("applies a terminal Task transition without fabricating closure evidence", async () => {
    const task = {
      task_id: "tsk_cccccccc33333333", title: "Close without evidence", description: null,
      lifecycle_state: "open", evidence_state: "accepted", origin_kind: "direct_principal",
      origin_evidence_ref: null, closure_evidence_ref: null, accepted_by_review_decision_id: null,
      acceptance_kind: "direct_principal", closure_history_id: null, version: 1, priority: null,
      due_at: null, scheduled_at: null, deferred_until: null, archived_at: null, commitment_id: null,
      role: null, project_id: null, situation_id: null, opened_at: "2026-08-20T12:00:00Z",
      closed_at: null as string | null, created_at: "2026-08-20T12:00:00Z",
      updated_at: "2026-08-20T12:00:00Z",
    };
    let current = task;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path.includes("/transition") && init?.method === "POST") {
        current = { ...task, lifecycle_state: "completed", version: 2, closed_at: "2026-08-22T12:00:00Z" };
        return Response.json({
          task: current,
          history: { history_id: "thst_cccccccc33333333", task_id: task.task_id, action: "transition_lifecycle", actor: "principal", outcome: "applied", before_version: 1, after_version: 2, occurred_at: "2026-08-22T12:00:00Z", recorded_at: "2026-08-22T12:00:00Z" },
          replayed: false,
        });
      }
      if (path === `/api/tasks/${task.task_id}`) return Response.json({ task: current });
      if (path.includes("/history")) return Response.json({ history: [] });
      if (path.includes("/comments")) return Response.json({ comments: [] });
      if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<TaskDetailView taskId={task.task_id} />);
    await screen.findByTestId("task-close-control");

    // Direct-Principal closure asks for no authored note anywhere in the flow.
    expect(screen.queryByLabelText("Closure note")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Close Task" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).queryByRole("textbox")).toBeNull();
    expect(confirmation.querySelector("input, textarea")).toBeNull();
    expect(fetcher.mock.calls.some(([path]) => String(path).includes("/transition"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Confirm Closed" }));
    await waitFor(() => {
      expect(fetcher.mock.calls.some(([path]) => String(path).includes("/transition"))).toBe(true);
    });
    const transitionCall = fetcher.mock.calls.find(([path]) => String(path).includes("/transition"));
    const body = JSON.parse(String(transitionCall?.[1]?.body));
    expect(body).toMatchObject({ toState: "completed", expectedVersion: 1, idempotencyKey: expect.any(String) });
    expect(body).not.toHaveProperty("closureEvidenceRef");
    expect(fetcher.mock.calls.some(([path]) => String(path) === "/api/capture")).toBe(false);
  });
});
