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
  await taskCreate.getByLabel("Origin note").fill("Synthetic Task evidence in the disposable browser database.");
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

  await taskTrigger.click();
  const taskDialog = page.getByRole("dialog");
  await expect(taskDialog.getByRole("heading", { name: taskTitle })).toBeVisible();
  let revealRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/reveal") revealRequests += 1;
  });

  await taskDialog.getByLabel("Description").fill("Safe atomic browser edit");
  await taskDialog.getByLabel("Priority").selectOption("p2");
  await taskDialog.getByRole("button", { name: "Save atomic patch" }).click();
  await expect(taskDialog.getByText("Task update persisted.")).toBeVisible();

  const beforeConflict = await api<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
  expect(beforeConflict.status).toBe(200);
  await taskDialog.getByLabel("Title").fill(reappliedTitle);
  const concurrent = await api<Record<string, unknown>>(page, `/api/tasks/${taskId}`, {
    method: "PATCH",
    body: {
      description: "Concurrent canonical edit",
      expectedVersion: beforeConflict.body.task.version,
      idempotencyKey: key("e2e-concurrent-task"),
    },
  });
  expect(concurrent.status).toBe(200);
  await taskDialog.getByRole("button", { name: "Save atomic patch" }).click();
  await expect(taskDialog.getByText(/changed on the server/i)).toBeVisible();
  await expect(taskDialog.getByRole("button", { name: /Reapply proposed patch to version/ })).toBeVisible();
  await taskDialog.getByRole("button", { name: /Reapply proposed patch to version/ }).click();
  await expect(taskDialog.getByRole("heading", { name: reappliedTitle })).toBeVisible();

  await taskDialog.getByLabel("Commitment").selectOption("");
  await taskDialog.getByLabel("Role").selectOption("");
  await taskDialog.getByRole("button", { name: "Save atomic patch" }).click();
  await expect(taskDialog.getByText("Task update persisted.")).toBeVisible();
  const unlinked = await api<{ task: { commitment_id: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(unlinked.body.task.commitment_id).toBeNull();

  await taskDialog.getByLabel("Commitment").selectOption({ label: commitmentTitle });
  await taskDialog.getByLabel("Role").selectOption("follow_up");
  await taskDialog.getByRole("button", { name: "Save atomic patch" }).click();
  await expect(taskDialog.getByText("Task update persisted.")).toBeVisible();
  const relinked = await api<{ task: { commitment_id: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(relinked.body.task.commitment_id).toBe(commitment!.commitment_id);

  await taskDialog.getByLabel("Move to").selectOption("in_progress");
  await taskDialog.getByRole("button", { name: "Apply transition" }).click();
  await expect(taskDialog.getByText(/in progress · version/)).toBeVisible();
  await taskDialog.getByLabel("Move to").selectOption("completed");
  await taskDialog.getByLabel("Closure note").fill("Synthetic terminal evidence from the browser acceptance flow.");
  await taskDialog.getByRole("button", { name: "Apply transition" }).click();
  await expect(taskDialog.getByText(/completed · version/)).toBeVisible();
  const completed = await api<{ task: { lifecycle_state: string; closure_evidence_ref: string | null } }>(page, `/api/tasks/${taskId}`);
  expect(completed.body.task.lifecycle_state).toBe("completed");
  expect(completed.body.task.closure_evidence_ref).toMatch(/^cap_/);

  await taskDialog.getByRole("button", { name: "View closure evidence" }).click();
  await expect(page.getByRole("heading", { name: "Why am I seeing this?" })).toBeVisible();
  expect(revealRequests).toBe(0);
  await page.getByRole("button", { name: "Reveal", exact: true }).click();
  await expect.poll(() => revealRequests).toBe(1);
  await expect(
    page.locator('[data-testid="reveal-evidence"], [data-testid="reveal-no-evidence"], [data-testid="reveal-unavailable"], [role="alert"]').last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).last().click();

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
  await expect(commitmentDialog.getByText(/completed/i)).toBeVisible();
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
      originEvidenceRef: "cap_bbbbbbbb22222222",
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
