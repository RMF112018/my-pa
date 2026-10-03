import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn, syntheticNote } from "./fixtures";

const launcherControl = (page: Page) => page.getByRole("button", { name: "Search or create" }).filter({ visible: true });
const launcher = (page: Page) => page.getByRole("dialog", { name: "Search or create" });
const launcherClose = (page: Page) => launcher(page).getByRole("button", { name: "Close dialog", exact: true }).filter({ visible: true });
const activeOverlays = (page: Page) => page.locator('dialog[open], [role="dialog"][data-state="open"]');
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

async function openNew(page: Page) {
  await launcherControl(page).click();
  await launcher(page).getByRole("button", { name: "New", exact: true }).click();
  return launcher(page);
}

test("WP02 exposes one Search or create launcher and safe transitional destinations", async ({ page }, testInfo) => {
  await signIn(page);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(launcherControl(page)).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Search", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Review" }).first()).toHaveAttribute("href", "/review");
  for (const target of ["/home", "/tasks", "/projects", "/utilities"]) {
    await expect(page.locator(`a[href="${target}"]`)).toHaveCount(0);
  }
  if (testInfo.project.name === "mobile") {
    const moreButton = page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "More" });
    await moreButton.click();
    const more = page.getByRole("dialog", { name: "More" });
    for (const name of ["Intelligence", "Knowledge", "Map", "Review", "System"]) {
      await expect(more.getByRole("link", { name, exact: true })).toBeVisible();
    }
    await expect(more.getByRole("link", { name: "Search" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(moreButton).toBeFocused();
  }
  await page.keyboard.press("ControlOrMeta+k");
  await expect(launcher(page)).toBeVisible();
  await expect(launcher(page).getByRole("button", { name: "Search" })).toBeFocused();
  await expect(launcher(page).getByRole("button", { name: "New", exact: true })).toBeVisible();
  await expect(activeOverlays(page)).toHaveCount(1);
  expect((await new AxeBuilder({ page }).analyze()).violations.map(({ id }) => id)).toEqual([]);
});

test("WP02 Search reuses canonical read results, seeds typed input, and Escape steps back", async ({ page }) => {
  await signIn(page);
  await launcherControl(page).click();
  await page.keyboard.type("morning");
  const dialog = launcher(page);
  const searchbox = dialog.getByRole("searchbox", { name: "Search" });
  await expect(searchbox).toBeFocused();
  await expect(searchbox).toHaveValue("morning");
  await expect(dialog.getByTestId("search-command-list")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /Create Task|Quick Note|Conversation Log/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(dialog.getByRole("button", { name: "Search" })).toBeFocused();
  await expect(dialog.getByRole("button", { name: "New", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(launcherControl(page)).toBeFocused();
});

test("WP02 New keeps independent Capture and Task drafts and guards only whole close", async ({ page }) => {
  await signIn(page);
  const invoker = launcherControl(page);
  await invoker.focus();
  const dialog = await openNew(page);
  expect(await dialog.getByRole("group", { name: "Create new", exact: true }).getByRole("button").allTextContents()).toEqual([
    "Create Task", "Quick Note", "Conversation Log",
  ]);
  await expect(launcherClose(page)).toHaveCount(1);
  await expect(launcherClose(page)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Create Task", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(dialog.getByRole("button", { name: "Conversation Log", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(dialog.getByRole("button", { name: "Create Task", exact: true })).toBeFocused();
  await dialog.getByRole("button", { name: "Quick Note" }).click();
  const note = syntheticNote("wp02-independent-note");
  await page.getByTestId("capture-field").fill(note);
  await page.getByTestId("capture-entry-back").click();
  await dialog.getByRole("button", { name: "Conversation Log" }).click();
  const conversation = syntheticNote("wp02-independent-conversation");
  await page.getByTestId("capture-field").fill(conversation);
  await page.getByTestId("capture-entry-back").click();
  await dialog.getByRole("button", { name: "Create Task" }).click();
  const title = page.getByRole("textbox", { name: "Title" });
  await title.fill("Synthetic WP02 retained task draft");
  await expect(activeOverlays(page)).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(dialog.getByRole("button", { name: "Create Task" })).toBeFocused();
  await expect(activeOverlays(page)).toHaveCount(1);
  await dialog.getByRole("button", { name: "Quick Note" }).click();
  await expect(page.getByTestId("capture-field")).toHaveValue(note);
  await page.getByTestId("capture-entry-back").click();
  await dialog.getByRole("button", { name: "Conversation Log" }).click();
  await expect(page.getByTestId("capture-field")).toHaveValue(conversation);
  await page.getByTestId("capture-entry-back").click();
  await dialog.getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue("Synthetic WP02 retained task draft");
  await page.getByRole("button", { name: "Close panel" }).click();
  const discard = page.getByRole("alertdialog", { name: "Discard drafts", exact: true });
  await expect(discard).toContainText("Held offline notes are not deleted.");
  await expect(discard.getByRole("button", { name: "Keep editing" })).toBeFocused();
  await discard.getByRole("button", { name: "Keep editing" }).click();
  await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue("Synthetic WP02 retained task draft");
  await page.getByRole("button", { name: "Close panel" }).click();
  await discard.getByRole("button", { name: "Discard drafts" }).click();
  await expect(launcher(page)).toHaveCount(0);
  await expect(invoker).toBeFocused();
});

test("WP02 confirmed Task closes on its origin and adds no Open Task action", async ({ page }) => {
  await signIn(page);
  const origin = page.url();
  const dialog = await openNew(page);
  const retainedNote = syntheticNote("wp02-note-retained-after-task");
  await dialog.getByRole("button", { name: "Quick Note", exact: true }).click();
  await page.getByTestId("capture-field").fill(retainedNote);
  await page.getByTestId("capture-entry-back").click();
  await expect(dialog.getByRole("button", { name: "Quick Note", exact: true })).toBeFocused();
  await dialog.getByRole("button", { name: "Create Task", exact: true }).click();
  const taskTitle = `Synthetic WP02 confirmed task ${Date.now()}`;
  await page.getByRole("textbox", { name: "Title" }).fill(taskTitle);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().endsWith("/api/tasks") && candidate.request().method() === "POST"),
    page.getByRole("button", { name: "Create", exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(page.getByRole("status").filter({ hasText: `Task created: ${taskTitle}` })).toHaveCount(1);
  await expect(launcher(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open Task" })).toHaveCount(0);
  expect(page.url()).toBe(origin);
  await (await openNew(page)).getByRole("button", { name: "Quick Note", exact: true }).click();
  await expect(page.getByTestId("capture-field")).toHaveValue(retainedNote);
  await expect(launcherClose(page)).toHaveCount(1);
  await launcherClose(page).click();
  const discard = page.getByRole("alertdialog", { name: "Discard drafts", exact: true });
  await expect(discard.getByRole("button", { name: "Keep editing" })).toBeFocused();
  await discard.getByRole("button", { name: "Discard drafts" }).click();
  await expect(launcher(page)).toHaveCount(0);
});

test("WP02 offline Task is not queued while Quick Note can be held", async ({ page, context }) => {
  await signIn(page);
  await context.setOffline(true);
  await (await openNew(page)).getByRole("button", { name: "Create Task" }).click();
  await expect(launcher(page).getByRole("status").locator("p")).toHaveText("Tasks can’t be created offline. Keep this draft open and try again when you’re online.");
  await expect(activeOverlays(page)).toHaveCount(1);
  await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  await expect(page.getByTestId("capture-queued")).toHaveCount(0);
  await launcher(page).getByRole("button", { name: "Back", exact: true }).click();
  await expect(launcher(page).getByRole("button", { name: "Create Task", exact: true })).toBeFocused();
  await launcher(page).getByRole("button", { name: "Quick Note" }).click();
  await page.getByTestId("capture-field").fill(syntheticNote("wp02-offline-held"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("capture-queued")).toContainText("Held on this device only");
  await expect(page.getByTestId("capture-durable")).toHaveCount(0);
});

for (const width of [320, 390, 768, 1024, 1440]) {
  test(`WP02 launcher and canonical Task controls reflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await expect.poll(() => noSideScroll(page)).toBe(true);
    const dialog = await openNew(page);
    const menu = dialog.getByRole("group", { name: "Create new", exact: true });
    await expect(menu.getByRole("button")).toHaveText(["Create Task", "Quick Note", "Conversation Log"]);
    for (const name of ["Create Task", "Quick Note", "Conversation Log"]) {
      await expect(menu.getByRole("button", { name, exact: true })).toBeVisible();
    }
    await expect(launcherClose(page)).toHaveCount(1);
    await expect(launcherClose(page)).toBeVisible();
    await launcherClose(page).focus();
    await expect(launcherClose(page)).toBeFocused();
    await expect(activeOverlays(page)).toHaveCount(1);
    const box = await dialog.boundingBox();
    expect(box, "the active launcher has measurable geometry").not.toBeNull();
    if (width <= 767) {
      await expect(launcherClose(page)).toHaveAccessibleName("Close dialog");
      expect(Math.abs(box!.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(box!.width - width)).toBeLessThanOrEqual(1);
      expect(Math.abs(box!.y + box!.height - 900)).toBeLessThanOrEqual(1);
      expect(box!.height).toBeLessThanOrEqual(900 * 0.92);
    } else if (width < 1024) {
      expect(box!.width).toBeGreaterThanOrEqual(width * 0.70);
      expect(box!.width).toBeLessThanOrEqual(width * 0.85);
    } else {
      expect(box!.width).toBeGreaterThanOrEqual(640);
      expect(box!.width).toBeLessThanOrEqual(720);
      expect(box!.height).toBeLessThanOrEqual(900 * 0.80);
    }
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await menu.getByRole("button", { name: "Create Task", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Title" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create", exact: true })).toBeVisible();
    await expect(activeOverlays(page)).toHaveCount(1);
    await expect.poll(() => noSideScroll(page)).toBe(true);
    if (width <= 390) {
      const box = await page.getByRole("button", { name: "Create", exact: true }).boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(44);
      expect(box?.width).toBeGreaterThanOrEqual(44);
    }
  });
}

test("WP02 at 200-percent-equivalent width retains controls with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
  await (await openNew(page)).getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByRole("textbox", { name: "Title" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeVisible();
  await expect.poll(() => noSideScroll(page)).toBe(true);
});
