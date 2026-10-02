import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn, syntheticNote } from "./fixtures";

const newAction = (page: Page) => page.getByRole("banner").getByRole("button", { name: "New" });
const visibleDialogCount = (page: Page) => page.getByRole("dialog").count();
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

test("WP02 shell keeps one main and Search separate from New, with legacy destinations", async ({ page }, testInfo) => {
  await signIn(page);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(newAction(page)).toBeVisible();
  await expect(page.getByRole("link", { name: "Review" }).first()).toHaveAttribute("href", "/review");
  const primary = page.getByRole("navigation", { name: "Primary" });
  if (testInfo.project.name === "mobile") {
    const moreButton = primary.getByRole("button", { name: "More", exact: true });
    const more = page.getByRole("dialog", { name: "More", exact: true });
    await expect(more).not.toBeVisible();
    await expect(page.getByRole("link", { name: "System", exact: true })).toHaveCount(0);
    await moreButton.focus();
    await expect(moreButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(more).toBeVisible();
    const system = more.getByRole("link", { name: "System", exact: true });
    await expect(system).toBeVisible();
    await expect(system).toHaveAttribute("href", "/system");
    await system.focus();
    await expect(system).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(more).not.toBeVisible();
    await expect(page.getByRole("link", { name: "System", exact: true })).toHaveCount(0);
    await expect(moreButton).toBeFocused();
  } else {
    const system = primary.getByRole("link", { name: "System", exact: true });
    await expect(system).toBeVisible();
    await expect(system).toHaveAttribute("href", "/system");
  }
  expect((await new AxeBuilder({ page }).analyze()).violations.map(({ id, nodes }) => ({
    id, targets: nodes.map(({ target }) => target),
  }))).toEqual([]);

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Search" })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search" })).toBeFocused();
  await expect(page.getByTestId("capture-chooser")).not.toBeVisible();
  await expect(page.getByRole("dialog", { name: "Capture", includeHidden: true })).not.toBeVisible();
  await expect(page.locator('dialog[open][aria-label="Capture"]')).toHaveCount(0);
  await expect(page.locator("dialog[open]")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await newAction(page).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("capture-chooser")).toBeVisible();
  expect(await visibleDialogCount(page)).toBe(1);
  await expect(page.getByTestId("capture-choice-create_task")).toBeFocused();
  expect((await new AxeBuilder({ page }).analyze()).violations.map(({ id }) => id)).toEqual([]);
});

test("WP02 preserves separate drafts, guards Escape, and restores the actual New invoker", async ({ page }) => {
  await signIn(page);
  const invoker = newAction(page);
  await invoker.focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  const note = syntheticNote("wp02-separate-drafts");
  await page.getByTestId("capture-field").fill(note);
  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-choice-create_task").click();
  const title = page.getByRole("textbox", { name: "Title" });
  await expect(title).toBeFocused();
  await title.fill("Synthetic WP02 task draft");
  expect(await visibleDialogCount(page)).toBe(1);
  await page.getByTestId("task-create-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-field")).toHaveValue(note);
  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-choice-create_task").click();
  await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue("Synthetic WP02 task draft");
  await page.getByTestId("task-create-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  const prompt = page.waitForEvent("dialog");
  const press = page.keyboard.press("Escape");
  const browserDialog = await prompt;
  expect(browserDialog.type()).toBe("confirm");
  await browserDialog.dismiss();
  await press;
  await expect(page.getByTestId("capture-field")).toHaveValue(note);
  const secondPrompt = page.waitForEvent("dialog");
  const secondPress = page.keyboard.press("Escape");
  await (await secondPrompt).accept();
  await secondPress;
  await expect(page.getByRole("dialog", { name: "Capture" })).not.toBeVisible();
  await expect(invoker).toBeFocused();
});

test("WP02 Task confirmation offers Open Task with exactly one result", async ({ page }) => {
  await signIn(page);
  await newAction(page).click();
  await page.getByTestId("capture-choice-create_task").click();
  const taskTitle = `Synthetic WP02 confirmed task ${Date.now()}`;
  await page.getByRole("textbox", { name: "Title" }).fill(taskTitle);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().endsWith("/api/tasks") && candidate.request().method() === "POST"),
    page.getByRole("button", { name: "Create", exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  const result = await response.json() as { task: { task_id: string } };
  await expect(page.getByRole("dialog", { name: "Task created" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: `Task created: ${taskTitle}` })).toHaveCount(1);
  expect(await visibleDialogCount(page)).toBe(1);
  await expect(page.getByRole("button", { name: "Open Task" })).toBeVisible();
  await page.getByRole("button", { name: "Open Task" }).click();
  await expect(page).toHaveURL(new RegExp(`/work/tasks/${result.task.task_id}$`));
  await expect(page.getByRole("heading", { name: taskTitle })).toBeVisible();
});

test("WP02 offline Task explains the boundary while Capture remains available", async ({ page, context }) => {
  await signIn(page);
  await context.setOffline(true);
  await newAction(page).click();
  await page.getByTestId("capture-choice-create_task").click();
  const offline = page.getByRole("dialog", { name: "Create Task" });
  await expect(offline).toContainText("requires a connection");
  await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations.map(({ id }) => id)).toEqual([]);
  await offline.getByRole("button", { name: "Quick Capture" }).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await page.getByTestId("capture-field").fill(syntheticNote("wp02-offline-held"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("capture-queued")).toContainText("Held on this device only");
  await expect(page.getByTestId("capture-durable")).toHaveCount(0);
  expect(await visibleDialogCount(page)).toBe(1);
});

for (const width of [320, 390, 768, 1024, 1440]) {
  test(`WP02 New and essential creator content reflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await newAction(page).click();
    await expect(page.getByTestId("capture-choice-create_task")).toBeVisible();
    await expect(page.getByTestId("capture-choice-quick_note")).toBeVisible();
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await page.getByTestId("capture-choice-create_task").click();
    await expect(page.getByRole("textbox", { name: "Title" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create", exact: true })).toBeVisible();
    expect(await visibleDialogCount(page)).toBe(1);
    await expect.poll(() => noSideScroll(page)).toBe(true);
    if (width <= 390) {
      const target = page.getByRole("button", { name: "Create", exact: true });
      const box = await target.boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(44);
      expect(box?.width).toBeGreaterThanOrEqual(44);
    }
  });
}

test("WP02 at 200-percent-equivalent width keeps essential controls and no side scroll", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
  await newAction(page).click();
  await page.getByTestId("capture-choice-create_task").click();
  await expect(page.getByRole("textbox", { name: "Title" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeVisible();
  await expect.poll(() => noSideScroll(page)).toBe(true);
});
