/**
 * An automated accessibility scan of the real rendered pages.
 *
 * `@axe-core/playwright` runs axe-core **inside the browser**, against the DOM
 * and the computed accessibility tree that Chromium actually built — not against
 * a jsdom approximation of it. The tag set is `wcag2a`, `wcag2aa`, `wcag21a`,
 * `wcag21aa` and `wcag22aa`. That is a machine-checkable subset of those rule
 * packs, not a WCAG 2.2 AA claim.
 *
 * **What an automated pass does and does not establish.** axe finds a subset of
 * WCAG failures — roughly the machine-checkable third. A clean run means no
 * *detectable* violation of those rules on the pages scanned; it does not mean
 * the surface is conformant, and this file does not claim it does. Automation
 * here is not screen-reader proof: it does not operate a screen reader, does
 * not prove announcement quality, and does not replace WP30's screen-reader,
 * 200%/400% zoom, or real-device checks.
 *
 * Landmarks, headings, keyboard/focus, named dialogs, named icon-only
 * controls, and live regions are asserted separately below, because their
 * *correctness* is not something axe can decide.
 */
import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn, syntheticNote, visibleCaptureButton, openCaptureNote, openAccount, pinInspector } from "./fixtures";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const PAGES = [
  "/today",
  "/work",
  "/intelligence",
  "/people",
  "/canvas",
  "/knowledge",
  "/knowledge/goodnotes",
  "/review",
  "/search",
  "/system",
  "/situations",
  "/library",
  "/work/projects/prj_e2ecst0000000001/constraints",
] as const;

/** Desktop primary rail plus System utility. Review/Search/Map are not rail items. */
const SHELL_DESTINATIONS = [
  "Today",
  "Work",
  "People",
  "Knowledge",
  "Intelligence",
  "System",
] as const;

/**
 * The Next.js development overlay, excluded — and why that is not a dodge.
 *
 * The browser suite runs against `next dev`, because the only sign-in this build
 * implements is refused in a production build (see `playwright.config.ts`). Dev
 * mode injects a `<nextjs-portal>` element carrying the "Open Next.js Dev Tools"
 * button, which is framework development chrome: it is not in `src/`, it is not
 * in the production bundle, and no user of this product will ever see it. A
 * violation reported against it would be a violation of Next.js's own overlay,
 * and leaving it in would mean either a permanently red suite or — far worse —
 * a suppression that also hid a real finding.
 *
 * Everything the product ships is still scanned. The exclusion is one custom
 * element name, stated here once so it cannot quietly grow.
 */
const DEV_OVERLAY = "nextjs-portal";

/** Every violation, with the nodes that caused it, so a failure is actionable. */
async function scan(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).exclude(DEV_OVERLAY).analyze();
  return results.violations.flatMap((violation) =>
    violation.nodes.map(
      (node) => `${violation.impact}: ${violation.id} @ ${node.target.join(" ")}`,
    ),
  );
}

async function useDarkTheme(page: Page): Promise<void> {
  await openAccount(page);
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Close panel" }).click();
}

test.describe("axe-core, in Chromium, against the rendered page", () => {
  test("the sign-in screen has no detectable violation", async ({ page }) => {
    await page.goto("/sign-in");
    expect(await scan(page), "sign-in accessibility violations").toEqual([]);
  });

  test("the setup screen has no detectable violation", async ({ page }) => {
    await page.goto("/setup");
    expect(await scan(page), "/setup accessibility violations").toEqual([]);
  });

  test("the operator-recovery screen has no detectable violation", async ({ page }) => {
    await page.goto("/recover/operator");
    expect(await scan(page), "/recover/operator accessibility violations").toEqual([]);
  });

  test("public owner-setup and operator-recovery reflow at 390px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const path of ["/setup", "/recover/operator"] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows horizontally at 390`).toBeLessThanOrEqual(1);
    }
  });

  for (const path of PAGES) {
    test(`${path} has no detectable violation`, async ({ page }) => {
      await signIn(page);
      await page.goto(path);
      expect(await scan(page), `${path} accessibility violations`).toEqual([]);
    });
  }

  test("the capture dialog, open, has no detectable violation", async ({ page }) => {
    await signIn(page);
    // Both stages are scanned: the WP-TUX-04 chooser and the note branch behind it.
    await visibleCaptureButton(page).click();
    await expect(page.getByTestId("capture-choice-create_task")).toBeFocused();
    expect(await scan(page), "capture chooser accessibility violations").toEqual([]);

    await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
    await expect(page.getByTestId("capture-field")).toBeFocused();
    expect(await scan(page), "capture dialog accessibility violations").toEqual([]);
  });

  test("the populated Constraint Register and Inspector have no detectable violation", async ({ page }) => {
    await signIn(page);
    await page.goto("/work/projects/prj_e2ecst0000000001/constraints?view=register&group=none");
    const register = page.locator("#main").getByRole("table", { name: /Constraint Register/ });
    await expect(register.getByRole("button", { name: "1.01" })).toBeVisible();
    expect(await scan(page), "Constraint Register accessibility violations").toEqual([]);
    await register.getByRole("button", { name: "1.01" }).click();
    await expect(page.getByTestId("constraint-inspector")).toBeVisible();
    expect(await scan(page), "Constraint Inspector accessibility violations").toEqual([]);
  });

  test("dark Work and interactive surfaces have no detectable violation", async ({ page }) => {
    await signIn(page);
    await useDarkTheme(page);

    for (const path of ["/work", "/knowledge"] as const) {
      await page.goto(path);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      expect(await scan(page), `${path} dark-theme accessibility violations`).toEqual([]);
    }
  });

  test("the dark held-note surface has no detectable violation", async ({ page, context }) => {
    await signIn(page);
    await useDarkTheme(page);
    await context.setOffline(true);

    await openCaptureNote(page);
    await page.getByTestId("capture-field").fill(syntheticNote("dark-accessibility"));
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-queued")).toBeVisible({ timeout: 30_000 });

    // The status normally drains on mount or the browser's online event. Fire
    // that event while transport remains offline so the retained-note surface
    // is deterministically rendered without claiming a reconnect occurred.
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(page.getByTestId("offline-queue-status")).toBeVisible();
    await page.getByRole("button", { name: "Close", exact: true }).click();
    expect(await scan(page), "dark held-note accessibility violations").toEqual([]);
  });
});

test.describe("what axe cannot decide", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("every destination exposes banner, navigation and main exactly once", async ({ page }) => {
    const assertLandmarks = async (path: string) => {
      await page.goto(path);
      await expect(page.getByRole("banner"), `${path} banner count`).toHaveCount(1);
      await expect(page.getByRole("main"), `${path} main count`).toHaveCount(1);
      // Two navigation landmarks by design — the desktop rail and the mobile
      // bar — and only one of them is rendered at any viewport.
      const navs = page.getByRole("navigation");
      expect(await navs.count()).toBeGreaterThanOrEqual(1);
    };

    await expect(page).toHaveURL(/\/today$/);
    await expect(page.getByRole("banner"), "/today banner count").toHaveCount(1);
    await expect(page.getByRole("main"), "/today main count").toHaveCount(1);
    expect(await page.getByRole("navigation").count()).toBeGreaterThanOrEqual(1);
    for (const path of PAGES.slice(1)) {
      await assertLandmarks(path);
    }
  });

  test("every destination has exactly one level-1 heading", async ({ page }) => {
    for (const path of PAGES) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    }
  });

  test("command palette search takes focus and restores it on Escape", async ({ page }) => {
    const opener = page.getByRole("button", { name: "Account" });
    await opener.focus();
    await page.keyboard.press("Control+K");
    const dialog = page.getByRole("dialog", { name: "Search" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("searchbox", { name: "Search" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test("Search Cmd/K dialog restores focus on close", async ({ page }) => {
    // Native <dialog> returns focus to the invoking element. Control+K is the
    // chord the overlay listens for (meta or ctrl); this is not screen-reader
    // proof and does not claim WCAG 2.2 AA.
    const opener = page.getByRole("button", { name: "Account" });
    await opener.focus();
    await expect(opener).toBeFocused();
    await page.keyboard.press("Control+K");
    const dialog = page.getByRole("dialog", { name: "Search" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("searchbox", { name: "Search" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test("shell dialogs expose an accessible name", async ({ page }) => {
    await visibleCaptureButton(page).click();
    await expect(page.getByRole("dialog", { name: "Capture" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Capture" })).toHaveCount(0);

    await page.keyboard.press("Control+K");
    await expect(page.getByRole("dialog", { name: "Search" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Search" })).toHaveCount(0);
  });

  test("icon-only shell chrome and collapsed destinations have accessible names", async ({
    page,
  }) => {
    await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
    await openAccount(page);
    await expect(page.getByRole("button", { name: "Use dark theme" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Use compact density" })).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByRole("button", { name: /Commands/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open Inspector" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Collapse navigation" })).toBeVisible();

    await page.getByRole("button", { name: "Collapse navigation" }).click();
    await expect(page.getByRole("button", { name: "Expand navigation" })).toBeVisible();
    const rail = page.getByRole("navigation", { name: "Primary" }).first();
    for (const name of SHELL_DESTINATIONS) {
      await expect(rail.getByRole("link", { name })).toBeVisible();
    }
    await expect(rail.getByRole("link", { name: "Search" })).toBeVisible();
    await expect(rail.getByRole("link", { name: "Review" })).toBeVisible();
    await expect(rail.getByRole("link", { name: "Map" })).toBeVisible();
  });

  test("a state change is announced, not merely rendered", async ({ page }) => {
    await openCaptureNote(page);
    await page.getByTestId("capture-field").fill("E2E synthetic note — announcement check.");
    await page.getByRole("button", { name: "Save" }).click();
    // Live-region role is what automation can see. That is not screen-reader
    // proof: WP30 owns actual screen-reader announcement quality.
    const outcome = page.locator('[data-testid^="capture-"][role="status"], [data-testid^="capture-"][role="alert"]');
    await expect(outcome.first()).toBeVisible();
  });
});

test.describe("touch targets at a phone viewport", () => {
  // CI's accessibility job is `--project=desktop` only. Skipping unless
  // `project.name === "mobile"` would mean this never ran in CI. Force a
  // touch viewport onto whichever project executes the file — including
  // that desktop job — rather than changing the workflow.
  test.use({ viewport: { width: 412, height: 839 }, hasTouch: true });

  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  // **44px tall, 24px wide, and the two numbers are not the same rule.** WCAG
  // 2.5.8 (AA) sets the minimum target at 24x24 CSS px, and that is the number
  // the *width* is held to — inventing a stricter one here would be this suite
  // asserting a standard nobody adopted. The height is held to 44px because this
  // shell's own layout makes it free: the rail links and the capture button are
  // full-width rows whose height is the only dimension a regression can shrink,
  // so 44px there is a real floor rather than an aspiration. The title says both
  // numbers so that neither can drift away from what is measured below. This is
  // a bounding-box check, not a screen-reader proof and not a WCAG 2.2 AA claim.
  test("interactive targets are 44px tall and clear WCAG 2.5.8's 24px width", async ({ page }) => {
    await page.goto("/knowledge");
    // Scoped to the application's own landmarks, which excludes the Next.js dev
    // overlay button — framework development chrome that ships in no build (see
    // `DEV_OVERLAY` above). The skip link is excluded by the size floor below
    // rather than by name: it is a visually-hidden 1x1 target until focused, and
    // WCAG 2.5.8 does not ask a hidden bypass link to be 44px while hidden.
    const targets = page
      .locator("header, nav, main")
      .locator("button, a[href], input[type=search]");
    const count = await targets.count();
    expect(count).toBeGreaterThan(0);
    const undersized: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const target = targets.nth(index);
      if (!(await target.isVisible())) continue;
      const box = await target.boundingBox();
      if (!box) continue;
      // Below 4px in either dimension is a visually-hidden control, not a target.
      if (box.height < 4 || box.width < 4) continue;
      if (box.height < 44 || box.width < 24) {
        undersized.push(`${(await target.textContent())?.trim().slice(0, 40)} ${box.width}x${box.height}`);
      }
    }
    expect(undersized, "targets below 44px tall or below WCAG 2.5.8's 24px wide").toEqual([]);
  });

  test("the Inspector sheet is a named dialog at a phone viewport", async ({ page }) => {
    await pinInspector(page);
    await expect(page.getByRole("dialog", { name: "Inspector" })).toBeVisible();
  });
});

test.describe("Intelligence working surface landmarks", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("Intelligence landing keeps one h1, a labelled region, and a History link", async ({
    page,
  }) => {
    await page.goto("/intelligence");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Intelligence", level: 1 })).toBeVisible();
    await expect(page.getByRole("region", { name: "Intelligence" })).toHaveCount(1);
    const history = page.getByRole("link", { name: "History" });
    await expect(history).toBeVisible();
    await history.focus();
    await expect(history).toBeFocused();
  });

  test("Intelligence history keeps one h1 and a back link", async ({ page }) => {
    await page.goto("/intelligence/history");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Intelligence history", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Current Intelligence" })).toBeVisible();
  });
});

test.describe("People search, warnings, and profile extras", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("People landing forms are labelled and idle is not a directory", async ({ page }) => {
    await page.goto("/people");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("searchbox", { name: "Find a person" })).toBeVisible();
    await expect(page.getByTestId("people-resolve-advanced")).toBeVisible();
    await expect(page.getByTestId("people-idle")).toBeVisible();
    await expect(page.getByTestId("people-search-hits")).toHaveCount(0);
    expect(await scan(page), "/people idle accessibility violations").toEqual([]);
  });

  test("ambiguous resolve lists every candidate as a choice", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/people");
    await page.getByTestId("people-resolve-advanced").locator("summary").click();
    await page.getByLabel("Resolve a reference").fill("Alex Chen");
    await page.getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByTestId("people-resolve-result")).toHaveAttribute("role", "alert");
    await expect(page.getByTestId("people-resolve-candidates")).toBeVisible();
    expect(await scan(page), "people resolve accessibility violations").toEqual([]);
  });

  test("/people/ detail keeps one h1 and remains scannable", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/people");
    await page.getByRole("searchbox", { name: "Find a person" }).fill("Pat Synthetic");
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("link", { name: "Pat Synthetic" }).click();
    await expect(page).toHaveURL(/\/people\/ent_/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByTestId("people-profile")).toBeVisible();
    expect(await scan(page), "/people/ detail accessibility violations").toEqual([]);
  });
});
