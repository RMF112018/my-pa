import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/** Real owned Storybook fixtures; no new product route or gateway admission. */
const storyOrigin = process.env.MYPA_WP01_STORYBOOK_URL ?? "http://localhost:6006";
const fixture = (story: string) => `${storyOrigin}/iframe.html?id=foundation-workspace-frame--${story}&viewMode=story`;

for (const width of [320, 390, 768, 1024, 1440]) {
  test(`WP01 foundation preserves essential content and detail at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(fixture("foundation"));
    const main = page.getByRole("main", { name: "Foundation workspace" });
    await expect(main).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    for (const name of ["Synthetic record title", "Needs review", "Tomorrow", "No error reported"]) {
      await expect(page.getByText(name, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Source", { exact: true }).first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const frame = page.locator(".workspace-frame");
    await expect(frame).toHaveAttribute("data-detail-presentation", width < 1024 ? "sheet" : "inline");
    if (width < 1024) {
      const invoker = page.getByRole("button", { name: "Open details" });
      await invoker.focus();
      await page.keyboard.press("Enter");
      const panel = page.getByRole("dialog", { name: "Foundation workspace details" });
      await expect(panel).toBeVisible();
      await expect(page.getByRole("heading", { name: "Foundation workspace details" })).toBeFocused();
      await expect(page.getByText("Synthetic source evidence remains available.")).toBeVisible();
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(panel).not.toBeVisible();
      await expect(invoker).toBeFocused();
    } else {
      const source = await page.locator(".workspace-content").boundingBox();
      const detail = await page.getByRole("complementary").boundingBox();
      expect(source!.width).toBeGreaterThanOrEqual(320);
      expect(detail!.width).toBeGreaterThanOrEqual(420);
      expect(detail!.width).toBeLessThanOrEqual(Math.min(560, width * .44) + 1);
    }
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`foundation-${width}.png`), fullPage: true });
  });
}

test("WP01 dialog has deterministic input focus, keyboard trap, Escape and return focus", async ({ page, browserName }) => {
  await page.goto(fixture("foundation"));
  const invoker = page.getByRole("button", { name: "Open foundation dialog" });
  await invoker.focus();
  await page.keyboard.press("Enter");
  const field = page.getByRole("textbox", { name: "Record title" });
  await expect(field).toBeFocused();
  const next = browserName === "webkit" && process.platform === "darwin" ? "Alt+Tab" : "Tab";
  await page.keyboard.press(next);
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.keyboard.press(next);
  await expect(page.getByRole("button", { name: "Close dialog" })).toBeFocused();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Foundation input" })).not.toBeVisible();
  await expect(invoker).toBeFocused();
});

test("WP01 state vocabulary distinguishes claims and keeps explicit review keyboard-operable", async ({ page }) => {
  await page.goto(fixture("state-vocabulary"));
  for (const kind of ["loading", "empty", "partial", "unavailable", "not_found", "validation", "conflict"]) {
    await expect(page.getByTestId(`foundation-${kind}`)).toBeVisible();
    await expect(page.getByTestId(`foundation-${kind}`)).toHaveAttribute("data-state", kind);
  }
  await expect(page.getByTestId("foundation-unavailable")).toHaveAttribute("role", "alert");
  await expect(page.getByTestId("foundation-empty")).toHaveAttribute("role", "status");
  const review = page.getByRole("button", { name: "Review current" });
  await review.focus(); await page.keyboard.press("Enter");
  await expect(page.getByText("Read requested; no successful outcome claimed.")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("WP01 reflows at 200-percent-equivalent width and honors reduced motion", async ({ page }) => {
  // 640px at 200% gives a 320 CSS-pixel layout viewport. No physical-device claim.
  await page.setViewportSize({ width: 320, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(fixture("foundation"));
  await expect(page.getByRole("heading", { name: "Synthetic record title" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Open details" }).click();
  const panel = page.getByRole("dialog", { name: "Foundation workspace details" });
  await expect(panel).toBeVisible();
  expect(await panel.evaluate((element) => getComputedStyle(element).transitionDuration)).toBe("0s");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("WP01 open detail survives reflow and returns focus to the surviving workspace heading", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(fixture("foundation"));
  const invoker = page.getByRole("button", { name: "Open details" });
  await invoker.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Foundation workspace details" })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator(".workspace-frame")).toHaveAttribute("data-detail-presentation", "inline");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Foundation workspace details" })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Foundation workspace", exact: true })).toBeFocused();
  await expect(page.getByRole("complementary")).toBeVisible();
});


test("WP01 Dialog returns to the workspace heading when its originating action disappears", async ({ page }) => {
  await page.goto(fixture("removed-invoker"));
  await page.getByRole("button", { name: "Open removable dialog" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Changing action" })).toBeVisible();
  await page.getByRole("button", { name: "Remove originating action" }).click();
  await expect(page.getByRole("button", { name: "Open removable dialog" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Changing action" })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Changing workspace" })).toBeFocused();
});


test("WP01 Sheet preserves the consumer's surviving-row focus after its opener leaves", async ({ page }) => {
  await page.goto(fixture("surviving-row"));
  await page.getByRole("button", { name: "Open departing record" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Remove originating record" }).click();
  await expect(page.getByRole("button", { name: "Open departing record" })).toHaveCount(0);
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(page.getByRole("dialog", { name: "Departing record" })).not.toBeVisible();
  // Observe after the close lifecycle and consumer's paint-aligned restoration.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByRole("button", { name: "Surviving record", exact: true })).toBeFocused();
});
