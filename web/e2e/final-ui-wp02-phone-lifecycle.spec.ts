import { expect, test, type Page } from "@playwright/test";
import { openCaptureNote, signIn, syntheticNote, visibleCaptureButton } from "./fixtures";

const launcher = (page: Page) => page.getByRole("dialog", { name: "Search or create" });
const overlays = (page: Page) => page.locator('dialog[open], [role="dialog"][data-state="open"]').filter({ visible: true });

test.use({ viewport: { width: 390, height: 844 } });
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await test.step("PHONE_SIGN_IN", async () => { await signIn(page); });
});

/** Canonical phone launcher lifetime; only synthetic request tuples are held in memory. */
test("WP02 phone Capture keeps its pending mutex and ambiguous frozen attempt through Task", async ({ page }) => {
  const projectId = await test.step("CAPTURE_PROJECT_SEED", async () => {
    const projectsResponse = await page.request.get("/api/projects");
    expect(projectsResponse.status()).toBe(200);
    const projects = await projectsResponse.json() as { projects?: { projectId?: string }[] };
    const projectId = projects.projects?.[0]?.projectId;
    expect(typeof projectId).toBe("string");
    return projectId;
  });
  type CaptureAttempt = { text: string; captureKind: string; projectId: string | null; idempotencyKey: string };
  const attempts: CaptureAttempt[] = [];
  let releaseFirst: () => void = () => undefined;
  const heldFirst = new Promise<void>((resolve) => { releaseFirst = resolve; });
  let firstStarted: () => void = () => undefined;
  const firstRequest = new Promise<void>((resolve) => { firstStarted = resolve; });
  let firstReceipt: { captureId: string; receiptId: string } | undefined;
  await page.exposeBinding("wp02CaptureResponseBarrier", async (_source, observed: {
    attempt: CaptureAttempt; responseClass: "OK" | "OTHER";
    receipt: { captureId?: string; receiptId?: string };
  }) => {
    attempts.push(observed.attempt);
    if (attempts.length !== 1) return "REAL";
    expect(observed.responseClass).toBe("OK");
    expect(typeof observed.receipt.captureId).toBe("string");
    expect(typeof observed.receipt.receiptId).toBe("string");
    firstReceipt = observed.receipt as { captureId: string; receiptId: string };
    firstStarted();
    await heldFirst;
    return "MASK_FIRST";
  });
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    const scopedWindow = window as typeof window & {
      wp02CaptureResponseBarrier: (observed: {
        attempt: { text: string; captureKind: string; projectId: string | null; idempotencyKey: string };
        responseClass: "OK" | "OTHER"; receipt: { captureId?: string; receiptId?: string };
      }) => Promise<"REAL" | "MASK_FIRST">;
      wp02RestoreFetch?: () => void;
    };
    scopedWindow.wp02RestoreFetch = () => { window.fetch = originalFetch; };
    window.fetch = async (input, init) => {
      const request = new Request(input, init);
      if (request.method !== "POST" || new URL(request.url).pathname !== "/api/capture") {
        return originalFetch(input, init);
      }
      const body = await request.clone().json();
      const attempt = { text: body.text, captureKind: body.captureKind,
        projectId: body.projectId, idempotencyKey: body.idempotencyKey };
      // The real backend commits before only the response delivered to Capture is held.
      const response = await originalFetch(input, init);
      const ack = await response.clone().json();
      const mode = await scopedWindow.wp02CaptureResponseBarrier({ attempt,
        responseClass: response.ok ? "OK" : "OTHER",
        receipt: { captureId: ack.receipt?.captureId, receiptId: ack.receipt?.receiptId },
      });
      if (mode === "REAL") return response;
      return new Response(JSON.stringify({ error: { errorClass: "unavailable",
        code: "upstream_contract_invalid", message: "Synthetic ambiguous Capture response" } }),
      { status: 503, headers: { "content-type": "application/json" } });
    };
  });
  const note = syntheticNote(`wp02-phone-frozen-${Date.now()}`);
  const taskDraft = "Synthetic independent phone Task draft";
  await test.step("CAPTURE_OPEN_AND_AUTHOR", async () => {
    await openCaptureNote(page);
    await page.getByTestId("capture-project-select").selectOption(projectId!);
    await page.getByTestId("capture-field").fill(note);
  });
  try {
    await test.step("CAPTURE_FIRST_SAVE_CLICK", async () => {
      await expect(page.getByTestId("capture-field")).toHaveValue(note);
      await expect(page.getByTestId("capture-project-select")).toHaveValue(projectId!);
      const save = page.getByRole("button", { name: "Save", exact: true });
      await expect(save).toHaveCount(1);
      await expect(save).toBeVisible();
      await expect(save).toBeEnabled();
      await save.click();
    });
    await test.step("CAPTURE_SAVE_HANDLER_ENTERED", async () => {
      const saving = page.getByRole("button", { name: "Saving…", exact: true });
      await expect(saving).toHaveCount(1);
      await expect(saving).toBeDisabled();
      await expect(page.getByTestId("capture-field")).toBeDisabled();
      await expect(page.getByTestId("capture-project-select")).toBeDisabled();
    });
    await test.step("CAPTURE_FIRST_BACKEND_RESPONSE_HELD", async () => {
      await firstRequest;
    });
    await test.step("CAPTURE_PENDING_TASK_ROUNDTRIP", async () => {
      await expect(page.getByRole("button", { name: "Saving…", exact: true })).toBeDisabled();
      await page.getByTestId("capture-entry-back").click();
      await launcher(page).getByRole("button", { name: "Create Task", exact: true }).click();
      await page.getByRole("textbox", { name: "Title", exact: true }).fill(taskDraft);
      await expect(overlays(page)).toHaveCount(1);
      await page.getByTestId("task-create-back").click();
      await launcher(page).getByRole("button", { name: "Quick Note", exact: true }).click();
      await expect(page.getByTestId("capture-field")).toHaveValue(note);
      await expect(page.getByTestId("capture-project-select")).toHaveValue(projectId!);
      await expect(page.getByRole("button", { name: "Saving…", exact: true })).toBeDisabled();
      expect(attempts.length, "Task roundtrip must not create another pending Capture request").toBe(1);
      await expect(overlays(page)).toHaveCount(1);
    });
    await test.step("CAPTURE_RELEASE_AMBIGUOUS_RESPONSE", async () => {
      releaseFirst();
      await expect(page.getByTestId("capture-unavailable")).toBeVisible();
    });
    await test.step("CAPTURE_AMBIGUOUS_TASK_ROUNDTRIP", async () => {
      await page.getByTestId("capture-entry-back").click();
      await launcher(page).getByRole("button", { name: "Create Task", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue(taskDraft);
      await page.getByTestId("task-create-back").click();
      await launcher(page).getByRole("button", { name: "Quick Note", exact: true }).click();
      await expect(page.getByTestId("capture-unavailable")).toBeVisible();
      await expect(page.getByTestId("capture-field")).toHaveValue(note);
      await expect(page.getByTestId("capture-project-select")).toHaveValue(projectId!);
      await expect(page.getByTestId("capture-kind-quick_note")).toBeChecked();
    });
    await test.step("CAPTURE_RETRY_SAME_FROZEN_ATTEMPT", async () => {
      const [retry] = await Promise.all([
        page.waitForResponse((response) => new URL(response.url()).pathname === "/api/capture" && response.request().method() === "POST"),
        page.getByRole("button", { name: "Save", exact: true }).click(),
      ]);
      expect(retry.status()).toBe(200);
      const ack = await retry.json() as { status?: string; created?: boolean;
        receipt?: { captureId?: string; receiptId?: string } };
      expect(ack.status).toBe("persisted");
      expect(ack.created).toBe(false);
      expect(ack.receipt?.captureId).toBe(firstReceipt!.captureId);
      expect(ack.receipt?.receiptId).toBe(firstReceipt!.receiptId);
      await expect(page.getByTestId("capture-durable")).toBeVisible();
      await expect(page.getByTestId("capture-durable")).toContainText("Already saved");
      const libraryResponse = await page.request.get("/api/library");
      expect(libraryResponse.status()).toBe(200);
      const library = await libraryResponse.json() as { result?: {
        captures?: { capture_id?: string; project_id?: string | null }[] } };
      const matching = (library.result?.captures ?? []).filter((row) => row.capture_id === firstReceipt!.captureId);
      expect(matching).toHaveLength(1);
      expect(matching[0].project_id).toBe(projectId);
      expect(attempts.length).toBe(2);
      expect(attempts[0].text === note && attempts[1].text === note).toBe(true);
      expect(attempts[0].captureKind === "quick_note" && attempts[1].captureKind === "quick_note").toBe(true);
      expect(attempts[0].projectId === projectId && attempts[1].projectId === projectId).toBe(true);
      expect(typeof attempts[0].idempotencyKey === "string" && attempts[0].idempotencyKey.length > 0).toBe(true);
      expect(attempts[1].idempotencyKey === attempts[0].idempotencyKey, "ambiguous retry keeps the exact original key").toBe(true);
      await expect(overlays(page)).toHaveCount(1);
    });
  } finally {
    await test.step("CAPTURE_RELEASE_AND_RESTORE_FETCH", async () => {
      releaseFirst();
      await page.evaluate(() => {
        const scopedWindow = window as typeof window & { wp02RestoreFetch?: () => void };
        scopedWindow.wp02RestoreFetch?.();
        delete scopedWindow.wp02RestoreFetch;
      });
    });
  }
});

test("WP02 phone Search Task roundtrip retains full query, canonical result and row focus", async ({ page }) => {
  const marker = `phone-search-lifecycle-${Date.now()}`;
  const title = `Synthetic ${marker}`;
  // Use a real canonical Task and real Search; never invent an acceptable hit.
  const created = await page.evaluate(async ({ title, key }) => {
    const response = await fetch("/api/tasks", {
      method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" },
      body: JSON.stringify({ title, idempotencyKey: key }),
    });
    const body = await response.json() as { task?: { task_id?: string } };
    return { status: response.status, taskId: body.task?.task_id };
  }, { title, key: `e2e-${marker}` });
  expect(created.status).toBe(200);
  expect(created.taskId).toMatch(/^tsk_/);
  const origin = page.url();
  await visibleCaptureButton(page).click();
  await launcher(page).getByRole("button", { name: "Search", exact: true }).click();
  const query = launcher(page).getByRole("searchbox", { name: "Search", exact: true });
  await query.fill(marker);
  const result = launcher(page).locator(`[data-search-result="true"][data-result-key="${created.taskId}"]`);
  await expect(result).toHaveCount(1);
  await expect(result).toBeVisible();
  await expect(result).toHaveRole("link");
  await expect(result).toContainText(title);
  await result.focus();
  await expect(result).toBeFocused();
  await page.keyboard.press("Enter");
  const task = page.getByTestId("task-compact-sheet");
  await expect(task.getByRole("heading", { name: title, exact: true })).toBeVisible();
  await expect(task.getByTestId("task-summary")).toBeVisible();
  await expect(overlays(page)).toHaveCount(1);
  expect(page.url()).toBe(origin);
  const close = overlays(page).getByRole("button", { name: "Close panel", exact: true });
  await expect(close).toHaveCount(1);
  await close.click();
  await expect(task).toHaveCount(0);
  await expect(query).toHaveValue(marker);
  await expect(result).toHaveCount(1);
  await expect(result).toContainText(title);
  await expect(result).toBeFocused();
  await expect(overlays(page)).toHaveCount(1);
  expect(page.url()).toBe(origin);
});
