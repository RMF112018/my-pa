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

/* ------------------------------------------------------------------ *
 * Seeding, and putting back what it takes out
 * ------------------------------------------------------------------ */

/**
 * Two scans here need a *populated* surface, so two of them create a Task.
 *
 * That is not inert in a suite whose tiers are shared. `e2e/stack.sh` creates
 * one disposable database for the whole run, and an open Task sits in
 * `work_view=unscheduled` — which `task_management.py` orders
 * `asc(due_at).nullslast()` — and, when its due moment has passed, on Today's
 * derived Pulse as well. Left behind, one Task per scanning test per project
 * accumulates and changes what every later spec sees. `today-tasks.spec.ts`
 * leaked the same way at larger scale and put three latent defects in
 * `journeys.spec.ts` and one in `work-acceptance.spec.ts` on screen as a red
 * job; this file is the smaller instance of it, drained the same way.
 *
 * The cleanup cannot hollow out what is being scanned: every seed is created,
 * asserted on screen, and scanned *inside* its test, and disposal happens in
 * `afterEach` — after the last assertion of that test and before the next one.
 * No scan ever runs against a surface this teardown has touched.
 */
const seededTaskIds: string[] = [];

/** See `today-tasks.spec.ts`: scaffolding was never done, so it is not "Closed". */
const TEARDOWN_STATE = "cancelled";

type ApiAnswer<T> = { status: number; body: T };

async function api<T>(
  page: Page,
  path: string,
  options: { method?: string; body?: Record<string, unknown> } = {},
): Promise<ApiAnswer<T>> {
  return page.evaluate(
    async ({ target, method, payload }) => {
      const response = await fetch(target, {
        method: method ?? "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: payload ? { "content-type": "application/json" } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      });
      return { status: response.status, body: (await response.json()) as T };
    },
    { target: path, method: options.method, payload: options.body },
  );
}

/** Create one synthetic Task through the canonical BFF and remember it. */
async function seedTask(
  page: Page,
  input: { readonly title: string; readonly dueAt: string; readonly idempotencyKey: string },
): Promise<{ readonly status: number; readonly taskId: string }> {
  const created = await api<{ task?: { task_id: string } }>(page, "/api/tasks", {
    method: "POST",
    body: { title: input.title, dueAt: input.dueAt, idempotencyKey: input.idempotencyKey },
  });
  const taskId = created.body.task?.task_id;
  if (taskId) seededTaskIds.push(taskId);
  return { status: created.status, taskId: taskId ?? "" };
}

/**
 * Dispose of every Task a test seeded, and fail loudly if disposal fails.
 *
 * Deterministic rather than best-effort — a silent `catch` would let the leak
 * back the moment the endpoint changed shape. Each row is read, one already
 * terminal is left alone, and the rest are transitioned with the version that
 * read returned. Confirmed by its own response, so no wait is introduced.
 */
async function disposeSeededTasks(page: Page): Promise<void> {
  const ids = [...seededTaskIds];
  seededTaskIds.length = 0;
  for (const taskId of ids) {
    const read = await api<{ task?: { version: number; lifecycle_state: string } }>(
      page,
      `/api/tasks/${taskId}`,
    );
    if (read.status !== 200 || !read.body.task) continue;
    const task = read.body.task;
    if (task.lifecycle_state === "completed" || task.lifecycle_state === "cancelled") continue;
    const disposed = await api<unknown>(page, `/api/tasks/${taskId}/transition`, {
      method: "POST",
      body: {
        toState: TEARDOWN_STATE,
        expectedVersion: task.version,
        idempotencyKey: `a11y-teardown-${taskId}-${Date.now()}`,
      },
    });
    expect(
      disposed.status,
      `teardown must dispose of seeded Task ${taskId}: ${JSON.stringify(disposed.body)}`,
    ).toBeLessThan(300);
  }
}

test.beforeEach(() => {
  seededTaskIds.length = 0;
});

/*
  Runs after a failed test as well as a passing one: a test that fails after
  seeding has still seeded, and those are the runs that leave the most behind.
  Tests that seed nothing drain an empty list and touch the network not at all,
  which matters for the offline held-note scan.
*/
test.afterEach(async ({ page }) => {
  await disposeSeededTasks(page);
});

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

  /**
   * The Create Task sheet, open (WP-POSTUX-01).
   *
   * The `/work` entry above scans the page with the sheet closed, so it says
   * nothing about the densest concentration of shared form primitives this head
   * puts on one screen — a text Input, a Textarea, a native Select and a date
   * Input inside a modal dialog. WP-POSTUX-01 moved all four onto a shared
   * typography and shrink contract and migrated Priority from a raw `<select>`
   * to the shared primitive, so the open state is where a regression in label
   * association, accessible name, or dialog semantics would actually surface.
   *
   * Nothing is submitted, so this creates no Task and seeds nothing to dispose.
   */
  test("the open Create Task sheet has no detectable violation", async ({ page }) => {
    await signIn(page);
    await page.goto("/work");
    await page.getByRole("button", { name: "New task" }).click();
    const sheet = page.getByTestId("task-create-sheet");
    await expect(sheet).toBeVisible();
    // Load-bearing: scanning before the controls render would pass vacuously.
    await expect(sheet.getByLabel("Priority")).toBeVisible();
    expect(await scan(page), "open Create Task sheet accessibility violations").toEqual([]);
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  });

  /**
   * A populated Task detail in its read-first default, then with the title
   * editor open, then with Planning and Context expanded (WP-POSTUX-04).
   *
   * The Create Task scan above is a different sheet and must stay that way:
   * Task detail no longer mounts Title/Description/Priority editors or the
   * comment composer until asked. An empty `/work` scan never opens this
   * dialog, so a pass there would say nothing about it.
   *
   * Still an automated subset: not screen-reader proof, not VoiceOver, and not
   * a WCAG 2.2 AA claim.
   */
  test("a populated Task detail default, title edit, and expanded Planning/Context have no detectable violation", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await signIn(page);
    const marker = `a11y-detail-${test.info().project.name}-${Date.now()}`;
    const title = `E2E task detail a11y ${marker}`;
    const created = await seedTask(page, {
      title,
      dueAt: "2026-12-18T17:00:00Z",
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    await page.goto(`/work?view=all-open&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: new RegExp(title) }).click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();
    await expect(sheet.getByTestId("task-edit-title")).toBeVisible();
    await expect(sheet.getByTestId("task-comments-add")).toBeVisible();
    await expect(sheet.getByRole("textbox", { name: "Title" })).toHaveCount(0);
    await expect(sheet.getByRole("textbox", { name: "Description" })).toHaveCount(0);
    await expect(sheet.getByRole("textbox", { name: "Add comment" })).toHaveCount(0);

    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog).toBeVisible();
    const sheetTitle = dialog.getByRole("heading", { name: title }).and(dialog.locator(".sr-only"));
    await expect(sheetTitle).toHaveCount(1);
    await expect(sheetTitle).toHaveClass(/sr-only/);
    await expect(dialog.locator("h1:not(.sr-only)")).toHaveCount(1);
    await expect(dialog.locator("h1:not(.sr-only)")).toHaveText(title);

    expect(await scan(page), "populated Task detail default accessibility violations").toEqual([]);

    await sheet.getByTestId("task-edit-title").click();
    const titleInput = sheet.getByRole("textbox", { name: "Title" });
    await expect(titleInput).toBeVisible();
    await expect(titleInput).toBeFocused();
    await expect(dialog.locator("h1:not(.sr-only)")).toHaveCount(0);
    await expect(dialog.locator("h1.sr-only")).toHaveCount(1);
    expect(await scan(page), "Task detail title-edit accessibility violations").toEqual([]);

    await sheet.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(sheet.getByTestId("task-edit-title")).toBeVisible();

    await sheet.getByTestId("task-planning-section").locator("summary").click();
    await expect(sheet.getByTestId("task-planning-section")).toHaveAttribute("open", "");
    await sheet.getByTestId("task-context-section").locator("summary").click();
    await expect(sheet.getByTestId("task-context-section")).toHaveAttribute("open", "");
    await expect(sheet.getByText("No project linked")).toBeVisible();
    expect(
      await scan(page),
      "Task detail expanded Planning/Context accessibility violations",
    ).toEqual([]);
  });

  /**
   * The Board and Calendar perspectives, populated, in both themes (WP-TUX-06).
   *
   * The `/work` entry in `PAGES` scans the List perspective only, which is the
   * default and which renders a different tree: Board and Calendar carry their
   * own landmarks, their own column headings, and the shared Task-operation
   * affordances in a different arrangement. An automated pass on List says
   * nothing about either of them.
   *
   * The surfaces are *populated* first, and that is load-bearing: axe finds no
   * violation in an empty column, so an unpopulated scan would pass vacuously.
   * The Task is synthetic, created through the real BFF, and carries a Due date
   * so the Calendar has a marker to render at all.
   *
   * Still an automated subset: not screen-reader proof, not a WCAG 2.2 AA claim.
   */
  test("populated Board and Calendar perspectives have no detectable violation", async ({ page }) => {
    test.setTimeout(180_000);
    await signIn(page);
    const marker = `a11y-${test.info().project.name}-${Date.now()}`;
    const title = `E2E perspective task ${marker}`;
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const created = await seedTask(page, {
      title,
      dueAt: "2026-11-18T17:00:00Z",
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    const board = `/work?view=all-open&q=${encodeURIComponent(marker)}&perspective=board`;
    const calendar = `/work?view=all-open&q=${encodeURIComponent(marker)}&perspective=calendar`;

    await page.goto(board);
    await expect(page.getByRole("region", { name: "Task lifecycle board" })).toBeVisible();
    await expect(page.locator('[data-testid="task-board-card"]').filter({ hasText: title })).toHaveCount(1);
    expect(await scan(page), "Board perspective accessibility violations").toEqual([]);

    // The Due choices are a popover: a control that only exists once opened is
    // never scanned by a page-level pass over the closed state.
    await page
      .locator('[data-testid="task-board-card"]')
      .filter({ hasText: title })
      .getByRole("button", { name: /^Due, / })
      .click();
    await expect(page.getByRole("group", { name: "Due choices" })).toBeVisible();
    expect(await scan(page), "Board Due choices accessibility violations").toEqual([]);

    await page.goto(calendar);
    await expect(page.getByRole("heading", { name: "Work calendar", level: 2 })).toBeVisible();
    await expect(page.locator('[data-testid="task-calendar-marker"]').filter({ hasText: title })).toHaveCount(1);
    expect(await scan(page), "Calendar perspective accessibility violations").toEqual([]);

    // Both perspectives again in the dark theme, where contrast rules are
    // decided against a different set of computed colours.
    await useDarkTheme(page);
    for (const [path, label] of [[board, "Board"], [calendar, "Calendar"]] as const) {
      await page.goto(path);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      expect(await scan(page), `${label} dark-theme accessibility violations`).toEqual([]);
    }
  });

  /**
   * A **populated** Today, and the two states its Task card can be put into
   * (WP-TUX-07).
   *
   * The `/today` entry in `PAGES` scans whatever Today happens to hold, and on
   * a quiet database that is the Empty card — a scan that passes without ever
   * seeing a Task card, a Due chooser or a terminal confirmation. So this test
   * puts a Task on the Pulse first and asserts the card is on screen before
   * scanning, exactly as the Board/Calendar test does, so a pass cannot be
   * vacuous.
   *
   * A Task reaches Today by being open with a due moment already past: the
   * derivation (`domain/situation/pulse_derivation.py`) surfaces it as
   * `task_overdue`, and it derives at read time, so nothing needs seeding into
   * a pulse table. The Task is synthetic and lives in the disposable database.
   *
   * The Due chooser and the Close confirmation are scanned separately, and for
   * the same reason the Board test gives: a control that exists only once it is
   * opened is never reached by a pass over the closed state — and the Close
   * confirmation is a `role="alertdialog"` that takes focus, which is precisely
   * the sort of tree an automated pass is good at.
   *
   * Still an automated subset: not screen-reader proof, not a WCAG 2.2 AA claim.
   */
  test("a populated Today, its Due chooser and its Close confirmation have no detectable violation", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await signIn(page);
    const marker = `a11y-today-${test.info().project.name}-${Date.now()}`;
    const title = `E2E today a11y task ${marker}`;
    const created = await seedTask(page, {
      title,
      // Past-due, so `pulse_derivation` surfaces it as `task_overdue` and Today
      // is genuinely populated before anything here is scanned.
      dueAt: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    const card = () => page.getByTestId("today-task-card").filter({ hasText: title });

    /** Populate, prove it is populated, then scan the three states. */
    async function scanTodayStates(label: string): Promise<void> {
      await page.goto("/today");
      await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
      // Load-bearing: without this the scan below could pass on an Empty card.
      await expect(card(), `${label}: Today must be populated before it is scanned`).toBeVisible({
        timeout: 30_000,
      });
      expect(await scan(page), `${label} populated Today accessibility violations`).toEqual([]);

      await card().getByRole("button", { name: `Reschedule ${title}` }).click();
      await expect(page.getByRole("group", { name: "Due choices" })).toBeVisible();
      expect(await scan(page), `${label} Today Reschedule chooser accessibility violations`).toEqual(
        [],
      );
      await page.keyboard.press("Escape");
      await expect(page.getByRole("group", { name: "Due choices" })).toHaveCount(0);

      await card().getByTestId("task-close-trigger").click();
      await expect(card().getByTestId("task-close-confirmation")).toBeVisible();
      expect(
        await scan(page),
        `${label} Today Close confirmation accessibility violations`,
      ).toEqual([]);
      // Stand the confirmation down: the Task must survive into the dark pass.
      await card().getByTestId("task-close-keep-open").click();
      await expect(card().getByTestId("task-close-confirmation")).toHaveCount(0);
    }

    await scanTodayStates("light");

    // The same three states in the dark theme, where contrast rules are decided
    // against a different set of computed colours.
    await useDarkTheme(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await scanTodayStates("dark");
  });

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

  /**
   * TASK-AC-035. A mutation outcome is perceptible to a screen reader, not merely painted.
   *
   * This is the automated half. The VoiceOver leg of TASK-AC-046 is operator-gated on a real
   * device and is not claimed by this run.
   */
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

test.describe("Task detail keyboard and named dialog (WP-POSTUX-04)", () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("Edit title focuses the Title input", async ({ page }) => {
    test.setTimeout(180_000);
    const marker = `a11y-detail-kb-${test.info().project.name}-${Date.now()}`;
    const title = `E2E task detail keyboard ${marker}`;
    const created = await seedTask(page, {
      title,
      dueAt: "2026-12-18T17:00:00Z",
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    await page.goto(`/work?view=all-open&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: new RegExp(title) }).click();
    const sheet = page.getByTestId("task-compact-sheet");
    const edit = sheet.getByTestId("task-edit-title");
    await expect(edit).toBeVisible();

    await edit.focus();
    await expect(edit).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(sheet.getByRole("textbox", { name: "Title" })).toBeFocused();
  });
});

test.describe("Task close confirmation and terminal read (WP-POSTUX-05)", () => {
  /**
   * macOS Tab vs Option+Tab: same chord rule as the Work List block above.
   * This is not VoiceOver and not a WCAG 2.2 AA claim.
   */
  async function pressNextControl(page: Page): Promise<void> {
    await page.keyboard.press(test.info().project.name === "webkit" ? "Alt+Tab" : "Tab");
  }

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("Close confirmation is an inline named alertdialog with Keep open focused", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const marker = `a11y-close-${test.info().project.name}-${Date.now()}`;
    const title = `E2E task close a11y ${marker}`;
    const created = await seedTask(page, {
      title,
      dueAt: "2026-12-18T17:00:00Z",
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    await page.goto(`/work?view=all-open&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: new RegExp(title) }).click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();

    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog).toBeVisible();
    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();

    const confirmation = sheet.getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation).toHaveAccessibleName("Close Task");
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    // Inline region, not a second modal: the sheet remains the one dialog.
    await expect(page.getByRole("dialog")).toHaveCount(1);
    expect(await scan(page), "Task Close confirmation accessibility violations").toEqual([]);

    await pressNextControl(page);
    await expect(confirmation.getByRole("button", { name: "Confirm Closed" })).toBeFocused();

    await confirmation.getByRole("button", { name: "Keep open" }).click();
    await expect(sheet.getByRole("alertdialog")).toHaveCount(0);
    await expect(sheet.getByRole("button", { name: "Close Task", exact: true })).toBeFocused();
  });

  test("a closed Task remains a named dialog and a read-only scannable surface", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const marker = `a11y-term-${test.info().project.name}-${Date.now()}`;
    const title = `E2E task terminal a11y ${marker}`;
    const created = await seedTask(page, {
      title,
      dueAt: "2026-12-18T17:00:00Z",
      idempotencyKey: `e2e-${marker}`,
    });
    expect(created.status).toBe(200);

    await page.goto(`/work?view=all-open&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: new RegExp(title) }).click();
    const sheet = page.getByTestId("task-compact-sheet");
    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();
    await sheet.getByRole("alertdialog").getByRole("button", { name: "Confirm Closed" }).click();

    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expect(sheet.getByTestId("task-terminal-summary")).toBeFocused();
    await expect(sheet.getByTestId("task-edit-title")).toHaveCount(0);
    await expect(sheet.getByTestId("task-edit-priority")).toHaveCount(0);
    await expect(sheet.getByTestId("task-add-description")).toHaveCount(0);
    await expect(sheet.getByTestId("task-close-control")).toHaveCount(0);
    await expect(sheet.getByTestId("task-comments-add")).toBeVisible();

    const dialog = page.getByRole("dialog").filter({ has: sheet });
    await expect(dialog).toBeVisible();
    await expect(sheet.locator("h1:not(.sr-only)")).toHaveCount(1);
    await expect(sheet.locator("h1:not(.sr-only)")).toHaveText(title);
    expect(await scan(page), "terminal Task detail accessibility violations").toEqual([]);
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

/**
 * The Create Task Title field's required-ness, and the validation that governs it.
 *
 * WP-POSTUX-02 exposes the Title input as `aria-required="true"` so assistive
 * technology announces the field as required *before* anyone submits — which is
 * the point of the attribute, and the reason the first assertion below is made
 * on a freshly opened sheet rather than after a failure.
 *
 * What it deliberately does **not** add is the native `required` attribute, and
 * that omission is the contract the rest of this block defends. Native
 * constraint validation would pre-empt the form's own handler: the browser would
 * block submission itself, show its own locale-dependent bubble instead of the
 * product's "Enter a task title.", and never run the code that sets
 * `aria-invalid`, wires `aria-describedby`, renders the `role="alert"` message
 * and returns focus to Title. `aria-required` announces; it does not validate.
 * So the tests here assert the custom path still runs end to end, and — the
 * assertion that actually discriminates the two designs — that submitting an
 * empty Title issues no `POST /api/tasks` at all.
 *
 * Nothing is ever submitted successfully, so this block creates no Task.
 */
test.describe("Create Task required-field semantics", () => {
  /** The product's own missing-title message. `task-create-sheet.tsx`, read not guessed. */
  const TITLE_REQUIRED_MESSAGE = "Enter a task title.";

  async function openCreateTask(page: Page) {
    await page.goto("/work");
    await page.getByRole("button", { name: "New task" }).click();
    const sheet = page.getByTestId("task-create-sheet");
    await expect(sheet).toBeVisible();
    // Load-bearing: asserting against a half-rendered form would pass vacuously.
    await expect(sheet.getByLabel("Priority")).toBeVisible();
    return sheet;
  }

  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("Title is announced as required before anything is submitted", async ({ page }) => {
    const sheet = await openCreateTask(page);
    const title = sheet.getByLabel("Title");

    await expect(title).toHaveAttribute("aria-required", "true");
    // The negative half of the same contract, and the load-bearing one: native
    // `required` must be absent, or the custom validation below never runs.
    expect(
      await title.evaluate((node) => node.hasAttribute("required")),
      "native `required` must not be present — it would pre-empt the product's own validation",
    ).toBe(false);
    // Announced as required, not yet announced as invalid. A field that starts
    // out `aria-invalid` tells a screen-reader user they have already made a
    // mistake they have not had the chance to make.
    await expect(title).not.toHaveAttribute("aria-invalid", "true");

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  });

  test("an empty Title is refused by the product, not by the browser, and reaches no network", async ({
    page,
  }) => {
    const creates: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      if (new URL(request.url()).pathname === "/api/tasks") creates.push(request.url());
    });

    const sheet = await openCreateTask(page);
    const title = sheet.getByLabel("Title");

    await sheet.getByRole("button", { name: "Create", exact: true }).click();

    // 1. The product's own copy, exposed as a live region so it is announced
    //    rather than merely painted.
    const alert = sheet.getByRole("alert");
    await expect(alert).toHaveText(TITLE_REQUIRED_MESSAGE);

    // 2. Programmatically associated with the field, not just adjacent to it.
    //    The association is checked by resolving the id, because an
    //    `aria-describedby` pointing at nothing is worse than none at all.
    await expect(title).toHaveAttribute("aria-invalid", "true");
    const describedBy = await title.getAttribute("aria-describedby");
    expect(describedBy, "Title must describe itself by the error's id").toBeTruthy();
    // Addressed by attribute rather than by `#id`: React's `useId` emits ids
    // containing characters an id selector would have to escape, and `CSS.escape`
    // does not exist in the Node process this assertion runs in.
    const described = sheet.locator(`[id="${describedBy}"]`);
    await expect(described).toHaveText(TITLE_REQUIRED_MESSAGE);
    await expect(described).toHaveAttribute("role", "alert");

    // 3. Focus is returned to the field the person must fix, so a keyboard or
    //    screen-reader user is not left at the submit button.
    await expect(title).toBeFocused();

    // 4. The assertion native `required` could not survive. The form's own
    //    handler refuses before it builds a request, so nothing is dispatched;
    //    a short settle gives any stray request time to land and be counted.
    await page.waitForTimeout(500);
    expect(creates, "a refused create must issue no POST /api/tasks").toEqual([]);

    // Typing clears the error, so the state is not sticky.
    await title.fill("Draft that is never submitted");
    await expect(sheet.getByRole("alert")).toHaveCount(0);
    await expect(title).not.toHaveAttribute("aria-invalid", "true");

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  });

  test("the sheet is a named dialog with a named close control", async ({ page }) => {
    // Dialog semantics are the frame everything above depends on: an error
    // announced inside an unnamed, non-dialog container is announced into a
    // context the reader cannot place.
    const sheet = await openCreateTask(page);
    const dialog = page.getByRole("dialog").filter({ has: sheet });

    await expect(dialog).toHaveCount(1);
    await expect(dialog.getByRole("heading", { name: "Create task" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Close panel" })).toBeVisible();

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  });

  test("the compacted sheet in its error state has no detectable violation", async ({ page }) => {
    // The WP-POSTUX-01 scan covers the sheet at rest. This one scans it after
    // the compaction has been applied *and* the validation has fired, which is
    // where a mis-wired `aria-describedby`, an orphaned live region, or a
    // contrast failure on the error copy would surface. Same `scan` helper, so
    // the rule set and the dev-overlay exclusion cannot drift apart.
    const sheet = await openCreateTask(page);
    await sheet.getByRole("button", { name: "Create", exact: true }).click();
    await expect(sheet.getByRole("alert")).toHaveText(TITLE_REQUIRED_MESSAGE);

    expect(await scan(page), "Create Task error-state accessibility violations").toEqual([]);

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  });
});

/* ------------------------------------------------------------------ *
 * The normalized Work List (WP-POSTUX-03)
 * ------------------------------------------------------------------ */

/**
 * The Work List after normalization, scanned and driven where it is operated.
 *
 * **Why the `/work` entry in `PAGES` is not enough, and why that matters here
 * more than anywhere else in this file.** That entry scans whatever the Work
 * List happens to hold, and on a quiet disposable database that is the Empty
 * card: axe finds no violation in a list with no rows, so a green result there
 * says nothing whatever about a Task row. WP03-AC-101 asks for a scan of the
 * *populated* List, so every test below seeds real Tasks through the canonical
 * BFF, asserts the rows are on screen, and only then scans or drives them. The
 * row count is asserted rather than assumed, so a pass cannot be vacuous.
 *
 * **What normalization changed that only an accessibility check can catch.**
 * Three of the row's controls gave up visible text: the Status field label is
 * now `sr-only`, the Due trigger shows its value without the word `Due`, and
 * the expanded More disclosure reads `Less`. Each of those is a place where an
 * accessible name can be lost by accident while the surface still looks right,
 * so each is asserted as a name rather than as a rendering. The interactive DOM
 * order is asserted by actually tabbing, because the bands were rearranged and
 * a reading order that no longer matches the visual one is invisible to axe.
 *
 * Still an automated subset, and still bounded the way the rest of this file is
 * bounded: not screen-reader proof, not a 200%/400% zoom proof, and not a WCAG
 * 2.2 AA claim.
 */
test.describe("the normalized Work List", () => {
  /**
   * macOS Tab traverses text fields and lists only unless Full Keyboard Access
   * is on; Option+Tab is the chord that reaches every control, and Playwright's
   * WebKit reproduces that operating-system default. The chord differs by
   * engine; the path being proved — keyboard, no pointer — does not. Same rule
   * as `work-acceptance.spec.ts`, restated here because this file is driven by
   * its own project list.
   */
  async function pressNextControl(page: Page): Promise<void> {
    await page.keyboard.press(test.info().project.name === "webkit" ? "Alt+Tab" : "Tab");
  }

  /**
   * Put `count` synthetic Tasks in one Work List and hand back the marker that
   * isolates them.
   *
   * The marker goes through the List's own `q=` filter, so the view holds these
   * rows and nothing else a parallel spec may have left; `seedTask` registers
   * each one for the file's `afterEach` disposal, so nothing is left behind.
   */
  async function seedList(
    page: Page,
    count: number,
  ): Promise<{ marker: string; titles: string[] }> {
    const marker = `a11ylist-${test.info().project.name}-${Date.now()}`;
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const titles: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const title = `E2E list a11y task ${marker} ${index}`;
      const created = await seedTask(page, {
        title,
        dueAt: "2026-12-04T17:00:00Z",
        idempotencyKey: `e2e-${marker}-${index}`,
      });
      expect(created.status, `seeding Task ${index} must succeed`).toBe(200);
      titles.push(title);
    }
    await page.goto(`/work?view=all-open&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("list", { name: "Work list" })).toBeVisible();
    await expect(page.locator('[data-testid="task-list-row"]')).toHaveCount(count);
    return { marker, titles };
  }

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  /** WP03-AC-101. */
  test("a populated Work List and its expanded states have no detectable violation", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { titles } = await seedList(page, 2);
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: titles[0]! });
    await expect(row).toHaveCount(1);

    // Load-bearing: a scan of an empty `/work` is vacuous, so the rows are
    // proved present before anything is measured. The count assertion lives in
    // `seedList`; this one names the row the expanded states are opened on.
    expect(await scan(page), "populated Work List accessibility violations").toEqual([]);

    // The Due chooser is a popover: a control that only exists once opened is
    // never seen by a page-level pass over the closed state.
    await row.getByRole("button", { name: /^Due, / }).click();
    await expect(page.getByRole("group", { name: "Due choices" })).toBeVisible();
    expect(await scan(page), "Work List Due chooser accessibility violations").toEqual([]);
    await page.keyboard.press("Escape");

    // More is a disclosure whose expanded content — Cancel Task — does not
    // exist in the DOM until it is opened, and whose own visible wording
    // changes to `Less` while its accessible name must not.
    const more = row.getByTestId("task-list-row-more");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(row.getByRole("button", { name: "Cancel Task", exact: true })).toBeVisible();
    expect(await scan(page), "Work List expanded More accessibility violations").toEqual([]);
  });

  /**
   * WP03-AC-102. The interactive order is proved by tabbing, not by reading the
   * DOM: a `tabindex`, a portal, or a control rendered in a different band would
   * all keep the source order this asserts against while changing the order a
   * keyboard actually visits. Priority is deliberately not in the list — it
   * moved into the state band as plain text and must remain unfocusable.
   */
  test("keyboard order on a row is checkbox, title, Status, Due, Comment, Close, More", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { titles } = await seedList(page, 1);
    const title = titles[0]!;
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: title });

    const expected: Array<[string, ReturnType<typeof row.locator>]> = [
      ["checkbox", row.getByRole("checkbox", { name: `Select ${title}` })],
      ["title", row.getByTestId("task-list-row-title")],
      ["Status", row.getByTestId("task-status-control").getByRole("combobox")],
      ["Due", row.getByRole("button", { name: /^Due, / })],
      ["Comment", row.getByTestId("task-list-row-comment")],
      ["Close", row.getByTestId("task-close-trigger")],
      ["More", row.getByTestId("task-list-row-more")],
    ];

    // The first stop is reached with the keyboard's own entry point rather than
    // by a click, so nothing in this test depends on a pointer.
    await expected[0]![1].focus();
    await expect(expected[0]![1], "the checkbox must take focus first").toBeFocused();
    for (let index = 1; index < expected.length; index += 1) {
      await pressNextControl(page);
      const [name, locator] = expected[index]!;
      await expect(locator, `Tab stop ${index} should be ${name}`).toBeFocused();
    }

    // Priority is a `<span>` in the same band as Status and Due. If it ever
    // acquired a tabindex it would sit between the title and Status above; this
    // states the rule directly so the reason is recorded, not inferred.
    await expect(row.locator("[tabindex]:not([tabindex='-1'])")).toHaveCount(0);
  });

  /**
   * WP03-AC-053 and WP03-AC-127. Two controls gave up visible text in the List
   * and neither may give up its name.
   *
   * Status keeps a real `<label for>` that is hidden visually only, so the
   * association is asserted in the DOM *and* the resolved accessible name is
   * asserted through the engine's own accessibility tree. The Due trigger's
   * visible text is the phrase alone; its accessible name must still be exactly
   * `Due, <phrase>`, which is stated as an equality against the phrase the row
   * is actually showing rather than against a date this test guessed.
   */
  test("Status keeps its name behind a visually hidden label and Due names its value", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { titles } = await seedList(page, 1);
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: titles[0]! });

    const status = row.getByTestId("task-status-control").getByRole("combobox");
    await expect(status).toBeVisible();
    await expect(status, "the Status select must resolve its accessible name").toHaveAccessibleName(
      "Status",
    );
    // The `<label for>` element itself is still in the DOM and still associated:
    // an `aria-label` bolted on after the label was deleted would satisfy the
    // name assertion above while losing the click-to-focus behaviour a real
    // label carries.
    const labelled = await status.evaluate((node) => {
      const control = node as HTMLSelectElement;
      const label = control.labels?.[0] ?? null;
      if (!label) return null;
      const style = getComputedStyle(label);
      return {
        text: label.textContent?.trim() ?? "",
        htmlFor: label.getAttribute("for"),
        id: control.id,
        // A visually hidden label is clipped, not removed: `display: none` or
        // `visibility: hidden` would take it out of the accessibility tree too.
        display: style.display,
        visibility: style.visibility,
      };
    });
    expect(labelled, "Status must still be labelled by a real <label for>").not.toBeNull();
    expect(labelled!.htmlFor, "the label must point at the select").toBe(labelled!.id);
    expect(labelled!.text).toBe("Status");
    expect(labelled!.display, "a hidden label must not be display:none").not.toBe("none");
    expect(labelled!.visibility, "a hidden label must not be visibility:hidden").not.toBe("hidden");

    const due = row.getByRole("button", { name: /^Due, / });
    await expect(due).toBeVisible();
    const phrase = (await due.innerText()).trim();
    // Value-only presentation: the visible text is the phrase alone, with no
    // `Due` prefix drawn beside it.
    expect(phrase.length, "the Due trigger must state a phrase").toBeGreaterThan(0);
    expect(phrase, "the List Due trigger draws no visible `Due` prefix").not.toMatch(/^Due\b/);
    await expect(due, "the Due trigger's accessible name is `Due, <phrase>`").toHaveAccessibleName(
      `Due, ${phrase}`,
    );
  });

  /**
   * WP03-AC-103. Every keyboard-focusable control on a row paints something.
   *
   * Measured the way this suite already measures focus on the Create Task sheet:
   * an outline of at least 1px, or a ring implemented as a box-shadow. Focus is
   * moved with the keyboard rather than with `focus()`, because `:focus-visible`
   * is exactly the rule a pointer-driven focus is allowed not to match — a
   * scripted focus that happened to satisfy this would prove the wrong thing.
   */
  test("every keyboard-focusable row control shows a focus indicator", async ({ page }) => {
    test.setTimeout(180_000);
    const { titles } = await seedList(page, 1);
    const title = titles[0]!;
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: title });

    const checkbox = row.getByRole("checkbox", { name: `Select ${title}` });
    await checkbox.focus();

    const unindicated: string[] = [];
    // Seven controls, entered on the first and stepped through with the same
    // chord the order test uses.
    for (let index = 0; index < 7; index += 1) {
      if (index > 0) await pressNextControl(page);
      const focus = await page.evaluate(() => {
        const active = document.activeElement as HTMLElement | null;
        if (!active) return null;
        const style = getComputedStyle(active);
        return {
          name:
            active.getAttribute("aria-label") ??
            active.getAttribute("data-testid") ??
            `${active.tagName.toLowerCase()}`,
          outlineStyle: style.outlineStyle,
          outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
          boxShadow: style.boxShadow,
          inRow: Boolean(active.closest('[data-testid="task-list-row"]')),
        };
      });
      expect(focus, `something must hold focus at stop ${index}`).not.toBeNull();
      expect(focus!.inRow, `focus left the row at stop ${index}`).toBe(true);
      const hasOutline = focus!.outlineStyle !== "none" && focus!.outlineWidth >= 1;
      const hasRing = focus!.boxShadow !== "none" && focus!.boxShadow !== "";
      if (!hasOutline && !hasRing) unindicated.push(`${focus!.name}: ${JSON.stringify(focus)}`);
    }
    expect(unindicated, "row controls with no visible focus indicator").toEqual([]);
  });
});
