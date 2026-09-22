/**
 * T17 — a Task created from Capture, and the Project a frozen create keeps.
 *
 * The real Task BFF, the real gateway, the real database. Two things are proven
 * that the unit tier could only prove in aggregate or not at all:
 *
 * * the Project a Capture-launched Task was created with is the Project the
 *   canonical row holds afterwards; and
 * * **FINDING-08** — the C08 precedence, isolated. Phase 3's unit test could
 *   only turn red when *both* enforcement mechanisms were removed, because the
 *   resume path always runs both. Here the isolation comes from the network
 *   rather than from the code: an ambiguous create is left unresolved, Capture
 *   is relaunched proposing a different Project, and the request that finally
 *   reaches the server is inspected. Whichever mechanism produced it, the wire
 *   says which Project won — and that is the claim the precedence rule makes.
 */
import { expect, test } from "@playwright/test";
import { signIn, syntheticNote, visibleCaptureButton } from "./fixtures";

type Page = import("@playwright/test").Page;

async function authorizedProjects(page: Page) {
  const response = await page.request.get("/api/projects");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { projects?: { projectId?: string }[] };
  return (body.projects ?? [])
    .map((row) => row.projectId)
    .filter((id): id is string => typeof id === "string");
}

/**
 * The canonical Task, by identifier.
 *
 * The exact read rather than the default listing: `/api/tasks` without
 * parameters is a bounded work view, and a test that searched it would be
 * asserting on that view's membership rule rather than on the row this create
 * produced.
 */
async function canonicalTask(page: Page, taskId: string) {
  const response = await page.request.get(`/api/tasks/${taskId}`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { task?: { project_id?: string | null } };
  return body.task;
}

/** Create through the real UI and return the canonical mutation the BFF published. */
async function createAndReadTask(page: Page) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.url().includes("/api/tasks") && candidate.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Create" }).click(),
  ]);
  expect(response.status()).toBe(200);
  return (await response.json()) as { task: { task_id: string; project_id: string | null } };
}

/** Open Capture and take the Create Task branch. */
async function openTaskFromCapture(page: Page): Promise<void> {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByTestId("task-create-sheet")).toBeVisible();
}

test.describe("WP08 Capture to Task Project, real stack", () => {
  test("a Task created from Capture reads back against the chosen Project", async ({ page }) => {
    await signIn(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length === 0, "this stack seeds no Project for the synthetic Principal");
    const chosen = projects[0]!;

    const title = syntheticNote(`wp08-task-project-${Date.now()}`);
    await openTaskFromCapture(page);
    await page.getByTestId("capture-project-select").selectOption(chosen);
    await page.getByLabel("Title").fill(title);
    const created = await createAndReadTask(page);
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);

    // The canonical row holds the Project, not just the response that made it.
    expect(created.task.project_id).toBe(chosen);
    expect((await canonicalTask(page, created.task.task_id))?.project_id).toBe(chosen);
  });

  test("No Project omits the field and the canonical Task holds null", async ({ page }) => {
    await signIn(page);
    const title = syntheticNote(`wp08-task-no-project-${Date.now()}`);

    const sent: string[] = [];
    await page.route("**/api/tasks", async (route) => {
      if (route.request().method() === "POST") sent.push(route.request().postData() ?? "");
      await route.continue();
    });

    await openTaskFromCapture(page);
    await expect(page.getByTestId("capture-project-select")).toHaveValue("");
    await page.getByLabel("Title").fill(title);
    const created = await createAndReadTask(page);
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);

    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]!) as Record<string, unknown>;
    // Omission, not null: that is what the Task contract admits.
    expect(Object.hasOwn(body, "projectId")).toBe(false);
    expect((await canonicalTask(page, created.task.task_id))?.project_id ?? null).toBeNull();
  });

  test("FINDING-08: a frozen create against A is not moved by a relaunch proposing B", async ({
    page,
  }) => {
    await signIn(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length < 2, "this stack seeds fewer than two Projects");
    const [projectA, projectB] = projects;

    const title = syntheticNote(`wp08-task-frozen-a-${Date.now()}`);
    const posts: string[] = [];
    let holdFirst = true;
    await page.route("**/api/tasks", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      posts.push(route.request().postData() ?? "");
      if (holdFirst) {
        // The first create never answers: the intent is left unresolved and
        // frozen, which is the state the precedence rule governs.
        holdFirst = false;
        await new Promise((resolve) => setTimeout(resolve, 5_000));
        await route.abort("failed");
        return;
      }
      await route.continue();
    });

    // Create against A, and leave it ambiguous.
    await openTaskFromCapture(page);
    await page.getByTestId("capture-project-select").selectOption(projectA!);
    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Create" }).click();
    await expect.poll(() => posts.length, { timeout: 15_000 }).toBe(1);
    const first = JSON.parse(posts[0]!) as Record<string, unknown>;
    expect(first.projectId).toBe(projectA);

    // The create is now ambiguous. Relaunch Capture proposing B.
    await expect(page.getByRole("button", { name: "Retry same create" })).toBeVisible({
      timeout: 20_000,
    });
    await page.getByTestId("task-create-back").click();
    await expect(page.getByTestId("capture-chooser")).toBeVisible();
    await page
      .getByTestId("capture-chooser")
      .getByRole("button", { name: "Quick note" })
      .click();
    await page.getByTestId("capture-project-select").selectOption(projectB!);
    await page.getByTestId("capture-entry-back").click();
    await page.getByTestId("capture-chooser").getByRole("button", { name: "Create Task" }).click();

    // The resumed surface shows A, disabled, and offers the same retry.
    const select = page.getByTestId("capture-project-select");
    await expect(select).toHaveValue(projectA!);
    await expect(select).toBeDisabled();
    await expect(page.getByTestId("task-create-frozen-project")).toBeVisible();

    // The retry goes out. Whatever produced it, the wire names A and carries the
    // original key — the isolation this finding asked for.
    const [retried] = await Promise.all([
      page.waitForResponse(
        (candidate) =>
          candidate.url().includes("/api/tasks") && candidate.request().method() === "POST",
      ),
      page.getByRole("button", { name: "Retry same create" }).click(),
    ]);
    await expect.poll(() => posts.length, { timeout: 20_000 }).toBe(2);
    const retry = JSON.parse(posts[1]!) as Record<string, unknown>;
    expect(retry.projectId).toBe(projectA);
    expect(retry.idempotencyKey).toBe(first.idempotencyKey);

    // And the canonical Task the retry produced is against A.
    expect(retried.status()).toBe(200);
    const produced = (await retried.json()) as { task: { task_id: string; project_id: string } };
    expect(produced.task.project_id).toBe(projectA);
    expect((await canonicalTask(page, produced.task.task_id))?.project_id).toBe(projectA);
  });

  test("Back returns to Capture with the Project the sheet held", async ({ page }) => {
    await signIn(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length === 0, "this stack seeds no Project for the synthetic Principal");
    const chosen = projects[0]!;

    await openTaskFromCapture(page);
    await page.getByTestId("capture-project-select").selectOption(chosen);
    await page.getByTestId("task-create-back").click();

    await expect(page.getByTestId("capture-chooser")).toBeVisible();
    await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
    // Capture adopted what Task actually held.
    await expect(page.getByTestId("capture-project-select")).toHaveValue(chosen);
    // Focus is inside the reopened surface, not on the page behind it.
    await expect(page.getByTestId("capture-field")).toBeFocused();
  });

  test("the Capture to Task path captures nothing", async ({ page }) => {
    await signIn(page);
    const captureCalls: string[] = [];
    await page.route("**/api/capture", async (route) => {
      captureCalls.push(route.request().method());
      await route.continue();
    });

    const title = syntheticNote("wp08-task-no-capture");
    await openTaskFromCapture(page);
    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);

    expect(captureCalls.filter((method) => method === "POST")).toHaveLength(0);
  });
});
