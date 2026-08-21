import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

async function stableFrame(page: Page) {
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
  await stableFrame(page);
});

test("light successor shell is visually reviewable", async ({ page }) => {
  await page.goto("/intelligence");
  await stableFrame(page);
  await expect(page).toHaveScreenshot("shell-light-unavailable.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("dark shell captures responsive navigation and Inspector states", async ({ page }, testInfo) => {
  await page.goto("/people");
  await stableFrame(page);
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "Open Inspector" }).click();
    await expect(page.getByRole("dialog", { name: "Inspector" })).toBeVisible();
  } else {
    await page.getByRole("button", { name: "Collapse navigation" }).click();
    await page.getByRole("complementary", { name: "Utility region" }).getByRole("button", {
      name: "Open Inspector",
    }).click();
  }

  await expect(page).toHaveScreenshot("shell-dark-inspector.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("command overlay has a deterministic reduced-motion state", async ({ page }) => {
  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "Command menu" })).toBeVisible();
  await expect(page).toHaveScreenshot("shell-command-menu.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("the shell reflows at 200 percent without horizontal loss", async ({ page }) => {
  await page.goto("/work");
  await stableFrame(page);
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("the visual project must define a viewport");
  // Browser zoom reduces the available CSS viewport rather than scaling a
  // fixed-width page. Halve desktop/tablet width; use the WCAG reflow floor on
  // an already-narrow mobile viewport instead of manufacturing a 195px device.
  await page.setViewportSize({
    width: Math.max(320, Math.floor(viewport.width / 2)),
    height: viewport.height,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page).toHaveScreenshot("shell-zoom-200.png", {
    animations: "disabled",
    fullPage: false,
  });
});
