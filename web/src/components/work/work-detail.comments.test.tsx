import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskDetailView } from "@/components/work/work-detail";
import type { TaskDetail } from "@/contracts/work";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";

const TASK: TaskDetail = {
  task_id: TASK_ID,
  title: "Coordinate the review",
  lifecycle_state: "in_progress",
  priority: null,
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-10T12:00:00Z",
  version: 4,
  description: null,
  evidence_state: "accepted",
  origin_kind: "direct_principal",
  origin_evidence_ref: null,
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  acceptance_kind: null,
  closure_history_id: null,
  commitment_id: null,
  role: null,
  project_id: null,
  situation_id: null,
  opened_at: "2026-09-01T12:00:00Z",
  closed_at: null,
};

const COMMENT = {
  comment_id: "tcm_aaaaaaaa11111111",
  task_id: TASK_ID,
  body: "Reviewer confirmed the revised scope.",
  author_kind: "principal" as const,
  author_id: "prin_aaaaaaaa11111111",
  created_at: "2026-09-11T12:00:00Z",
};

function json(data: unknown, status = 200) {
  const body = status >= 400 ? { error: { message: "gateway unavailable", code: "unavailable" } } : data;
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** Records every comment-create attempt so identity can be compared across a retry. */
function commentStub(postOutcomes: readonly (number | "throw")[]) {
  const posted: { body: string; idempotencyKey: string }[] = [];
  let persisted: readonly (typeof COMMENT)[] = [];
  let post = 0;
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/comments") && method === "POST") {
      const body = JSON.parse(String(init?.body)) as { body: string; idempotencyKey: string };
      posted.push(body);
      const outcome = postOutcomes[post] ?? 200;
      post += 1;
      if (outcome === "throw") throw new TypeError("Failed to fetch");
      if (outcome >= 400) return json(null, outcome);
      persisted = [{ ...COMMENT, body: body.body }];
      return json({ comment: persisted[0], replayed: false });
    }
    if (path.includes("/comments")) return json({ comments: persisted });
    if (path.includes("/history")) return json({ history: [] });
    if (path === "/api/commitments?pageSize=100") return json({ commitments: [] });
    if (path === `/api/tasks/${TASK_ID}`) return json({ task: TASK });
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  return { fetcher, posted };
}

async function addComment(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(await screen.findByLabelText("Add comment"), text);
  await user.click(screen.getByRole("button", { name: "Add comment" }));
}

describe("Task comments through the shared mutation coordinator", () => {
  it("persists one comment and shows it in the thread", async () => {
    const user = userEvent.setup();
    const { fetcher, posted } = commentStub([200]);
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_ID} />);
    await addComment(user, "Reviewer confirmed the revised scope.");

    expect(await screen.findByText("Reviewer confirmed the revised scope.")).toBeTruthy();
    expect(posted).toHaveLength(1);
    expect(posted[0].idempotencyKey).toMatch(/^task-comment-/);
  });

  it("reuses the same idempotency key when an ambiguous comment is retried", async () => {
    const user = userEvent.setup();
    // A transport-level failure is ambiguous: the comment may already be persisted.
    const { fetcher, posted } = commentStub(["throw", 200]);
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_ID} />);
    await addComment(user, "Ambiguous comment");

    const retry = await screen.findByRole("button", { name: "Retry" });
    await user.click(retry);

    await waitFor(() => expect(posted).toHaveLength(2));
    // The retried attempt carries the identical key and body, so the backend can
    // recognise the replay instead of persisting the comment twice.
    expect(posted[1].idempotencyKey).toBe(posted[0].idempotencyKey);
    expect(posted[1].body).toBe(posted[0].body);
  });

  it("keeps a failed comment visible and truthful rather than pretending it persisted", async () => {
    const user = userEvent.setup();
    const { fetcher } = commentStub([503]);
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_ID} />);
    await addComment(user, "Never persisted");

    const row = await screen.findByTestId(/task-comment-pending-/);
    expect(row.getAttribute("data-status")).toBe("failed");
    expect(row.textContent).toContain("Never persisted");
    // The failed body is not presented as part of the persisted thread.
    expect(screen.queryByRole("listitem", { name: "Never persisted" })).toBeNull();
  });

  it("does not offer a comment composer before the canonical Task hydrates", async () => {
    const { fetcher } = commentStub([200]);
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_ID} />);
    // Before hydration there is no detail at all, so no composer can submit.
    expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull();
    expect(await screen.findByLabelText("Add comment")).toBeTruthy();
  });

  it("offers no edit or delete affordance on a persisted comment", async () => {
    const user = userEvent.setup();
    const { fetcher } = commentStub([200]);
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_ID} />);
    await addComment(user, "Reviewer confirmed the revised scope.");
    await screen.findByText("Reviewer confirmed the revised scope.");

    expect(screen.queryByRole("button", { name: /edit|delete|remove/i })).toBeNull();
  });
});
