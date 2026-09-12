import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { signIn } from "./fixtures";

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

test.describe("Work acceptance", () => {
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
    await page.getByTestId("task-create-sheet").getByLabel("Title").fill(title);
    await page.getByTestId("task-create-sheet").getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
    // Creation sets no work date, so the canonical Today view must continue to
    // exclude this Task. Read it from the server-backed Unscheduled view instead.
    await page.getByRole("button", { name: "Work views" }).click();
    await page.getByRole("menuitem", { name: "Unscheduled" }).click();
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

  test("Work has no detectable automated accessibility violation in its rendered state", async ({ page }) => {
    // axe is a machine check of a subset of rules. It is not screen-reader
    // proof and is not a WCAG 2.2 AA claim. WP30 owns screen readers, zoom,
    // and real devices.
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .exclude("nextjs-portal")
      .analyze();
    expect(results.violations).toEqual([]);
  });

  for (const width of [390, 768, 1440] as const) {
    test(`Work keeps essential controls and reflows at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.getByRole("button", { name: "Work views" })).toBeVisible();
      await expect(page.getByRole("group", { name: "Work perspective" })).toBeVisible();
      await expect(page.getByRole("button", { name: "New task" })).toBeVisible();
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    });
  }

  test("Work survives the 200 percent reflow equivalent with reduced motion", async ({ page }) => {
    // Viewport-halving proxy, not a real browser zoom. WP30 owns 200%/400% zoom
    // and real devices. This is not screen-reader proof and not a WCAG 2.2 AA claim.
    await page.setViewportSize({ width: 720, height: 900 });
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("button", { name: "Use dark theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });
});

test.describe("representative 390-width reflow", () => {
  // Representative destinations only — not every route. Horizontal overflow
  // at 390 CSS px is not 200%/400% zoom, not a screen-reader proof, and not
  // a WCAG 2.2 AA claim. WP30 owns screen readers, zoom, and real devices.
  // GoodNotes also measures 390 overflow in goodnotes.spec.ts (that file
  // skips its desktop/tablet layout check on the mobile project because the
  // dedicated 390x844 test covers it).
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
    await page.setViewportSize({ width: 390, height: 844 });
  });

  for (const path of ["/search", "/canvas", "/knowledge/goodnotes", "/review"] as const) {
    test(`${path} does not overflow horizontally at 390px`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await horizontalOverflow(page), `${path} overflows horizontally at 390`).toBeLessThanOrEqual(
        1,
      );
    });
  }
});

/**
 * Compact Task detail acceptance (WP-TUX-03).
 *
 * Bounded to this work package's Task primitives: the narrow-width contract, the
 * absence of backend vocabulary from the primary surface, and the two-activation
 * close. Board, Calendar, Search and Today journeys are owned elsewhere.
 */
test.describe("compact Task detail", () => {
  /** Backend vocabulary and dead controls that must never reach the primary Task surface. */
  const FORBIDDEN_COPY = [
    "in_progress",
    "p1",
    "p2",
    "p3",
    "p4",
    "lifecycle",
    "atomic patch",
    "Apply transition",
  ] as const;
  /** Opaque identifier families. Diagnostics may state them; the primary surface may not. */
  const IDENTIFIER_PREFIXES = ["tsk_", "cap_", "rdec_", "tsh_"] as const;

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  /** Creates one synthetic Task and opens its compact detail sheet. */
  async function openTask(page: Page): Promise<ReturnType<Page["getByTestId"]>> {
    const title = `E2E synthetic compact task ${Date.now()}`;
    await page.goto("/work?view=unscheduled");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "New task" }).click();
    await page.getByTestId("task-create-sheet").getByLabel("Title").fill(title);
    await page.getByTestId("task-create-sheet").getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
    const trigger = page.getByRole("link", { name: new RegExp(title) });
    await expect(trigger).toBeVisible();
    await trigger.click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();
    return sheet;
  }

  // TASK-AC-045. Narrow-width reflow is measured at the four widths the work
  // package pins. This is not 200%/400% zoom and not a WCAG 2.2 AA claim.
  for (const width of [320, 375, 390, 430] as const) {
    test(`TASK-AC-045 compact Task detail fits ${width}px without horizontal scroll`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const sheet = await openTask(page);

      expect(await horizontalOverflow(page), `Task detail overflows horizontally at ${width}`).toBeLessThanOrEqual(1);

      // Terminal action stays reachable in the primary surface: Technical
      // details must still be collapsed when Close Task is available.
      await expect(sheet.getByTestId("task-technical-details")).not.toHaveAttribute("open", "");
      const close = sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true });
      await expect(close).toBeVisible();
      await close.scrollIntoViewIfNeeded();
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    });
  }

  test("TASK-AC-042/043 the primary Task surface states no backend token or opaque identifier, and diagnostics keep them", async ({ page }) => {
    const sheet = await openTask(page);
    const technical = sheet.getByTestId("task-technical-details");
    await expect(technical).not.toHaveAttribute("open", "");

    const primary = await sheet.innerText();
    // Guard the guard: an empty read would satisfy every negative below.
    expect(primary).toContain("Status");
    expect(primary).toContain("Close Task");
    for (const copy of FORBIDDEN_COPY) {
      expect(primary, `primary Task surface states "${copy}"`).not.toContain(copy);
    }
    for (const prefix of IDENTIFIER_PREFIXES) {
      expect(primary, `primary Task surface states a ${prefix} identifier`).not.toContain(prefix);
    }

    // Diagnostics were relocated, not deleted: the raw identity is reachable
    // behind one deliberate disclosure.
    await technical.getByText("Technical details").click();
    await expect(technical.getByRole("region", { name: "Identity" })).toBeVisible();
    expect(await technical.innerText()).toMatch(/tsk_[a-z0-9]+/i);
  });

  test("closing a Task costs two activations and never asks for authored text", async ({ page }) => {
    const sheet = await openTask(page);
    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();

    const confirmation = sheet.getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await expect(confirmation.locator("input, textarea")).toHaveCount(0);
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeVisible();

    await confirmation.getByRole("button", { name: "Confirm Closed" }).click();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expect(sheet.getByTestId("task-status-control")).toHaveAttribute("data-terminal", "true");
  });
});
