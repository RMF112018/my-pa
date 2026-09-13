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
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
    const row = page.locator('[data-testid="task-list-row"]').filter({ hasText: title });
    await expect(row).toBeVisible();
    return { row, title };
  }

  const feedback = (page: Page) => page.getByTestId("mutation-feedback-region");

  test("changes Status from the row without opening Task detail", async ({ page }) => {
    const { row } = await seedRow(page);

    await row.getByRole("combobox").selectOption({ label: "In progress" });

    await expect(feedback(page).getByText("Status changed to In progress")).toBeVisible();
    // Detail was never opened: this is the whole point of the package.
    await expect(page.getByTestId("task-compact-sheet")).toHaveCount(0);
  });

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

  /** The four narrow widths this work package pins for TASK-AC-045. */
  const NARROW_WIDTHS = [320, 375, 390, 430] as const;

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
   * **A defect is recorded here rather than asserted away.** On WebKit the
   * native `<select>` that carries Status renders 22 CSS px tall on the Board
   * card — below the shell's own 44px floor *and* below WCAG 2.5.8's 24px
   * minimum — because the element's `min-height` does not take effect on a
   * default-appearance select in that engine. This test is therefore expected to
   * fail on WebKit and expected to pass everywhere else: it holds the real
   * number, it goes red on Chromium the moment that regresses, and it goes red
   * on WebKit the day the product fixes it. `src/` belongs to another worker in
   * this package; this is the report, not the fix.
   */
  test("TASK-AC-017 the Board Status and Due controls are real touch targets", async ({ page }) => {
    test.fail(
      test.info().project.name === "webkit",
      "Reported, not fixed: WebKit renders the Status select 22px tall, below WCAG 2.5.8's 24px and this shell's 44px.",
    );
    test.setTimeout(180_000);
    const title = await seedTask(page);
    await page.goto("/work?view=all-open&perspective=board");
    const card = boardCard(page, title);
    await expect(card).toHaveCount(1);

    const undersized: string[] = [];
    for (const [name, control] of [
      ["Status", card.getByTestId("task-status-control").getByRole("combobox")],
      ["Due", card.getByRole("button", { name: /^Due, / })],
      ["Comment", card.getByTestId("task-board-card-comment")],
      ["Close Task", card.getByRole("button", { name: "Close Task", exact: true })],
      ["More", card.getByTestId("task-board-card-more")],
    ] as const) {
      const box = await control.boundingBox();
      expect(box, `${name} has no box on the Board card`).not.toBeNull();
      if (box!.height < 44 || box!.width < 24) {
        undersized.push(`${name} ${box!.width}x${box!.height}`);
      }
    }
    expect(undersized, "Board controls below 44px tall or WCAG 2.5.8's 24px wide").toEqual([]);
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
      await expect(card.getByRole("button", { name: /^Due, / })).toBeVisible();
      await expect(card.getByTestId("task-board-card-comment")).toBeVisible();
      await expect(card.getByRole("button", { name: "Close Task", exact: true })).toBeVisible();
      await expect(card.getByTestId("task-board-card-more")).toBeVisible();
      expect(
        await horizontalOverflow(page),
        `Board overflows horizontally at ${width}`,
      ).toBeLessThanOrEqual(1);
      // The card itself fits, so the absence of document overflow is not a
      // clipped card sitting outside it.
      const cardBox = await card.boundingBox();
      expect(cardBox, "Board card has no box").not.toBeNull();
      expect(cardBox!.x + cardBox!.width, `Board card exceeds ${width}`).toBeLessThanOrEqual(width + 1);

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
});
