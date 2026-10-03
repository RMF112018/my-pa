import { expect, test, type Page } from "@playwright/test";
import { signIn, openAccount, pinInspector } from "./fixtures";

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
  await openAccount(page);
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Close panel" }).click();

  await pinInspector(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  if (testInfo.project.name === "mobile") {
    await expect(page.getByRole("dialog", { name: "Inspector" })).toBeVisible();
  } else {
    if ((page.viewportSize()?.width ?? 0) >= 1024) {
      const toggle = page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: /^(Collapse|Expand) navigation$/ });
      await expect(toggle).toHaveCount(1);
      await expect(toggle).toBeVisible();
      if (await toggle.getAttribute("aria-label") === "Collapse navigation") await toggle.click();
      await expect(page.getByRole("button", { name: "Expand navigation" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Collapse navigation" })).toHaveCount(0);
    } else {
      await expect(page.getByRole("button", { name: "Collapse navigation" })).toHaveCount(0);
    }
    await expect(page.getByRole("complementary", { name: "Utility region" })).toBeVisible();
  }

  await expect(page).toHaveScreenshot("shell-dark-inspector.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("unified launcher has a deterministic reduced-motion initial state", async ({ page }) => {
  await page.keyboard.press("ControlOrMeta+k");
  const launcher = page.getByRole("dialog", { name: "Search or create" });
  await expect(launcher).toBeVisible();
  await expect(launcher.getByRole("group", { name: "Search or New" }).getByRole("button")).toHaveText(["Search", "New"]);
  await expect(launcher.getByRole("button", { name: "Search", exact: true })).toBeFocused();
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
  // Work disclosure/freshness is diagnostic-only in the default product view.
  await expect(page.getByRole("complementary", { name: "Work answer disclosure" })).toHaveCount(0);
  await expect(page.locator('[data-visual-dynamic="freshness"]')).toHaveCount(0);
  await expect(page).toHaveScreenshot("shell-zoom-200.png", {
    animations: "disabled",
    fullPage: false,
  });
});
