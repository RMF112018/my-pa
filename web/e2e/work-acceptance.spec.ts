import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
  await page.goto("/work?view=today&q=synthetic&tz=America%2FNew_York");
  await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
});

test("keyboard view changes preserve filter and canonical URL context", async ({ page }) => {
  const board = page.getByRole("button", { name: "Board" });
  await board.focus();
  await page.keyboard.press("Enter");
  await expect(board).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("textbox", { name: "Search tasks" })).toHaveValue("synthetic");
  await expect(page).toHaveURL(/view=today/);
  await expect(page).toHaveURL(/q=synthetic/);
  await expect(page).toHaveURL(/tz=America%2FNew_York/);
  await expect(page).toHaveURL(/perspective=board/);

  await page.getByRole("button", { name: "Calendar" }).press("Enter");
  await expect(page).toHaveURL(/perspective=calendar/);
  await expect(page.getByRole("textbox", { name: "Search tasks" })).toHaveValue("synthetic");
});

test("a synthetic Task preserves selection and restores focus after its detail drawer", async ({ page }) => {
  const title = `E2E synthetic Work task ${Date.now()}`;
  await page.getByRole("button", { name: "New task" }).click();
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Origin note").fill("Synthetic acceptance evidence; disposable database only.");
  await page.getByRole("button", { name: "Create task" }).click();
  await expect(page.getByRole("heading", { name: "Create task" })).toHaveCount(0);
  // Creation sets no work date, so the canonical Today view must continue to
  // exclude this Task. Read it from the server-backed Unscheduled view instead.
  await page.getByRole("button", { name: "Unscheduled" }).click();
  const trigger = page.getByRole("link", { name: new RegExp(title) });
  await expect(trigger).toBeVisible();
  await page.getByRole("checkbox", { name: `Select ${title}` }).check();
  await page.getByRole("button", { name: "Board" }).click();
  await expect(page.getByRole("checkbox", { name: `Select ${title}` })).toBeChecked();
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page).toHaveURL(/perspective=board/);
});

test("Work has no automated WCAG 2.2 AA violation in its rendered state", async ({ page }) => {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .exclude("nextjs-portal")
    .analyze();
  expect(results.violations).toEqual([]);
});

for (const width of [390, 768, 1440] as const) {
  test(`Work keeps essential controls and reflows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("navigation", { name: "Work views" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Work perspective" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New task" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("Work survives the 200 percent reflow equivalent with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 900 });
  expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
