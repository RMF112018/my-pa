import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { enableDiagnostics, signIn } from "./fixtures";

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * After Create, the first list page can already be full from earlier tests in
 * the same disposable database (desktop → tablet → mobile). Wait for the
 * create result, then search so the new Task is locatable.
 */
async function waitForCreateSettled(page: Page, title: string): Promise<void> {
  await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
  await expect(page.getByTestId("mutation-feedback-region").getByText(`Task created: ${title}`)).toBeVisible();
}

async function revealCreatedTask(page: Page, title: string): Promise<void> {
  const trigger = page.getByRole("link", { name: new RegExp(title) });
  if (await trigger.isVisible()) return;
  await page.getByRole("textbox", { name: "Search tasks" }).fill(title);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(trigger).toBeVisible();
}

async function createdTaskAppearsInWork(page: Page, title: string): Promise<void> {
  await waitForCreateSettled(page, title);
  await revealCreatedTask(page, title);
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
    await waitForCreateSettled(page, title);
    // Creation sets no work date, so the canonical Today view must continue to
    // exclude this Task. Read it from the server-backed Unscheduled view instead.
    await page.getByRole("button", { name: "Work views" }).click();
    await page.getByRole("menuitem", { name: "Unscheduled" }).click();
    await revealCreatedTask(page, title);
    const trigger = page.getByRole("link", { name: new RegExp(title) });
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

/** Terminal Task detail: read facts plus comments, no operational editors. */
async function expectTerminalReadOnly(sheet: ReturnType<Page["getByTestId"]>): Promise<void> {
  await expect(sheet.getByTestId("task-terminal-summary")).toBeVisible();
  await expect(sheet.getByTestId("task-edit-title")).toHaveCount(0);
  await expect(sheet.getByTestId("task-edit-priority")).toHaveCount(0);
  await expect(sheet.getByTestId("task-edit-description")).toHaveCount(0);
  await expect(sheet.getByTestId("task-add-description")).toHaveCount(0);
  await expect(sheet.getByTestId("task-status-control")).toHaveCount(0);
  await expect(sheet.getByTestId("task-due-control")).toHaveCount(0);
  await expect(sheet.getByTestId("task-close-control")).toHaveCount(0);
  await expect(sheet.getByRole("button", { name: "Close Task", exact: true })).toHaveCount(0);
  await expect(sheet.getByRole("button", { name: "Cancel Task", exact: true })).toHaveCount(0);
  await expect(sheet.getByRole("textbox", { name: "Title" })).toHaveCount(0);
  await expect(sheet.getByRole("textbox", { name: "Description" })).toHaveCount(0);
  await expect(sheet.getByTestId("task-comments-add")).toBeVisible();
}

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
    await createdTaskAppearsInWork(page, title);
    const trigger = page.getByRole("link", { name: new RegExp(title) });
    await trigger.click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();
    return sheet;
  }

  // TASK-AC-045. Narrow-width reflow is measured at the widths the work
  // package pins. 393 sits between 390 and 430 so a phone-width gap cannot
  // hide wrapping. This is not 200%/400% zoom and not a WCAG 2.2 AA claim.
  for (const width of [320, 375, 390, 393, 430] as const) {
    test(`TASK-AC-045 compact Task detail fits ${width}px without horizontal scroll`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const sheet = await openTask(page);

      expect(await horizontalOverflow(page), `Task detail overflows horizontally at ${width}`).toBeLessThanOrEqual(1);

      // Read-first default: editors stay off the primary surface until asked.
      await expect(sheet.getByRole("textbox", { name: "Description" })).toHaveCount(0);
      await expect(sheet.locator("textarea")).toHaveCount(0);
      await expect(sheet.getByTestId("task-status-control")).toBeVisible();
      await expect(sheet.getByTestId("task-due-control")).toBeVisible();
      await expect(sheet.getByTestId("task-edit-title")).toBeVisible();
      await expect(sheet.getByTestId("task-comments-add")).toBeVisible();
      await expect(sheet.getByRole("textbox", { name: "Add comment" })).toHaveCount(0);

      // Terminal action stays reachable in the primary surface. Under WP07
      // Technical details is not merely collapsed while diagnostics are off —
      // it is not mounted at all, which is a stronger form of the same claim
      // and is asserted as such rather than as an absent `open` attribute.
      await expect(sheet.getByTestId("task-technical-details")).toHaveCount(0);
      const close = sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true });
      await expect(close).toBeVisible();
      await close.scrollIntoViewIfNeeded();
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    });
  }

  test("the default Task detail keeps description and comments closed until Edit or Add", async ({
    page,
  }) => {
    const sheet = await openTask(page);

    await expect(sheet.getByRole("textbox", { name: "Title" })).toHaveCount(0);
    await expect(sheet.getByRole("textbox", { name: "Description" })).toHaveCount(0);
    await expect(sheet.getByRole("combobox", { name: "Priority" })).toHaveCount(0);
    await expect(sheet.getByTestId("task-status-control")).toBeVisible();
    await expect(sheet.getByTestId("task-due-control")).toBeVisible();
    await expect(sheet.getByTestId("task-edit-title")).toBeVisible();
    await expect(sheet.getByTestId("task-add-description")).toBeVisible();
    await expect(sheet.getByTestId("task-comments-add")).toBeVisible();
    await expect(sheet.getByRole("textbox", { name: "Add comment" })).toHaveCount(0);

    await sheet.getByTestId("task-comments-add").click();
    await expect(sheet.getByRole("textbox", { name: "Add comment" })).toBeVisible();
  });

  test("TASK-AC-042/043 the primary Task surface states no backend token or opaque identifier, and diagnostics keep them", async ({ page }) => {
    // The second half of this test's claim — that diagnostics *keep* the
    // identifiers — only exists in the diagnostics-on mode.
    await enableDiagnostics(page);
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

  /** TASK-AC-024, TASK-AC-025: Close is exactly two activations, with no third interaction
   * and no text entry anywhere in the confirmation. */
  test("closing a Task costs two activations and never asks for authored text", async ({ page }) => {
    const sheet = await openTask(page);
    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();

    const confirmation = sheet.getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await expect(confirmation.locator("input, textarea")).toHaveCount(0);
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeVisible();
    // Entry focus is the non-destructive choice. The confirmation is inline
    // `alertdialog`, not a nested modal — the sheet remains the one dialog.
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await expect(page.getByRole("dialog")).toHaveCount(1);

    await confirmation.getByRole("button", { name: "Confirm Closed" }).click();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expect(sheet.getByTestId("task-terminal-summary")).toBeFocused();
    await expect(sheet.getByTestId("task-status-control")).toHaveCount(0);
    await expect(sheet.getByTestId("task-due-control")).toHaveCount(0);
    await expect(sheet.getByTestId("task-close-control")).toHaveCount(0);
    await expectTerminalReadOnly(sheet);
  });

  test("Keep open and Escape dismiss Close confirmation without acting", async ({ page }) => {
    const sheet = await openTask(page);
    const close = sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true });
    await close.click();

    const confirmation = sheet.getByRole("alertdialog");
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await confirmation.getByRole("button", { name: "Keep open" }).click();
    await expect(sheet.getByRole("alertdialog")).toHaveCount(0);
    await expect(close).toBeFocused();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveCount(0);

    await close.click();
    await expect(sheet.getByRole("alertdialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet.getByRole("alertdialog")).toHaveCount(0);
    await expect(close).toBeFocused();
    await expect(page.getByTestId("task-compact-sheet")).toBeVisible();
  });

  test("a dirty title or description blocks Close until it is saved or discarded", async ({ page }) => {
    const sheet = await openTask(page);
    const close = sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true });
    await expect(close).toBeEnabled();
    await expect(sheet.getByTestId("task-close-blocked-reason")).toHaveCount(0);

    await sheet.getByTestId("task-edit-title").click();
    await sheet.getByRole("textbox", { name: "Title" }).fill("Unsaved title draft");
    await expect(close).toBeDisabled();
    await expect(sheet.getByTestId("task-close-blocked-reason")).toHaveText(
      "Edits must be saved or discarded first.",
    );
    await expect(sheet.getByRole("alertdialog")).toHaveCount(0);

    await sheet.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(close).toBeEnabled();
    await expect(sheet.getByTestId("task-close-blocked-reason")).toHaveCount(0);

    await sheet.getByTestId("task-add-description").click();
    await sheet.getByRole("textbox", { name: "Description", exact: true }).fill("Unsaved description draft");
    await expect(close).toBeDisabled();
    await expect(sheet.getByTestId("task-close-blocked-reason")).toHaveText(
      "Edits must be saved or discarded first.",
    );
  });

  test("Cancel under More is a cancel-only two-step control, not a nested Close", async ({ page }) => {
    const sheet = await openTask(page);
    const more = sheet.getByTestId("task-more-actions");
    await more.locator("summary").click();

    const cancelOnly = more.getByTestId("task-cancel-control");
    await expect(cancelOnly.getByRole("button", { name: "Cancel Task", exact: true })).toBeVisible();
    await expect(cancelOnly.getByRole("button", { name: "Close Task", exact: true })).toHaveCount(0);
    await expect(sheet.getByRole("button", { name: "Close Task", exact: true })).toHaveCount(1);

    await cancelOnly.getByRole("button", { name: "Cancel Task", exact: true }).click();
    const confirmation = cancelOnly.getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await expect(confirmation.getByRole("button", { name: "Confirm Closed" })).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(1);

    await confirmation.getByRole("button", { name: "Confirm Cancelled" }).click();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is cancelled.");
    await expectTerminalReadOnly(sheet);
  });
});

/**
 * WP-POSTUX-05. Close confirmation lock, terminal read, and Workbench sheet
 * focus after Close panel.
 *
 * Not claimed: VoiceOver, a physical iPhone, or a nested modal. The
 * confirmation is the inline `alertdialog` already on the sheet.
 */
test.describe("WP-POSTUX-05 Close pending lock and sheet focus", () => {
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

  async function createAndOpen(
    page: Page,
    title: string,
  ): Promise<{ sheet: ReturnType<Page["getByTestId"]>; taskId: string }> {
    await page.getByRole("button", { name: "New task" }).click();
    await page.getByTestId("task-create-sheet").getByLabel("Title").fill(title);
    await page.getByTestId("task-create-sheet").getByRole("button", { name: "Create", exact: true }).click();
    await createdTaskAppearsInWork(page, title);
    const trigger = page.getByRole("link", { name: new RegExp(title) });
    const listed = await api<{ tasks: { task_id: string; title: string }[] }>(
      page,
      `/api/tasks?q=${encodeURIComponent(title)}&pageSize=50&workView=unscheduled&archived=exclude`,
    );
    expect(listed.status).toBe(200);
    const taskId = listed.body.tasks.find((row) => row.title === title)?.task_id ?? "";
    expect(taskId, "the created Task must be listed").toMatch(/^tsk_/);
    await trigger.click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();
    return { sheet, taskId };
  }

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("while Close is pending the confirmation stays, Keep open is disabled, and Escape is ignored", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const title = `E2E pending close ${test.info().project.name} ${Date.now()}`;
    await page.goto("/work?view=unscheduled");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const { sheet, taskId } = await createAndOpen(page, title);

    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      (url) => url.pathname === `/api/tasks/${taskId}/transition`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await held;
        await route.continue();
      },
    );

    try {
      await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();
      const confirmation = sheet.getByRole("alertdialog");
      await confirmation.getByRole("button", { name: "Confirm Closed" }).click();

      const pending = sheet.getByTestId("task-close-pending-status");
      await expect(pending).toBeVisible();
      await expect(pending).toHaveText("Closing…");
      await expect(pending).toBeFocused();
      await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeDisabled();
      await expect(confirmation.getByRole("button", { name: /Confirm Closed/ })).toBeDisabled();
      await expect(sheet.getByRole("button", { name: "Close Task", exact: true })).toBeDisabled();

      await page.keyboard.press("Escape");
      await expect(confirmation).toBeVisible();
      await expect(page.getByTestId("task-compact-sheet")).toBeVisible();
      await expect(sheet.getByTestId("task-terminal-summary")).toHaveCount(0);
    } finally {
      release();
    }

    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expectTerminalReadOnly(sheet);
  });

  test("Close panel restores the original trigger when the row is still there", async ({ page }) => {
    test.setTimeout(180_000);
    const title = `E2E sheet restore trigger ${test.info().project.name} ${Date.now()}`;
    await page.goto("/work?view=unscheduled");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await createAndOpen(page, title);

    const trigger = page.getByRole("link", { name: new RegExp(title) });
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("Close panel after closing a Task lands on a surviving Work row, never the body", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const marker = `wp05-surv-${test.info().project.name}-${Date.now()}`;
    const doomed = `E2E sheet restore doomed ${marker}`;
    const survivor = `E2E sheet restore survivor ${marker}`;
    await page.goto(`/work?view=unscheduled&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();

    await page.getByRole("button", { name: "New task" }).click();
    await page.getByTestId("task-create-sheet").getByLabel("Title").fill(survivor);
    await page.getByTestId("task-create-sheet").getByRole("button", { name: "Create", exact: true }).click();
    await createdTaskAppearsInWork(page, survivor);

    const { sheet } = await createAndOpen(page, doomed);
    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();
    await sheet.getByRole("alertdialog").getByRole("button", { name: "Confirm Closed" }).click();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expect(page.getByRole("link", { name: new RegExp(doomed) })).toHaveCount(0);
    await expect(page.getByRole("link", { name: new RegExp(survivor) })).toBeVisible();

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(page.getByRole("link", { name: new RegExp(survivor) })).toBeFocused();

    const landed = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return null;
      return {
        tag: active.tagName.toLowerCase(),
        connected: active.isConnected,
        isBody: active === document.body,
        inWork: Boolean(active.closest("section[aria-labelledby='work-heading']")),
        row: active.closest("[data-work-item]")?.getAttribute("data-work-item") ?? null,
        heading: active.id === "work-heading",
      };
    });
    expect(landed, "something must hold focus after Close panel").not.toBeNull();
    expect(landed!.isBody, `focus fell to the body: ${JSON.stringify(landed)}`).toBe(false);
    expect(landed!.connected, `focus landed on a detached node: ${JSON.stringify(landed)}`).toBe(true);
    expect(landed!.inWork, `focus left Work entirely: ${JSON.stringify(landed)}`).toBe(true);
    expect(landed!.row, `focus should be inside a surviving row: ${JSON.stringify(landed)}`).not.toBeNull();
  });

  test("Close panel after closing the last Task lands on the Work heading", async ({ page }) => {
    test.setTimeout(180_000);
    const marker = `wp05-last-${test.info().project.name}-${Date.now()}`;
    const title = `E2E sheet restore last ${marker}`;
    await page.goto(`/work?view=unscheduled&q=${encodeURIComponent(marker)}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const { sheet } = await createAndOpen(page, title);

    await sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }).click();
    await sheet.getByRole("alertdialog").getByRole("button", { name: "Confirm Closed" }).click();
    await expect(sheet.getByTestId("task-terminal-summary")).toHaveText("This task is closed.");
    await expect(page.locator('[data-testid="task-list-row"]')).toHaveCount(0);

    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeFocused();
  });
});

/**
 * WP-TUX-05. Ordinary Task management happens in the list.
 *
 * The point of this package is that routine work costs no navigation: Status,
 * Due, Comment and Close are reachable on the row itself. These run against the
 * real stack, because the guarantees that matter here — the server deciding
 * membership, the result surviving the row that issued it — only exist end to
 * end.
 */
test.describe("operational Work List", () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  /** Creates one synthetic Task and returns its list row. */
  async function seedRow(page: Page, view = "unscheduled") {
    const title = `E2E list op task ${Date.now()}`;
    await page.goto(`/work?view=${view}`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "New task" }).click();
    await page.getByTestId("task-create-sheet").getByLabel("Title").fill(title);
    await page.getByTestId("task-create-sheet").getByRole("button", { name: "Create", exact: true }).click();
    await createdTaskAppearsInWork(page, title);
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: title });
    await expect(row).toBeVisible();
    return { row, title };
  }

  const feedback = (page: Page) => page.getByTestId("mutation-feedback-region");

  /** TASK-AC-015: Status is changed inline from the list row, without opening Task detail. */
  test("changes Status from the row without opening Task detail", async ({ page }) => {
    const { row } = await seedRow(page);

    await row.getByRole("combobox").selectOption({ label: "In progress" });

    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();
    // Detail was never opened: this is the whole point of the package.
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
  });

  /** TASK-AC-016: Due is changed inline from the list row, without opening Task detail. */
  test("changes Due from the row without opening Task detail", async ({ page }) => {
    const { row } = await seedRow(page);

    await row.getByRole("button", { name: /^Due, / }).click();
    await page.getByRole("button", { name: "Today", exact: true }).click();

    await expect(feedback(page).getByText(/^Due date moved to /)).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
  });

  test("closes from the row in two activations, asking for no authored text", async ({ page }) => {
    const { row, title } = await seedRow(page);

    await row.getByRole("button", { name: /^Close /, exact: false }).click();
    const confirmation = page.getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    // No note, no keyboard: closing is a decision, not an essay.
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await confirmation.getByRole("button", { name: "Confirm Closed" }).click();

    // The result outlives the row that issued it.
    await expect(feedback(page).getByText(new RegExp(`${title}.*closed`))).toBeVisible();
  });

  test("keeps the list read-only on Board, which a later package owns", async ({ page }) => {
    await seedRow(page);
    await page.goto("/work?view=unscheduled&perspective=board");
    await expect(page.getByRole("region", { name: "Task lifecycle board" })).toBeVisible();
    // The operational row is a List surface; Board keeps the shared card.
    await expect(page.locator('[data-testid="task-list-row"]')).toHaveCount(0);
  });

  /** TASK-AC-042, TASK-AC-043: the row carries no opaque identifier and no raw lifecycle or
   * priority token. */
  test("states no backend vocabulary on the row", async ({ page }) => {
    const { row } = await seedRow(page);
    const text = await row.innerText();
    expect(text).toContain("Status");
    for (const token of ["in_progress", "lifecycle", "p1", "p2", "p3", "p4", "tsk_"]) {
      expect(text, `row states "${token}"`).not.toContain(token);
    }
  });
});

/**
 * WP-TUX-06. Board and Calendar are operational surfaces, and neither asks for a
 * mouse drag.
 *
 * Everything below drives the shipped controls in a real browser against the
 * real stack. The fixtures are synthetic Tasks created through the product's own
 * create sheet and addressed by a `Date.now()` marker, so no assertion here can
 * be satisfied by data this suite did not make.
 *
 * What these tests do **not** claim: they are not a screen-reader proof, not a
 * 200%/400% zoom proof and not a WCAG 2.2 AA claim. WP30 owns those.
 */
test.describe("operational Board and Calendar", () => {
  // A touch-capable context on every project, so the tap path is a real
  // `touchstart`/`touchend` rather than a synthetic mouse click. The viewport is
  // left to the project, which is what makes the same file meaningful on
  // desktop, tablet and mobile.
  test.use({ hasTouch: true });

  /** The shell-persistent feedback region, which outlives any card. */
  const feedback = (page: Page) => page.getByTestId("mutation-feedback-region");

  /**
   * The narrow widths this work package pins for TASK-AC-045.
   *
   * 393 is WP-TUX-06's addition: the repaired Status control is now a definite
   * 44 CSS px tall, and a definite height is exactly the kind of change that
   * shows up as card-density or wrapping pressure at one specific width. 393 is
   * the modern default-phone width that sits between the two the suite already
   * pinned, so the matrix has no gap where the pressure could hide.
   */
  const NARROW_WIDTHS = [320, 375, 390, 393, 430] as const;

  /**
   * The full width matrix the geometry of the Status control is asserted over:
   * every narrow width above at the suite's mobile height, plus tablet and
   * desktop. Heights follow the convention already in this file — 844 for the
   * narrow widths, and the `tablet`/`desktop` project viewports for the rest.
   */
  const STATUS_GEOMETRY_MATRIX = [
    ...NARROW_WIDTHS.map((width) => ({ width, height: 844 })),
    { width: 768, height: 1024 },
    { width: 1280, height: 800 },
  ] as const;

  /** This shell's row height, and the floor every touch target is held to. */
  const ROW_HEIGHT = 44;

  /**
   * Chromium drives a closed `<select>` from the keyboard alone: ArrowDown moves
   * the selection and fires `change`. Firefox and WebKit open a native popup
   * window that Playwright cannot address, so on those engines the *selection*
   * is made with `selectOption` — the same event sequence the platform picker
   * produces — while the keyboard *reachability* of the control is asserted on
   * every engine by Tab-focus. Stated rather than hidden: this is a limit of the
   * driver, not a second code path in the product.
   */
  function keyboardSelectIsDrivable(): boolean {
    return ["desktop", "tablet", "mobile"].includes(test.info().project.name);
  }

  /**
   * Move focus to the next control, with the keyboard, on whichever engine is
   * running.
   *
   * macOS Tab traverses text fields and lists only unless Full Keyboard Access
   * is switched on; Option+Tab is the chord that reaches every control, and
   * Playwright WebKit reproduces that operating-system default faithfully. This
   * is a platform convention, not a product behaviour, so the *chord* differs by
   * engine while the path being proved — keyboard, no pointer — does not.
   */
  async function pressNextControl(page: Page): Promise<void> {
    await page.keyboard.press(test.info().project.name === "webkit" ? "Alt+Tab" : "Tab");
  }

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  /**
   * Creates one synthetic Task through the product's create sheet and returns
   * its title. `due` is a civil date (`YYYY-MM-DD`) typed into the sheet's own
   * Due field, so a Calendar marker exists without any back-channel write.
   */
  async function seedTask(page: Page, options: { due?: string } = {}): Promise<string> {
    const title = `E2E surface task ${test.info().project.name} ${Date.now()}`;
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "New task" }).click();
    const sheet = page.getByTestId("task-create-sheet");
    await sheet.getByLabel("Title").fill(title);
    if (options.due) await sheet.getByLabel("Due", { exact: true }).fill(options.due);
    await sheet.getByRole("button", { name: "Create", exact: true }).click();
    await expect(sheet).toHaveCount(0);
    return title;
  }

  /** A civil date a few days out, so the Due marker is neither today nor overdue. */
  function civilDateAhead(days: number): string {
    const date = new Date(Date.now() + days * 86_400_000);
    return date.toISOString().slice(0, 10);
  }

  function boardCard(page: Page, title: string) {
    return page.locator('[data-testid="task-board-card"]').filter({ hasText: title });
  }

  function calendarMarker(page: Page, title: string) {
    return page.locator('[data-testid="task-calendar-marker"]').filter({ hasText: title });
  }

  /**
   * TASK-AC-017. Status changes from the Board card itself — by keyboard, and by
   * tap — and Task detail is never opened to do it.
   */
  test("TASK-AC-017 Board changes Status by keyboard and by tap without opening Task detail", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const title = await seedTask(page);
    await page.getByRole("button", { name: "Board" }).click();
    await expect(page).toHaveURL(/perspective=board/);
    await expect(page.getByRole("region", { name: "Task lifecycle board" })).toBeVisible();

    const card = boardCard(page, title);
    await expect(card).toHaveCount(1);

    // Keyboard reachability, asserted on every engine: the card's own title is
    // focusable and Tab from it lands on the Status control. Nothing here hovers
    // and nothing here drags.
    await card.getByTestId("task-board-card-title").focus();
    await page.keyboard.press("Tab");
    const status = card.getByTestId("task-status-control").getByRole("combobox");
    await expect(status).toBeFocused();

    if (keyboardSelectIsDrivable()) {
      // Open -> Waiting, from the keyboard alone: type-ahead on the focused
      // control, which is how a keyboard user changes a closed select.
      await page.keyboard.press("w");
    } else {
      await status.selectOption({ label: "Waiting" });
    }
    await expect(feedback(page).getByText("Status changed to Waiting")).toBeVisible();
    // The whole point of the criterion: no full detail was opened to do it.
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(page).toHaveURL(/perspective=board/);

    // The tap path. The control is a real touch target first, and the touch
    // lands on it.
    const moved = boardCard(page, title).getByTestId("task-status-control").getByRole("combobox");
    await expect(moved).toBeVisible();
    await moved.tap();
    // Playwright cannot drive a native option list, on any engine. The selection
    // itself is therefore made with `selectOption`, which is the event sequence
    // the platform picker produces once the tap has opened it.
    await moved.selectOption({ label: "In progress" });
    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
  });

  /**
   * The tap path is only a path if the target can be hit.
   *
   * WCAG 2.5.8 (AA) sets the minimum target at 24x24 CSS px; this shell builds
   * its controls to a 44px row height, which is the floor asserted here.
   *
   * **Every control is proved on its own, and nothing here is expected to
   * fail.** WebKit once rendered the Status `<select>` 22 CSS px tall, because a
   * default-appearance select in that engine does not honour `min-height`;
   * `task-status-control.tsx` now gives it a definite `h-11`, and the WebKit
   * expected-failure this test used to carry is gone.
   *
   * **Exactly what is proved, and where the claim stops.** The floor is
   * *measured* on Chromium (the `desktop`, `tablet` and `mobile` projects) at
   * 119x44, and on **macOS** WebKit at 106x44 — the engine and machine where
   * the 22px defect actually reproduces, which is what makes that measurement
   * evidence for the fix.
   *
   * It does not hold on "every engine", and a green run here on a CI runner is
   * weaker than it looks: the Linux Playwright builds render this control 44px
   * whether or not the fix is present, so neither their WebKit nor their
   * Firefox result can detect this defect. That was established by running a
   * branch with the fix removed. The full explanation, and the pointer to the
   * guard that does fail, lives on the sizing-contract test in
   * `src/components/tasks/task-status-control.test.tsx` — deliberately in one
   * place rather than restated here.
   *
   * The assertions below are unconditional on whatever engine runs them, which
   * is what keeps this test useful across all of them: it still proves the
   * absence of overflow, clipping and layout regression everywhere it runs.
   *
   * Each control is still reported by name. The five checks are `expect.soft`,
   * which records a failure and keeps going instead of aborting at the first
   * one, so a single run enumerates *every* undersized control rather than only
   * the first; the test still fails, and no floor is lowered to buy that. The
   * only conditional below is the `continue` after a missing box, which guards
   * a TypeError on a measurement that has already been recorded as failed.
   */
  test("TASK-AC-017 the Board Status and Due controls are real touch targets", async ({ page }) => {
    test.setTimeout(180_000);
    const title = await seedTask(page);
    await page.goto("/work?view=all-open&perspective=board");
    const card = boardCard(page, title);
    await expect(card).toHaveCount(1);

    // Status is measured first and named first: this is the control the WebKit
    // defect was in, and it is never again allowed to fail silently behind an
    // aggregate or an expected failure.
    for (const [name, control] of [
      ["Status", card.getByTestId("task-status-control").getByRole("combobox")],
      ["Due", card.getByRole("button", { name: /^Due, / })],
      ["Comment", card.getByTestId("task-board-card-comment")],
      ["Close Task", card.getByRole("button", { name: "Close Task", exact: true })],
      ["More", card.getByTestId("task-board-card-more")],
    ] as const) {
      const box = await control.boundingBox();
      expect.soft(box, `${name} has no box on the Board card`).not.toBeNull();
      // Recorded above; this only avoids dereferencing null for the next two.
      if (box === null) continue;
      expect.soft(box.height, `${name} is below this shell's 44px row height`).toBeGreaterThanOrEqual(44);
      expect.soft(box.width, `${name} is below WCAG 2.5.8's 24px minimum width`).toBeGreaterThanOrEqual(24);
    }
  });

  /**
   * TASK-AC-047. No Board operation depends on a drag: Due, More, Comment and
   * Close are each driven here by the keyboard or by a tap, and the surface
   * carries no drag affordance for any of them.
   */
  test("TASK-AC-047 every Board operation has a keyboard or tap path and nothing is drag-only", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const title = await seedTask(page);
    await page.goto("/work?view=all-open&perspective=board");
    const board = page.getByRole("region", { name: "Task lifecycle board" });
    await expect(board).toBeVisible();
    const card = boardCard(page, title);
    await expect(card).toHaveCount(1);

    // Nothing on this surface is draggable, and nothing announces itself as
    // draggable: a drag-only path cannot exist where there is no drag.
    await expect(board.locator('[draggable="true"]')).toHaveCount(0);
    await expect(board.locator("[aria-grabbed]")).toHaveCount(0);
    await expect(board.locator('[aria-roledescription*="drag" i]')).toHaveCount(0);
    await expect(board.getByText(/drag/i)).toHaveCount(0);

    // Due, from the keyboard alone. Opening the control focuses its first
    // choice, so Enter twice is the whole interaction.
    const due = card.getByRole("button", { name: /^Due, / });
    await due.focus();
    await expect(due).toBeFocused();
    await page.keyboard.press("Enter");
    const today = card.getByRole("button", { name: "Today", exact: true });
    await expect(today).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(feedback(page).getByText(/^Due date moved to /)).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);

    // More, from the keyboard alone. It exists to reveal Cancel, and it does.
    const more = boardCard(page, title).getByTestId("task-board-card-more");
    await more.focus();
    await page.keyboard.press("Enter");
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(boardCard(page, title).getByRole("button", { name: "Cancel Task", exact: true })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(more).toHaveAttribute("aria-expanded", "false");

    // Comment, by tap. It opens the Task's own Activity rather than a second
    // comment implementation, and closing returns focus to the control tapped.
    const comment = boardCard(page, title).getByTestId("task-board-card-comment");
    await comment.tap();
    await expect(page.getByTestId("task-compact-sheet")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(boardCard(page, title).getByTestId("task-board-card-comment")).toBeFocused();

    // Close, from the keyboard alone, in exactly two activations. The
    // confirmation opens on the non-destructive choice, so Confirm is one Tab
    // away and is never the thing Enter lands on by accident.
    const close = boardCard(page, title).getByRole("button", { name: "Close Task", exact: true });
    await close.focus();
    await page.keyboard.press("Enter");
    const confirmation = boardCard(page, title).getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await pressNextControl(page);
    await expect(confirmation.getByRole("button", { name: "Confirm Closed" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(feedback(page).getByText(new RegExp(`${title}.*closed`))).toBeVisible();
  });

  /**
   * TASK-AC-047, on the Calendar. The one editable marker is operable from the
   * keyboard, and the surface offers no drag for it either.
   */
  test("TASK-AC-047 the Calendar Due marker is operable from the keyboard and offers no drag", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const title = await seedTask(page, { due: civilDateAhead(4) });
    await page.goto("/work?view=all-open&perspective=calendar");
    const calendar = page.getByRole("heading", { name: "Work calendar", level: 2 }).locator("..");
    await expect(calendar).toBeVisible();

    const marker = calendarMarker(page, title);
    await expect(marker).toHaveCount(1);
    await expect(calendar.locator('[draggable="true"]')).toHaveCount(0);
    await expect(calendar.locator("[aria-grabbed]")).toHaveCount(0);
    await expect(calendar.locator('[aria-roledescription*="drag" i]')).toHaveCount(0);

    const due = marker.getByRole("button", { name: /^Due, / });
    await due.focus();
    await expect(due).toBeFocused();
    await page.keyboard.press("Enter");
    // Opening lands on the first choice; Tab reaches the next one. No pointer.
    await expect(marker.getByRole("button", { name: "Today", exact: true })).toBeFocused();
    await pressNextControl(page);
    await expect(marker.getByRole("button", { name: "Tomorrow", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(feedback(page).getByText(/^Due date moved to /)).toBeVisible();
  });

  /**
   * TASK-AC-045. Board and Calendar at 320, 375, 390 and 430 CSS px: no
   * horizontal scroll anywhere, and the operations still there to be operated.
   * This is a narrow-viewport reflow measurement, not browser zoom.
   */
  for (const width of NARROW_WIDTHS) {
    test(`TASK-AC-045 Board and Calendar are operable at ${width}px with no horizontal scroll`, async ({
      page,
    }) => {
      test.setTimeout(180_000);
      const title = await seedTask(page, { due: civilDateAhead(4) });

      await page.setViewportSize({ width, height: 844 });

      await page.goto("/work?view=all-open&perspective=board");
      await expect(page.getByRole("region", { name: "Task lifecycle board" })).toBeVisible();
      const card = boardCard(page, title);
      await expect(card).toHaveCount(1);
      // Every operation is present and enabled, not merely rendered somewhere
      // off to the side.
      const status = card.getByTestId("task-status-control").getByRole("combobox");
      await expect(status).toBeVisible();
      await expect(status).toBeEnabled();
      for (const [name, control] of [
        ["Due", card.getByRole("button", { name: /^Due, / })],
        ["Comment", card.getByTestId("task-board-card-comment")],
        ["Close Task", card.getByRole("button", { name: "Close Task", exact: true })],
        ["More", card.getByTestId("task-board-card-more")],
      ] as const) {
        await expect(control, `${name} is not visible at ${width}`).toBeVisible();
        await expect(control, `${name} is not enabled at ${width}`).toBeEnabled();
      }
      expect(
        await horizontalOverflow(page),
        `Board overflows horizontally at ${width}`,
      ).toBeLessThanOrEqual(1);
      // The card itself fits, so the absence of document overflow is not a
      // clipped card sitting outside it.
      const cardBox = await card.boundingBox();
      expect(cardBox, "Board card has no box").not.toBeNull();
      expect(cardBox!.x + cardBox!.width, `Board card exceeds ${width}`).toBeLessThanOrEqual(width + 1);

      // WP-TUX-06. The Status control is measured at every pinned width, not
      // merely found: a definite 44px height is what the WebKit repair added,
      // and a narrow card is where a definite height would push something out.
      const statusBox = await status.boundingBox();
      expect(statusBox, `Status has no box at ${width}`).not.toBeNull();
      expect(
        statusBox!.height,
        `Status is below this shell's ${ROW_HEIGHT}px row height at ${width}`,
      ).toBeGreaterThanOrEqual(ROW_HEIGHT);
      expect(
        statusBox!.x + statusBox!.width,
        `Status escapes its card at ${width}`,
      ).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);
      // Nothing is clipped away inside the card either: a card whose own
      // content is wider than its box is hiding an operation, not fitting.
      expect(
        await card.evaluate((el) => el.scrollWidth - el.clientWidth),
        `Board card clips its own content at ${width}`,
      ).toBeLessThanOrEqual(1);

      await page.goto("/work?view=all-open&perspective=calendar");
      await expect(page.getByRole("heading", { name: "Work calendar", level: 2 })).toBeVisible();
      const marker = calendarMarker(page, title);
      await expect(marker).toHaveCount(1);
      await expect(marker.getByRole("button", { name: /^Due, / })).toBeVisible();
      await expect(marker.getByRole("button", { name: /^Due, / })).toBeEnabled();
      expect(
        await horizontalOverflow(page),
        `Calendar overflows horizontally at ${width}`,
      ).toBeLessThanOrEqual(1);
      const markerBox = await marker.boundingBox();
      expect(markerBox, "Calendar marker has no box").not.toBeNull();
      expect(markerBox!.x + markerBox!.width, `Calendar marker exceeds ${width}`).toBeLessThanOrEqual(
        width + 1,
      );

      // Opening the Due choices must not push the page sideways either: a
      // popover is where a narrow layout usually breaks.
      await marker.getByRole("button", { name: /^Due, / }).click();
      await expect(marker.getByRole("button", { name: "Today", exact: true })).toBeVisible();
      expect(
        await horizontalOverflow(page),
        `Calendar Due choices overflow horizontally at ${width}`,
      ).toBeLessThanOrEqual(1);
    });
  }

  /**
   * WP-TUX-06. The repaired Status control, measured across the whole width
   * matrix, on a populated Board.
   *
   * **Why this test exists.** `task-status-control.tsx` now sets a *definite*
   * height (`h-11`) on the Task Status `<select>`, because WebKit resolves a
   * bare `min-height` down to the intrinsic 18px and rendered the control 22 CSS
   * px tall against this shell's 44px target. A definite height is the correct
   * repair, and it is also the kind of change that buys its target back out of
   * some other budget: card density, wrapping, clipping, horizontal overflow —
   * most plausibly at 320px, the narrowest width this product claims. Nothing
   * proved it did not. This does.
   *
   * One test rather than one per size, deliberately: a single seeded Task is
   * carried across every viewport, so the same card is measured throughout and
   * the matrix costs one seed instead of seven. The assertions are `expect.soft`
   * so that one run reports *every* width that fails rather than stopping at the
   * first; nothing is lowered to achieve that, and the test still fails.
   *
   * The measured height at each size is printed, so the record carries numbers
   * rather than the word "passed".
   *
   * Not claimed: this is a viewport measurement, not browser zoom, not a
   * screen-reader proof, and not a WCAG 2.2 AA claim. WP30 owns those.
   */
  test("WP-TUX-06 the Board Status control holds 44px across the width matrix without layout pressure", async ({
    page,
  }) => {
    test.setTimeout(300_000);
    const title = await seedTask(page, { due: civilDateAhead(4) });
    const measured: string[] = [];

    for (const { width, height } of STATUS_GEOMETRY_MATRIX) {
      await page.setViewportSize({ width, height });
      await page.goto("/work?view=all-open&perspective=board");
      await expect(page.getByRole("region", { name: "Task lifecycle board" })).toBeVisible();
      const card = boardCard(page, title);
      await expect(card).toHaveCount(1);
      const status = card.getByTestId("task-status-control").getByRole("combobox");
      await expect(status).toBeVisible();

      const statusBox = await status.boundingBox();
      const cardBox = await card.boundingBox();
      expect.soft(statusBox, `Status has no box at ${width}x${height}`).not.toBeNull();
      expect.soft(cardBox, `Board card has no box at ${width}x${height}`).not.toBeNull();
      if (statusBox === null || cardBox === null) continue;

      measured.push(
        `${width}x${height}: Status ${Math.round(statusBox.width)}x${Math.round(statusBox.height)}, ` +
          `card ${Math.round(cardBox.width)}x${Math.round(cardBox.height)}`,
      );

      // The floor the repair exists to hold.
      expect
        .soft(
          statusBox.height,
          `Status is below this shell's ${ROW_HEIGHT}px row height at ${width}x${height}`,
        )
        .toBeGreaterThanOrEqual(ROW_HEIGHT);
      // The taller control stays inside the card that owns it, and the card
      // stays inside the viewport. Same tolerance the narrow-width test uses.
      expect
        .soft(statusBox.x + statusBox.width, `Status escapes its card at ${width}x${height}`)
        .toBeLessThanOrEqual(cardBox.x + cardBox.width + 1);
      expect
        .soft(cardBox.x + cardBox.width, `Board card exceeds ${width} at ${width}x${height}`)
        .toBeLessThanOrEqual(width + 1);
      // No clipping: a card whose own content is wider than its box has hidden
      // an operation rather than fitted it.
      expect
        .soft(
          await card.evaluate((el) => el.scrollWidth - el.clientWidth),
          `Board card clips its own content at ${width}x${height}`,
        )
        .toBeLessThanOrEqual(1);
      // The document does not move sideways. The existing tolerance, unchanged.
      expect
        .soft(
          await horizontalOverflow(page),
          `Board overflows horizontally at ${width}x${height}`,
        )
        .toBeLessThanOrEqual(1);

      // Every operation is still there and still operable — the taller Status
      // must not have pushed a neighbour off the card or under another.
      for (const [name, control] of [
        ["Due", card.getByRole("button", { name: /^Due, / })],
        ["Comment", card.getByTestId("task-board-card-comment")],
        ["Close Task", card.getByRole("button", { name: "Close Task", exact: true })],
        ["More", card.getByTestId("task-board-card-more")],
      ] as const) {
        await expect.soft(control, `${name} is not visible at ${width}x${height}`).toBeVisible();
        await expect.soft(control, `${name} is not enabled at ${width}x${height}`).toBeEnabled();
      }
    }

    console.log(`WP-TUX-06 Status geometry matrix:\n  ${measured.join("\n  ")}`);
    expect(measured, "no viewport in the matrix was measured").toHaveLength(
      STATUS_GEOMETRY_MATRIX.length,
    );

    // Present is not operable. The narrowest viewport in the matrix changes
    // Status for real and the change survives a reload from the server, so the
    // taller control is proved to work rather than merely to fit.
    await page.setViewportSize({ width: 320, height: 844 });
    await page.goto("/work?view=all-open&perspective=board");
    const narrowCard = boardCard(page, title);
    await expect(narrowCard).toHaveCount(1);
    const narrowStatus = narrowCard.getByTestId("task-status-control").getByRole("combobox");
    await narrowStatus.selectOption({ label: "In progress" });
    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    expect(await horizontalOverflow(page), "Board overflows after a Status change at 320").toBeLessThanOrEqual(1);

    await page.goto("/work?view=all-open&perspective=board");
    const reloaded = boardCard(page, title).getByTestId("task-status-control").getByRole("combobox");
    await expect(reloaded).toBeVisible();
    expect(
      await reloaded.evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? ""),
      "the Status change did not round-trip at 320",
    ).toBe("In progress");
    const reloadedBox = await reloaded.boundingBox();
    expect(reloadedBox, "Status has no box after the round-trip at 320").not.toBeNull();
    expect(
      reloadedBox!.height,
      `Status is below this shell's ${ROW_HEIGHT}px row height after the round-trip at 320`,
    ).toBeGreaterThanOrEqual(ROW_HEIGHT);
  });
});

/**
 * WP-POSTUX-03. The Work List, normalized.
 *
 * The audited List was a vertical stack of per-row cards: every Task drew its
 * own border, its own rounding and its own surface, so twenty Tasks read as
 * twenty islands rather than as one list. Normalization removes that chrome from
 * the row and gives the grouping to the list itself — one surface, rows
 * separated by dividers — while the Commitment list, which is not a Task list
 * and was not audited as one, keeps the card treatment it has.
 *
 * **Everything below is asserted on computed style or on live geometry, never on
 * a class list.** A class name is a claim about intent; `border-width: 0px` read
 * back out of the engine is the thing the reader's eye actually meets, and it
 * stays true through a rule that lost to specificity, a purge that dropped a
 * class, or a token that changed underneath. The one exception is `data-state`,
 * which is a semantic hook the package pins by name and which this file
 * therefore reads by name.
 *
 * **What is not claimed.** This is not a screen-reader proof, not a 200%/400%
 * zoom proof and not a WCAG 2.2 AA claim. `accessibility.spec.ts` owns the axe
 * scan and the keyboard-order and accessible-name contracts for this surface;
 * `mobile-foundation.spec.ts` owns the coarse-pointer sizing and the narrow
 * geometry. This file owns the arrangement and the operations.
 */
test.describe("normalized Work List", () => {
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

  /**
   * Seeded Tasks, and putting them back.
   *
   * `e2e/stack.sh` builds one disposable database for the whole run and an open
   * Task sits in several Work views at once, so a row left behind changes what
   * every later spec sees. `today-tasks.spec.ts` leaked exactly this way and put
   * four latent defects on screen as a red job. Disposal is deterministic — each
   * row is read, one already terminal is left alone, and the rest are
   * transitioned with the version that read returned — and it runs after a
   * failed test as well as a passing one, because a test that fails after
   * seeding has still seeded.
   */
  const seeded: string[] = [];

  /** See `today-tasks.spec.ts`: scaffolding was never done, so it is not "Closed". */
  const TEARDOWN_STATE = "cancelled";

  async function seedTaskRow(
    page: Page,
    input: { title: string; dueAt?: string; priority?: string; idempotencyKey: string },
  ): Promise<string> {
    const created = await api<{ task?: { task_id: string } }>(page, "/api/tasks", {
      method: "POST",
      body: {
        title: input.title,
        ...(input.dueAt ? { dueAt: input.dueAt } : {}),
        ...(input.priority ? { priority: input.priority } : {}),
        idempotencyKey: input.idempotencyKey,
      },
    });
    expect(created.status, `seeding "${input.title}" must succeed`).toBe(200);
    const taskId = created.body.task?.task_id ?? "";
    expect(taskId, "the BFF must answer with a Task id").not.toBe("");
    seeded.push(taskId);
    return taskId;
  }

  test.beforeEach(async ({ page }) => {
    seeded.length = 0;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test.afterEach(async ({ page }) => {
    const ids = [...seeded];
    seeded.length = 0;
    for (const taskId of ids) {
      const read = await api<{ task?: { version: number; lifecycle_state: string } }>(
        page,
        `/api/tasks/${taskId}`,
      );
      if (read.status !== 200 || !read.body.task) continue;
      if (["completed", "cancelled"].includes(read.body.task.lifecycle_state)) continue;
      const disposed = await api<unknown>(page, `/api/tasks/${taskId}/transition`, {
        method: "POST",
        body: {
          toState: TEARDOWN_STATE,
          expectedVersion: read.body.task.version,
          idempotencyKey: `wp03-teardown-${taskId}-${Date.now()}`,
        },
      });
      expect(
        disposed.status,
        `teardown must dispose of seeded Task ${taskId}: ${JSON.stringify(disposed.body)}`,
      ).toBeLessThan(300);
    }
  });

  /** A marker no other spec can produce, so the `q=` filter isolates these rows. */
  function marker(): string {
    return `wp03-${test.info().project.name}-${Date.now()}`;
  }

  /** Seed `count` Tasks and open the List filtered down to exactly them. */
  async function seedList(
    page: Page,
    count: number,
    options: { priority?: string } = {},
  ): Promise<{ tag: string; titles: string[] }> {
    const tag = marker();
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const titles: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const title = `E2E normalized row ${tag} ${index}`;
      await seedTaskRow(page, {
        title,
        priority: options.priority,
        idempotencyKey: `e2e-${tag}-${index}`,
      });
      titles.push(title);
    }
    await page.goto(`/work?view=all-open&q=${encodeURIComponent(tag)}`);
    await expect(page.getByRole("list", { name: "Work list" })).toBeVisible();
    await expect(page.locator('[data-testid="task-list-row"]')).toHaveCount(count);
    return { tag, titles };
  }

  function listRow(page: Page, title: string) {
    return page.locator('[data-testid="task-list-row"]').filter({ hasText: title });
  }

  const feedback = (page: Page) => page.getByTestId("mutation-feedback-region");

  /** Every border width and the corner radius the engine resolved, in CSS px. */
  async function chrome(locator: ReturnType<Page["locator"]>) {
    return locator.evaluate((node) => {
      const style = getComputedStyle(node);
      const px = (value: string) => Number.parseFloat(value) || 0;
      return {
        borders: [
          px(style.borderTopWidth),
          px(style.borderRightWidth),
          px(style.borderBottomWidth),
          px(style.borderLeftWidth),
        ],
        radius: Math.max(
          px(style.borderTopLeftRadius),
          px(style.borderTopRightRadius),
          px(style.borderBottomLeftRadius),
          px(style.borderBottomRightRadius),
        ),
        boxShadow: style.boxShadow,
        background: style.backgroundColor,
      };
    });
  }

  /**
   * WP03-AC-043. The Task List is one grouped surface, not a column of cards.
   *
   * Two things are measured, and neither is a class name. First, the row root
   * draws no border of its own on any edge and no rounding — that is what made
   * each Task an island. Second, the rows are actually separated: every row
   * after the first carries a divider rule, read as a non-zero top border on the
   * row or on the list item that holds it, which is where both of the plausible
   * implementations (a `divide-y` on the list, a border on the row) put it.
   *
   * Stated rather than assumed: this asserts a divider *exists*, not how thick
   * it is. Pinning the exact hairline would be a brittle pixel contract of the
   * kind this package explicitly forbids.
   */
  test("WP03-AC-043 the Task List renders as one grouped list with dividers, not per-row cards", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await seedList(page, 3);

    const rows = page.locator('[data-testid="task-list-row"]');
    const count = await rows.count();
    // Guard the guard: one row cannot demonstrate a divider between rows.
    expect(count, "the grouping claim needs more than one row").toBeGreaterThanOrEqual(3);

    const carded: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const measured = await chrome(rows.nth(index));
      if (measured.borders.some((width) => width > 0.01)) {
        carded.push(`row ${index} borders ${measured.borders.join("/")}`);
      }
      if (measured.radius > 0.01) carded.push(`row ${index} radius ${measured.radius}`);
      if (measured.boxShadow !== "none" && measured.boxShadow !== "") {
        carded.push(`row ${index} shadow ${measured.boxShadow}`);
      }
    }
    expect(carded, "rows still carry per-row card chrome").toEqual([]);

    // All the rows belong to one list, which is what "grouped" means.
    const list = page.getByRole("list", { name: "Work list" });
    expect(
      await list.evaluate((node) => node.querySelectorAll('[data-testid="task-list-row"]').length),
      "every row must live in the one Work list",
    ).toBe(count);

    const undivided = await list.evaluate((node) => {
      const px = (value: string) => Number.parseFloat(value) || 0;
      const rowRoots = Array.from(node.querySelectorAll('[data-testid="task-list-row"]'));
      const missing: string[] = [];
      /*
        A divider between two rows is a rule on either facing edge, and which
        edge it lands on is an implementation detail: Tailwind v4's `divide-y`
        puts a *bottom* border on every child but the last, where v3 put a top
        border on every child but the first. Asserting one edge would make this
        a test of the utility's internals rather than of the separation a
        reader actually sees, so both edges of the pair count.
      */
      rowRoots.forEach((row, index) => {
        if (index === 0) return;
        const previous = rowRoots[index - 1];
        const rule = Math.max(
          px(getComputedStyle(row).borderTopWidth),
          px(getComputedStyle(previous).borderBottomWidth),
          row.parentElement ? px(getComputedStyle(row.parentElement).borderTopWidth) : 0,
          previous.parentElement ? px(getComputedStyle(previous.parentElement).borderBottomWidth) : 0,
        );
        if (rule <= 0.01) missing.push(`rows ${index - 1} and ${index} are not separated by a rule`);
      });
      return missing;
    });
    expect(undivided, "a grouped list separates its rows with dividers").toEqual([]);
  });

  /**
   * WP03-AC-039. The Commitment list is not a Task list and keeps its cards.
   *
   * The normalization is scoped to the Work Task List. A Commitment row is a
   * different object with a different reading — counterparty, direction, state,
   * obligation deadline — and it was not audited as a dense operational list, so
   * flattening it would be a change nobody asked for. Measured on the same
   * computed properties the Task row is measured on, so the two claims cannot
   * drift apart.
   *
   * The Commitment is created through the product's own form (the only path that
   * writes the origin evidence the canonical endpoint requires) and closed
   * through the product's own closure form in the same test, so nothing open is
   * left behind. `work-mutations.spec.ts` drives the identical pair of forms.
   */
  test("WP03-AC-039 the Commitment list keeps its card treatment", async ({ page }) => {
    test.setTimeout(180_000);
    const tag = marker();
    const title = `E2E obligation ${tag}`;

    await page.goto(`/work?view=commitments&commitment=all&q=${encodeURIComponent(tag)}`);
    await page.getByRole("button", { name: "New commitment" }).click();
    const create = page.getByRole("heading", { name: "Create commitment" }).locator("..");
    await create.getByLabel("Summary").fill(title);
    await create.getByLabel("Counterparty").selectOption({ label: "E2E Synthetic Counterparty" });
    await create.getByLabel("Direction").selectOption("owed_to_principal");
    await create
      .getByLabel("Origin note")
      .fill("Synthetic Commitment evidence in the disposable browser database.");
    await create.getByRole("button", { name: "Create commitment" }).click();

    const link = page.getByRole("link", { name: new RegExp(title) });
    await expect(link).toBeVisible();

    // The card is the element carrying the Commitment's identity attribute —
    // the same hook Work's own focus restoration uses — so this measures the
    // card itself rather than whatever wrapper happens to be nearest.
    const card = page.locator("[data-work-item]").filter({ hasText: title }).first();
    const measured = await chrome(card);
    expect(
      Math.min(...measured.borders),
      `the Commitment card must keep a border (measured ${measured.borders.join("/")})`,
    ).toBeGreaterThan(0);
    expect(measured.radius, "the Commitment card must keep its rounding").toBeGreaterThan(0);

    // Dispose through the product's own explicit closure, which is the only way
    // a Commitment is closed. Left open, it would sit in every later Commitment
    // read this run makes.
    await link.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Closure note").fill("Synthetic explicit Commitment closure evidence.");
    await dialog.getByRole("button", { name: "Close commitment" }).click();
    await expect(dialog.getByText("Commitment explicitly closed.")).toBeVisible();
  });

  /**
   * A selected row is differentiated, and says so in the way the package pins.
   *
   * `data-state="selected"` is the hook — never `aria-selected`, which would be
   * a lie about the role: these rows are not options in a listbox and a
   * `aria-selected` on a plain container is a role/state mismatch a screen
   * reader either ignores or mis-announces. The checkbox already carries the
   * selection semantics.
   *
   * "Visible low-emphasis differentiation" is measured as a real change in the
   * row's own painted background between the two states — low-emphasis is a
   * design judgement no automated check can make, but *present* and *painted*
   * are exactly what this can prove, and a differentiation that does not exist
   * is the failure that matters.
   */
  test("a selected row is visibly differentiated, carries data-state and never aria-selected", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { titles } = await seedList(page, 2);
    const title = titles[0]!;
    const row = listRow(page, title);

    await expect(row).not.toHaveAttribute("data-state", "selected");
    const unselected = await chrome(row);

    await page.getByRole("checkbox", { name: `Select ${title}` }).check();
    await expect(row).toHaveAttribute("data-state", "selected");
    await expect(page.getByRole("checkbox", { name: `Select ${title}` })).toBeChecked();

    /*
      Polled, not read once. The Work list revalidates against the server after
      a selection, so a single `getComputedStyle` can land on the frame between
      React re-creating the row and the style being recalculated — which reads
      as an unpainted row on a correctly painted surface. This waits for the
      painted state rather than retrying the whole test, and it still fails if
      selection genuinely paints nothing.
    */
    await expect
      .poll(
        async () => (await chrome(row)).background,
        { message: `selection must paint the row differently (was ${unselected.background})` },
      )
      .not.toBe(unselected.background);
    const selected = await chrome(row);
    // Differentiation by fill, not by a card growing back around the row.
    expect(selected.borders.every((width) => width <= 0.01), "selection must not add a border").toBe(
      true,
    );

    // The semantics the package forbids, on the row and on everything in it.
    await expect(row.locator("[aria-selected]")).toHaveCount(0);
    expect(
      await row.evaluate((node) => node.hasAttribute("aria-selected")),
      "the row must not carry aria-selected",
    ).toBe(false);

    // The unselected sibling is untouched: selection is per row, not per list.
    const other = listRow(page, titles[1]!);
    await expect(other).not.toHaveAttribute("data-state", "selected");
  });

  /**
   * WP03-AC-030..037. Every ordinary operation still works end to end.
   *
   * Normalization moved Priority into the state band, hid the Status label,
   * stripped the Due trigger to its value, re-weighted Close and re-worded the
   * expanded More. Each of those is a place where an operation can be lost while
   * the row still looks operable, so every one of them is driven here against
   * the real stack — not asserted as present.
   */
  test("WP03-AC-030..036 Status, Due, Comment, Close and More all still operate from the row", async ({
    page,
  }) => {
    test.setTimeout(300_000);
    const { titles } = await seedList(page, 2);
    const title = titles[0]!;

    // Status, inline, without opening Task detail.
    await listRow(page, title)
      .getByTestId("task-status-control")
      .getByRole("combobox")
      .selectOption({ label: "In progress" });
    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);

    // Due, inline, through the value-only trigger.
    await listRow(page, title).getByRole("button", { name: /^Due, / }).click();
    await page.getByRole("button", { name: "Today", exact: true }).click();
    await expect(feedback(page).getByText(/^Due date moved to /)).toBeVisible();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);

    // Comment opens the Task's own Activity surface rather than a second
    // comments implementation, and closing returns focus to the control used.
    const comment = listRow(page, title).getByTestId("task-list-row-comment");
    await comment.click();
    await expect(page.getByTestId("task-compact-sheet")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
    await expect(listRow(page, title).getByTestId("task-list-row-comment")).toBeFocused();

    // More reveals Cancel and reads `Less` while expanded — visible wording
    // only: the accessible name must not have moved with it.
    const more = listRow(page, title).getByTestId("task-list-row-more");
    await expect(more).toHaveAccessibleName(`More actions for ${title}`);
    await expect(more).toHaveText("More");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(more).toHaveText("Less");
    await expect(more, "the accessible name must not change with the wording").toHaveAccessibleName(
      `More actions for ${title}`,
    );
    await expect(
      listRow(page, title).getByRole("button", { name: "Cancel Task", exact: true }),
    ).toBeVisible();
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await expect(more).toHaveText("More");

    // Close, dismissed. The confirmation opens on the non-destructive choice,
    // asks for no authored text, and leaves the Task exactly as it was.
    const close = listRow(page, title).getByTestId("task-close-trigger");
    await close.click();
    const confirmation = listRow(page, title).getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("textbox")).toHaveCount(0);
    await confirmation.getByRole("button", { name: "Keep open" }).click();
    await expect(listRow(page, title).getByRole("alertdialog")).toHaveCount(0);
    await expect(listRow(page, title)).toHaveCount(1);

    // Close, confirmed. The outcome outlives the row that issued it.
    await listRow(page, title).getByTestId("task-close-trigger").click();
    await listRow(page, title)
      .getByRole("alertdialog")
      .getByRole("button", { name: "Confirm Closed" })
      .click();
    await expect(feedback(page).getByText(new RegExp(`${title}.*closed`))).toBeVisible();
  });

  /**
   * WP03-AC-037. An operation that removes its own row does not drop the user.
   *
   * Closing a Task takes it out of `all-open`, which unmounts the very control
   * the user activated; a browser answers that by dropping focus to the body,
   * and a list that leaves it there has stranded a keyboard user in the
   * document with nothing under them. Two rows are seeded so there is a
   * survivor to land on, and the whole interaction is driven from the keyboard
   * so the record of where focus was cannot depend on a pointer focusing a
   * button — which macOS WebKit deliberately does not do.
   *
   * The assertion is on all three of the things that can go wrong: focus on
   * `body`, focus on a node that has left the document, and focus somewhere
   * outside Work altogether.
   */
  test("WP03-AC-037 closing a row moves focus to a surviving Work target, never the body", async ({
    page,
  }) => {
    test.setTimeout(300_000);
    const { titles } = await seedList(page, 2);
    const doomed = titles[0]!;
    const survivor = titles[1]!;

    const close = listRow(page, doomed).getByTestId("task-close-trigger");
    await close.focus();
    await expect(close).toBeFocused();
    await page.keyboard.press("Enter");

    const confirmation = listRow(page, doomed).getByRole("alertdialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation.getByRole("button", { name: "Keep open" })).toBeFocused();
    await confirmation.getByRole("button", { name: "Confirm Closed" }).click();

    await expect(feedback(page).getByText(new RegExp(`${doomed}.*closed`))).toBeVisible();
    await expect(listRow(page, doomed)).toHaveCount(0);
    await expect(listRow(page, survivor)).toHaveCount(1);
    await expect(listRow(page, survivor).getByTestId("task-list-row-title")).toBeFocused();

    const landed = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return null;
      return {
        tag: active.tagName.toLowerCase(),
        connected: active.isConnected,
        isBody: active === document.body,
        inWork: Boolean(active.closest("section[aria-labelledby='work-heading']")),
        row: active.closest("[data-work-item]")?.getAttribute("data-work-item") ?? null,
        text: (active.textContent ?? "").trim().slice(0, 80),
      };
    });
    expect(landed, "something must hold focus after the row left").not.toBeNull();
    expect(landed!.isBody, `focus fell to the body: ${JSON.stringify(landed)}`).toBe(false);
    expect(landed!.connected, `focus landed on a detached node: ${JSON.stringify(landed)}`).toBe(
      true,
    );
    expect(landed!.inWork, `focus left Work entirely: ${JSON.stringify(landed)}`).toBe(true);
    // With a survivor on screen the placement is a row, not the fallback
    // heading: landing on the heading is correct only when nothing is left.
    expect(landed!.row, `focus should be inside a surviving row: ${JSON.stringify(landed)}`).not.toBeNull();
  });

  /**
   * WP03-AC-034. A version conflict is recoverable from the row itself.
   *
   * A real conflict, produced the only honest way: the row makes one write, so
   * its binder is holding the canonical version the server answered with; the
   * Task is then advanced out of band through the same BFF, which is exactly
   * what "changed elsewhere" means; and the row's next write arrives stale. No
   * route is stubbed and no response is rewritten — the 409 comes from the real
   * gateway against the real database.
   *
   * Both exits are driven, because a conflict panel that can only be dismissed
   * is a dead end and one that can only be reapplied is a trap.
   */
  test("WP03-AC-034 a real version conflict surfaces on the row and both exits work", async ({
    page,
  }) => {
    test.setTimeout(300_000);
    const tag = marker();
    const title = `E2E conflict row ${tag}`;
    const taskId = await seedTaskRow(page, { title, idempotencyKey: `e2e-${tag}` });
    await page.goto(`/work?view=all-open&q=${encodeURIComponent(tag)}`);
    await expect(listRow(page, title)).toHaveCount(1);

    // One confirmed write, so the row is holding a canonical version.
    await listRow(page, title)
      .getByTestId("task-status-control")
      .getByRole("combobox")
      .selectOption({ label: "In progress" });
    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();

    // The Task changes elsewhere. Read the version the row cannot see, and
    // advance it through the canonical endpoint.
    const read = await api<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
    expect(read.status).toBe(200);
    const bumped = await api<unknown>(page, `/api/tasks/${taskId}`, {
      method: "PATCH",
      body: {
        expectedVersion: read.body.task.version,
        priority: "p1",
        idempotencyKey: `e2e-${tag}-elsewhere`,
      },
    });
    expect(bumped.status, `the out-of-band write must land: ${JSON.stringify(bumped.body)}`).toBe(
      200,
    );

    // The row's next write is stale, and the row says so rather than locking
    // silently.
    await listRow(page, title)
      .getByTestId("task-status-control")
      .getByRole("combobox")
      .selectOption({ label: "Waiting" });
    const conflict = listRow(page, title).getByTestId("task-list-row-conflict");
    await expect(conflict).toBeVisible();
    await expect(conflict.getByTestId("task-list-row-conflict-reapply")).toBeVisible();
    await expect(conflict.getByTestId("task-list-row-conflict-dismiss")).toBeVisible();

    // Exit one: leave it. The panel goes and the row is usable again.
    await conflict.getByTestId("task-list-row-conflict-dismiss").click();
    await expect(listRow(page, title).getByTestId("task-list-row-conflict")).toHaveCount(0);
    await expect(
      listRow(page, title).getByTestId("task-status-control").getByRole("combobox"),
    ).toBeEnabled();

    // Exit two: provoke it again and reapply the intent against the version the
    // conflict exposed. The write lands for real.
    const reread = await api<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
    await api<unknown>(page, `/api/tasks/${taskId}`, {
      method: "PATCH",
      body: {
        expectedVersion: reread.body.task.version,
        priority: "p2",
        idempotencyKey: `e2e-${tag}-elsewhere-2`,
      },
    });
    await listRow(page, title)
      .getByTestId("task-status-control")
      .getByRole("combobox")
      .selectOption({ label: "Blocked" });
    const again = listRow(page, title).getByTestId("task-list-row-conflict");
    await expect(again).toBeVisible();
    await again.getByTestId("task-list-row-conflict-reapply").click();
    await expect(listRow(page, title).getByTestId("task-list-row-conflict")).toHaveCount(0);
    await expect(feedback(page).getByText("Status changed to Blocked")).toBeVisible();

    const settled = await api<{ task: { lifecycle_state: string } }>(page, `/api/tasks/${taskId}`);
    expect(settled.body.task.lifecycle_state, "the reapplied intent must have landed").toBe(
      "blocked",
    );
  });

  /**
   * A terminal row offers nothing it cannot do.
   *
   * Close and Cancel are withheld once a Task is closed or cancelled — the rule
   * lives with the affordance, so it applies on every surface — and Status stops
   * being an editable choice, because closure and cancellation are distinct
   * terminal actions and never ordinary Status values. The Completed view is the
   * one place a whole list of terminal rows exists, which is where offering a
   * live Close on every one of them was the defect.
   */
  test("terminal rows expose no invalid action", async ({ page }) => {
    test.setTimeout(180_000);
    const tag = marker();
    const title = `E2E terminal row ${tag}`;
    const taskId = await seedTaskRow(page, { title, idempotencyKey: `e2e-${tag}` });

    const read = await api<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
    const closed = await api<unknown>(page, `/api/tasks/${taskId}/transition`, {
      method: "POST",
      body: {
        toState: "completed",
        expectedVersion: read.body.task.version,
        idempotencyKey: `e2e-${tag}-close`,
      },
    });
    expect(closed.status, `the Task must actually close: ${JSON.stringify(closed.body)}`).toBe(200);

    await page.goto(`/work?view=completed&q=${encodeURIComponent(tag)}`);
    const row = listRow(page, title);
    await expect(row).toHaveCount(1);

    // Status is stated, not offered.
    await expect(row.getByTestId("task-status-control")).toHaveAttribute("data-terminal", "true");
    await expect(row.getByTestId("task-status-control").getByRole("combobox")).toHaveCount(0);
    await expect(row.getByText("Closed")).toBeVisible();

    // The terminal actions, and the disclosure that exists only to reveal one of
    // them, are withheld rather than disabled.
    await expect(row.getByTestId("task-close-trigger")).toHaveCount(0);
    await expect(row.getByTestId("task-list-row-more")).toHaveCount(0);
    await expect(row.getByRole("button", { name: "Cancel Task", exact: true })).toHaveCount(0);

    // What a terminal Task still supports is still there.
    await expect(row.getByTestId("task-list-row-comment")).toBeVisible();
    await expect(row.getByTestId("task-list-row-title")).toBeVisible();
  });
});
