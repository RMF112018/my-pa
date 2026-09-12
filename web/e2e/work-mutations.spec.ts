import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

async function api<T>(
  page: Page,
  path: string,
  options: { method?: string; body?: Record<string, unknown> } = {},
): Promise<ApiAnswer<T>> {
  return page.evaluate(
    async ({ target, method, payload }) => {
      const response = await fetch(target, {
        method: method ?? "GET",
        cache: "no-store",
        headers: payload ? { "content-type": "application/json" } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      });
      return { status: response.status, body: (await response.json()) as T };
    },
    { target: path, method: options.method, payload: options.body },
  );
}

function key(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("real stack preserves deliberate Task and Commitment mutation semantics", async ({ page }) => {
  test.setTimeout(180_000);
  const marker = `${test.info().project.name}-${Date.now()}`;
  const commitmentTitle = `E2E obligation ${marker}`;
  const taskTitle = `E2E follow-up ${marker}`;
  const reappliedTitle = `${taskTitle} reapplied`;

  await page.goto(`/work?view=commitments&commitment=all&q=${encodeURIComponent(marker)}`);
  await page.getByRole("button", { name: "New commitment" }).click();
  const commitmentCreate = page.getByRole("heading", { name: "Create commitment" }).locator("..");
  await commitmentCreate.getByLabel("Summary").fill(commitmentTitle);
  await commitmentCreate.getByLabel("Counterparty").selectOption({ label: "E2E Synthetic Counterparty" });
  await commitmentCreate.getByLabel("Direction").selectOption("owed_to_principal");
  await commitmentCreate.getByLabel("Origin note").fill("Synthetic Commitment evidence in the disposable browser database.");
  await commitmentCreate.getByRole("button", { name: "Create commitment" }).click();
  await expect(page.getByRole("link", { name: new RegExp(commitmentTitle) })).toBeVisible();

  const commitmentSearch = await api<{ commitments: { commitment_id: string; state: string }[] }>(
    page,
    `/api/commitments?q=${encodeURIComponent(marker)}&pageSize=50`,
  );
  expect(commitmentSearch.status).toBe(200);
  const commitment = commitmentSearch.body.commitments.find((item) => item.state === "open");
  expect(commitment).toBeTruthy();

  await page.goto(`/work?view=unscheduled&q=${encodeURIComponent(marker)}`);
  await page.getByRole("button", { name: "New task" }).click();
  const taskCreate = page.getByRole("heading", { name: "Create task" }).locator("..");
  await taskCreate.getByLabel("Title").fill(taskTitle);
  await taskCreate.getByLabel("Commitment").selectOption({ label: commitmentTitle });
  await taskCreate.getByLabel("Role").selectOption("follow_up");
  await taskCreate.getByRole("button", { name: "Create task" }).click();
  const taskTrigger = page.getByRole("link", { name: new RegExp(taskTitle) });
  await expect(taskTrigger).toBeVisible();

  const taskSearch = await api<{ tasks: { task_id: string }[] }>(
    page,
    `/api/tasks?q=${encodeURIComponent(marker)}&pageSize=50&workView=unscheduled&archived=exclude`,
  );
  expect(taskSearch.status).toBe(200);
  const taskId = taskSearch.body.tasks[0]?.task_id;
  expect(taskId).toBeTruthy();

  // Commitment and Role are no longer editable from Task detail: the compact
  // sheet states them as Context labels and owns no linkage form. The linkage
  // semantics this spec has always guarded are therefore driven through the
  // canonical endpoint, and the resulting *product language* is read back from
  // the Context disclosure.
  const linkedBefore = await api<{ task: { version: number; commitment_id: string | null } }>(
    page,
    `/api/tasks/${taskId}`,
  );
  expect(linkedBefore.body.task.commitment_id).toBe(commitment!.commitment_id);
  const unlink = await api<Record<string, unknown>>(page, `/api/tasks/${taskId}`, {
    method: "PATCH",
    body: {
      expectedVersion: linkedBefore.body.task.version,
      clearFields: ["commitment_id", "role"],
      idempotencyKey: key("e2e-unlink-task"),
    },
  });
  expect(unlink.status).toBe(200);
  const unlinked = await api<{ task: { commitment_id: string | null; version: number } }>(page, `/api/tasks/${taskId}`);
  expect(unlinked.body.task.commitment_id).toBeNull();

  const relink = await api<Record<string, unknown>>(page, `/api/tasks/${taskId}`, {
    method: "PATCH",
    body: {
      commitmentId: commitment!.commitment_id,
      role: "follow_up",
      expectedVersion: unlinked.body.task.version,
      idempotencyKey: key("e2e-relink-task"),
    },
  });
  expect(relink.status).toBe(200);
  const relinked = await api<{ task: { commitment_id: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(relinked.body.task.commitment_id).toBe(commitment!.commitment_id);

  await taskTrigger.click();
  const taskSheet = page.getByTestId("task-compact-sheet");
  await expect(taskSheet.getByRole("heading", { name: taskTitle })).toBeVisible();

  // Context is a progressive disclosure: the linkage is stated in words there,
  // never as a raw identifier in the primary surface.
  const context = taskSheet.getByTestId("task-context-section");
  await context.locator("summary").click();
  await expect(context.getByText(commitmentTitle)).toBeVisible();
  await expect(context.getByText("Follow up")).toBeVisible();

  // Bounded field saves replace the whole-Task atomic patch form.
  await taskSheet.getByRole("textbox", { name: "Description", exact: true }).fill("Safe atomic browser edit");
  await taskSheet.getByRole("button", { name: "Save description" }).click();
  await expect(taskSheet.getByText("Task saved.")).toBeVisible();
  const described = await api<{ task: { description: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(described.body.task.description).toBe("Safe atomic browser edit");

  await taskSheet.getByRole("combobox", { name: "Priority" }).selectOption({ label: "High" });
  await expect(taskSheet.getByText("Task saved.")).toBeVisible();
  await expect
    .poll(async () => (await api<{ task: { priority: string | null } }>(page, `/api/tasks/${taskId}`)).body.task.priority)
    .toBe("p2");

  const beforeConflict = await api<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
  expect(beforeConflict.status).toBe(200);
  await taskSheet.getByRole("textbox", { name: "Title" }).fill(reappliedTitle);
  const concurrent = await api<Record<string, unknown>>(page, `/api/tasks/${taskId}`, {
    method: "PATCH",
    body: {
      description: "Concurrent canonical edit",
      expectedVersion: beforeConflict.body.task.version,
      idempotencyKey: key("e2e-concurrent-task"),
    },
  });
  expect(concurrent.status).toBe(200);
  await taskSheet.getByRole("button", { name: "Save title" }).click();
  await expect(taskSheet.getByTestId("task-changed-elsewhere")).toBeVisible();
  const reapply = taskSheet.getByRole("button", { name: "Reapply my change to the latest version" });
  await expect(reapply).toBeVisible();
  await reapply.click();
  await expect(taskSheet.getByRole("heading", { name: reappliedTitle })).toBeVisible();
  const reappliedRead = await api<{ task: { title: string; description: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(reappliedRead.body.task.title).toBe(reappliedTitle);
  expect(reappliedRead.body.task.description).toBe("Concurrent canonical edit");

  // The Status control issues the state change immediately: there is no
  // separate apply step, and the human label is the only vocabulary offered.
  const statusControl = taskSheet.getByTestId("task-status-control");
  await expect(statusControl.getByRole("combobox")).toBeVisible();
  await statusControl.getByRole("combobox").selectOption({ label: "In progress" });
  await expect(taskSheet.getByText("Status updated.")).toBeVisible();
  await expect(taskSheet.getByText(/^In progress · /)).toBeVisible();
  const running = await api<{ task: { lifecycle_state: string } }>(page, `/api/tasks/${taskId}`);
  expect(running.body.task.lifecycle_state).toBe("in_progress");

  // Closing costs exactly two activations and never asks for authored text.
  await taskSheet.getByRole("button", { name: "Close Task", exact: true }).click();
  const closeConfirmation = taskSheet.getByRole("alertdialog");
  await expect(closeConfirmation).toBeVisible();
  await expect(closeConfirmation.getByRole("button", { name: "Keep open" })).toBeVisible();
  await closeConfirmation.getByRole("button", { name: "Confirm Closed" }).click();
  await expect(taskSheet.getByText("Task closed.")).toBeVisible();
  await expect(taskSheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
  await expect(statusControl).toHaveAttribute("data-terminal", "true");
  await expect(statusControl).toContainText("Closed");
  await expect(taskSheet.getByRole("button", { name: "Close Task", exact: true })).toHaveCount(0);

  const completed = await api<{ task: { lifecycle_state: string; closure_evidence_ref: string | null; origin_kind: string } }>(page, `/api/tasks/${taskId}`);
  expect(completed.body.task.lifecycle_state).toBe("completed");
  expect(completed.body.task.closure_evidence_ref).toBeNull();
  expect(completed.body.task.origin_kind).toBe("direct_principal");

  // Provenance and closure-evidence metadata did not disappear: they moved
  // behind the Technical details disclosure, which has to be expanded first.
  const technical = taskSheet.getByTestId("task-technical-details");
  await technical.getByText("Technical details").click();
  const provenance = technical.getByRole("region", { name: "Provenance" });
  await expect(provenance.getByText("direct_principal").first()).toBeVisible();
  await expect(technical.getByRole("button", { name: "View closure evidence" })).toHaveCount(0);
  await expect(technical.getByText(taskId!)).toBeVisible();

  const stillOpen = await api<{ commitment: { state: string } }>(
    page,
    `/api/commitments/${commitment!.commitment_id}`,
  );
  expect(stillOpen.body.commitment.state).toBe("open");

  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Commitments" }).click();
  await page.getByLabel("Search commitments").fill(marker);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("link", { name: new RegExp(commitmentTitle) }).click();
  const commitmentDialog = page.getByRole("dialog");
  await expect(commitmentDialog.getByText(/^E2E Synthetic Counterparty ·/)).toBeVisible();
  await expect(commitmentDialog.getByText(reappliedTitle)).toBeVisible();
  // The follow-up Task's terminal state, stated in product language. The
  // previous wording (`completed`) was the backend token.
  await expect(commitmentDialog.getByText("Task state: Closed")).toBeVisible();
  await commitmentDialog.getByLabel("Closure note").fill("Synthetic explicit Commitment closure evidence.");
  await commitmentDialog.getByRole("button", { name: "Close commitment" }).click();
  await expect(commitmentDialog.getByText("Commitment explicitly closed.")).toBeVisible();
  const closed = await api<{ commitment: { state: string; closure_evidence_ref: string | null } }>(
    page,
    `/api/commitments/${commitment!.commitment_id}`,
  );
  expect(closed.body.commitment.state).toBe("closed");
  expect(closed.body.commitment.closure_evidence_ref).toMatch(/^cap_/);
});

test("BFF refuses browser Principal selection and foreign opaque identifiers without disclosure", async ({ page }) => {
  await page.goto("/work?view=unscheduled");
  const widened = await api<{ error: { message: string } }>(page, "/api/tasks", {
    method: "POST",
    body: {
      principalId: "prn_bbbbbbbb22222222",
      title: "must not be attempted",
      idempotencyKey: key("e2e-principal-widen"),
    },
  });
  expect(widened.status).toBe(400);
  expect(widened.body.error.message).toMatch(/caller-supplied identity field.*principalId.*rejected/i);

  const foreignTask = await api<{ error: { errorClass: string } }>(
    page,
    "/api/tasks/tsk_bbbbbbbb22222222",
  );
  expect(foreignTask.status).toBe(404);
  expect(foreignTask.body.error.errorClass).toBe("not_found");

  const foreignCommitment = await api<{ error: { errorClass: string } }>(
    page,
    "/api/commitments/cmt_bbbbbbbb22222222",
  );
  expect(foreignCommitment.status).toBe(404);
  expect(foreignCommitment.body.error.errorClass).toBe("not_found");
});

test("unsupported Waiting On search is explicit and unavailable Work is not empty", async ({ page }) => {
  await page.goto("/work?view=commitments&commitment=waiting-on");
  await expect(page.getByLabel("Search commitments")).toBeDisabled();
  await expect(page.getByText(/Search is unavailable for the dedicated Waiting On view/)).toBeVisible();
});
