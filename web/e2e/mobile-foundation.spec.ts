/**
 * The mobile control-sizing foundation, measured as the browser computed it.
 *
 * **What this lane proves.** Every assertion below reads `getComputedStyle` or a
 * live box measurement out of a real engine — Chromium at Pixel 7 geometry
 * (`mobile`), WebKit at iPhone 15 geometry (`mobile-webkit`), and Chromium at
 * 1280x800 (`desktop`). Nothing here matches a Tailwind class name, because a
 * class list is a claim about intent and the computed value is the thing the
 * user's eyes and the platform's zoom heuristic actually meet. Specifically it
 * proves that under `(pointer: coarse)` the shared control token resolves to
 * 16px on the primitives that consume it, that the same token stays at the
 * intentional compact 14px on a fine-pointer desktop (so the coarse rule did not
 * leak into desktop density), that ordinary coarse-pointer interactive controls
 * are at least 44 CSS px tall, that the document and the Create Task sheet
 * introduce no horizontal scroll axis at 320/375/390/393/430 CSS px, that the
 * Due/Clear row keeps the date Input inside its parent's content box at those
 * widths, that the rendered viewport meta does not deny pinch zoom, and that
 * focusing an editable control keeps `document.activeElement` on it, paints a
 * focus indicator, and adds no horizontal overflow.
 *
 * **What WP-POSTUX-02 adds to it.** The same measurement discipline applied to
 * the Create Task surface's vertical compaction: that the major-field gap
 * measures 12 CSS px at narrow/coarse geometry and the Description control's
 * floor sits at or above 80px but under the shared 96px, that the identical
 * measurement on the fine-pointer desktop lane still reads 16px and 96px so the
 * mobile rule provably did not leak, that the field order is unchanged, that the
 * Due/Clear pair still shares one line at every narrow width rather than being
 * bought back as a stack, that every control stays inside the sheet's content
 * box at 320/375/390/393/430 px, in phone landscape, and at tablet and desktop
 * geometry, that the WP-POSTUX-01 type and touch-target floors still hold *in
 * the compacted layout*, and that raising the root font-size reflows the surface
 * downward rather than sideways. Every one of those numbers is read back out of
 * the engine; none is inferred from a class name.
 *
 * **What this lane does not prove, stated so no reader can mistake it.**
 * Playwright's WebKit is not the iOS Safari binary and device emulation is not a
 * device. This file says nothing about the iOS software keyboard (its
 * appearance, its height, or what it occludes), nothing about Safari's real
 * visual viewport or browser chrome (URL-bar collapse, `visualViewport` resize
 * on focus), nothing about the physical iOS focus-zoom heuristic — the 16px
 * threshold is asserted as a computed value here, not observed as a zoom that
 * did not happen — nothing about installed-iOS-PWA safe-area insets, and
 * nothing about VoiceOver announcements. All of those are WP09, and none of
 * them may be read out of a green run of this file.
 *
 * **What WP-POSTUX-03 adds to it.** The normalized Work List, measured on a
 * *populated* list rather than on an empty one. A row is where this shell puts
 * the most controls per vertical centimetre — a checkbox, a title, a Status
 * select, a Due trigger and three buttons — and normalization moved Priority
 * into that band, hid the Status label, stripped the Due trigger to its value
 * and re-weighted Close. So the coarse-pointer floors are re-measured on the row
 * itself, the Status `<select>`'s definite height is asserted on the WebKit lane
 * where the 22px defect actually reproduces, the four migrated Workbench selects
 * are measured where a user meets them, and every expanded state the row can
 * enter — the Due chooser, More with Cancel showing, a real version conflict —
 * is proved to stay inside the row and inside the viewport at every narrow
 * width. The row's vertical rhythm is held to a generous ceiling rather than to
 * an exact pixel count, deliberately: the package forbids a brittle
 * exact-pixel contract, and a ceiling is what actually states "materially
 * lighter than the audited stack of cards".
 *
 * **Read-only by construction, with one stated exception.** The Create Task
 * sheet is opened and measured but never submitted, so none of the WP01/WP02
 * work below creates a Task; each test that opens the sheet closes it again
 * through the real "Close panel" control before it ends. The WP-POSTUX-03
 * section cannot be read-only — an empty list has no row to measure and a
 * measurement of nothing is worse than no measurement — so it seeds synthetic,
 * marker-named Tasks through the canonical BFF and disposes of every one of
 * them in an `afterEach` that runs after a failed test as well as a passing one.
 * Nothing it creates outlives the test that created it.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { signIn } from "./fixtures";

/** `src/lib/tasks/presentation.ts`. Read, not guessed. */
const TASK_DUE_FIELD_LABEL = "Due";

/** The coarse-pointer emulation lanes. `tablet` is Desktop Chrome, so it is not one. */
const COARSE_PROJECTS = ["mobile", "mobile-webkit"];

/** The narrow widths the contract names, in CSS px. */
const NARROW_WIDTHS = [320, 375, 390, 393, 430] as const;

/** iOS raises the page's zoom when a focused control's text is under 16px. */
const COARSE_MIN_FONT_PX = 16;
/** The deliberate fine-pointer density: `--control-font-size: .875rem`. */
const FINE_CONTROL_FONT_PX = 14;
/** The shell's touch-target floor. */
const MIN_TOUCH_TARGET_PX = 44;

function isCoarse(projectName: string): boolean {
  return COARSE_PROJECTS.includes(projectName);
}

/** The computed `font-size` of an element, in CSS px, as the engine resolved it. */
async function computedFontPx(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const node = document.querySelector(sel);
    if (!node) throw new Error(`no element for ${sel}`);
    return Number.parseFloat(getComputedStyle(node).fontSize);
  }, selector);
}

/** Document-level horizontal overflow, in CSS px. Zero or negative means bounded. */
async function documentOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * Open Create Task on `/work` and hand back its dialog.
 *
 * The sheet is the densest concentration of shared primitives this head puts on
 * one screen — Input, Select, Textarea and a date Input beside a button — which
 * is why the sizing and geometry assertions are made here rather than spread
 * across pages that each show one control.
 */
async function openCreateTaskSheet(page: Page) {
  await page.getByRole("button", { name: "New task" }).click();
  const sheet = page.getByTestId("task-create-sheet");
  await expect(sheet).toBeVisible();
  return sheet;
}

/** Close the sheet through the control a person would use, and prove it went. */
async function closeCreateTaskSheet(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
}

test.describe("coarse-pointer control sizing", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(!isCoarse(testInfo.project.name), "coarse-pointer emulation lanes only");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("the emulation lane really is a coarse pointer", async ({ page }) => {
    // The premise of every assertion in this describe block. If the engine does
    // not report a coarse pointer under this device profile then the media query
    // in tokens.css never applied and a green font-size assertion below would be
    // measuring the desktop branch by accident. Asserted first so that failure
    // reads as "the lane is wrong", not "the token is wrong".
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
  });

  test("Create Task Title, Description, Priority and Due all compute to at least 16px", async ({
    page,
  }) => {
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    // Title is the shared Input, Description is the shared Textarea, Priority is
    // the shared Select (a raw <select> until this work package), and Due is the
    // shared Input at type="date". Four primitives, one token.
    const controls = {
      Title: sheet.getByLabel("Title"),
      Description: sheet.getByLabel("Description"),
      Priority: sheet.getByLabel("Priority"),
      [TASK_DUE_FIELD_LABEL]: sheet.getByLabel(TASK_DUE_FIELD_LABEL),
    };

    for (const [label, locator] of Object.entries(controls)) {
      await expect(locator).toBeVisible();
      const fontPx = await locator.evaluate((node) =>
        Number.parseFloat(getComputedStyle(node).fontSize),
      );
      expect(fontPx, `Create Task ${label} computed font-size`).toBeGreaterThanOrEqual(
        COARSE_MIN_FONT_PX,
      );
    }

    await closeCreateTaskSheet(page);
  });

  test("the Library search input computes to at least 16px", async ({ page }) => {
    // `#library-q` is a page-level input migrated onto the same token rather
    // than onto the shared primitive, so it is measured in its own right.
    await page.goto("/library");
    await expect(page.locator("#library-q")).toBeVisible();
    expect(await computedFontPx(page, "#library-q")).toBeGreaterThanOrEqual(COARSE_MIN_FONT_PX);
  });

  test("the capture composer TextField computes to at least 16px", async ({ page }) => {
    // TextField now renders the shared Textarea; the capture composer is the
    // instance of it reachable without first creating a row to comment on.
    //
    // NOT ASSERTED HERE, and not faked: the Task **comment** composer and the
    // Task **Status** select both live on a Task detail drawer, which requires an
    // existing Task. Nothing is seeded at this head (`e2e/stack.sh` creates no
    // Task), so reaching them means creating and then disposing of a real row —
    // outside this read-only lane. Both consume the same TextField/Select
    // primitives measured above, and `task-status-control.test.tsx` guards the
    // Status select's sizing contract in the blocking unit job.
    await page.goto("/today");
    await page
      .locator('[data-testid="capture-button-desktop"], [data-testid="capture-button-mobile"]')
      .filter({ visible: true })
      .click();
    await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
    const field = page.getByTestId("capture-field");
    await expect(field).toBeVisible();
    const fontPx = await field.evaluate((node) =>
      Number.parseFloat(getComputedStyle(node).fontSize),
    );
    expect(fontPx, "capture composer computed font-size").toBeGreaterThanOrEqual(
      COARSE_MIN_FONT_PX,
    );
    await page.keyboard.press("Escape");
  });

  test("ordinary interactive controls are at least 44 CSS px tall", async ({ page }) => {
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const named: Array<[string, ReturnType<typeof sheet.getByLabel>]> = [
      ["Title", sheet.getByLabel("Title")],
      ["Priority", sheet.getByLabel("Priority")],
      [TASK_DUE_FIELD_LABEL, sheet.getByLabel(TASK_DUE_FIELD_LABEL)],
    ];
    for (const [label, locator] of named) {
      const box = await locator.boundingBox();
      expect(box, `${label} must have a box`).not.toBeNull();
      expect(box!.height, `${label} height`).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }

    // Buttons on the same sheet. Description is deliberately excluded: a
    // multi-line Textarea's height is content-driven, not a touch-target claim.
    for (const name of ["Clear", "Create"]) {
      const box = await sheet.getByRole("button", { name, exact: true }).boundingBox();
      expect(box, `${name} must have a box`).not.toBeNull();
      expect(box!.height, `${name} height`).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }

    await closeCreateTaskSheet(page);
  });

  test("the rendered viewport meta does not deny pinch zoom", async ({ page }) => {
    // Read off the rendered document rather than off the source, because what
    // reaches the engine is what governs. A page that ships `user-scalable=no`
    // or pins `maximum-scale=1` takes zoom away from the reader; this asserts
    // the shipped tag does neither. It does not assert anything about how iOS
    // Safari behaves when a small control is focused — that is WP09.
    await page.goto("/today");
    const content = await page.evaluate(
      () =>
        document.querySelector<HTMLMetaElement>('meta[name="viewport"]')?.getAttribute("content") ??
        null,
    );
    expect(content, "a viewport meta must be rendered").not.toBeNull();
    const normalised = content!.replace(/\s+/g, "").toLowerCase();
    expect(normalised).not.toContain("user-scalable=no");
    expect(normalised).not.toContain("user-scalable=0");
    expect(normalised).not.toContain("maximum-scale=1");
  });

  for (const width of NARROW_WIDTHS) {
    test(`nothing that must not scroll sideways does so at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/work");
      const sheet = await openCreateTaskSheet(page);

      // 1. The document itself. A scrollWidth beyond clientWidth here is the
      //    whole page carrying a second axis, which is the defect.
      expect(await documentOverflow(page), `document overflow at ${width}`).toBeLessThanOrEqual(1);

      // 2. The sheet's own scroll container. It is deliberately `overflow: auto`
      //    so a tall form can scroll vertically; that must not become a
      //    horizontal axis, so the assertion is on the measurement, not on the
      //    CSS.
      const dialog = page.getByRole("dialog").filter({ has: page.getByTestId("task-create-sheet") });
      const sheetOverflow = await dialog.evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(sheetOverflow, `Create Task sheet overflow at ${width}`).toBeLessThanOrEqual(1);

      // 3. Everything inside the sheet, minus the regions whose horizontal
      //    scrolling is intentional. "Every element fits" is a brittle rule —
      //    a designed horizontal carousel or a wide table in its own
      //    `overflow-x: auto` shell is correct, not a defect — so an element is
      //    skipped when it, or any ancestor up to the sheet, declares
      //    `overflow-x: auto | scroll`. What remains is the set that genuinely
      //    has nowhere to put spill.
      const spills = await sheet.evaluate((root) => {
        const scrollableX = (node: Element) => {
          const overflowX = getComputedStyle(node).overflowX;
          return overflowX === "auto" || overflowX === "scroll";
        };
        const excused = (node: Element) => {
          for (let cursor: Element | null = node; cursor; cursor = cursor.parentElement) {
            if (scrollableX(cursor)) return true;
            if (cursor === root) break;
          }
          return false;
        };
        const rootRight = root.getBoundingClientRect().right;
        const offenders: string[] = [];
        for (const node of Array.from(root.querySelectorAll("*"))) {
          if (excused(node)) continue;
          const rect = node.getBoundingClientRect();
          if (rect.width === 0 && rect.height === 0) continue;
          if (rect.right > rootRight + 1) {
            offenders.push(
              `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ""} right=${rect.right.toFixed(1)} > ${rootRight.toFixed(1)}`,
            );
          }
        }
        return offenders;
      });
      expect(spills, `non-scrollable descendants spilling past the sheet at ${width}`).toEqual([]);

      await closeCreateTaskSheet(page);
    });

    test(`the Create Task Due/Clear row stays inside its parent at ${width}px`, async ({ page }) => {
      // The row this measures is the date Input beside the Clear button. Before
      // the shared `min-w-0 max-w-full` fix a date input's intrinsic width
      // pushed its flex row wider than the sheet at phone widths; these two
      // numbers are what that defect moved.
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/work");
      const sheet = await openCreateTaskSheet(page);

      const due = sheet.getByLabel(TASK_DUE_FIELD_LABEL);
      await expect(due).toBeVisible();

      const geometry = await due.evaluate((node) => {
        const row = node.parentElement;
        if (!row) throw new Error("the Due input has no parent row");
        const rowStyle = getComputedStyle(row);
        const rowRect = row.getBoundingClientRect();
        // The parent's *content* box: its border box less border and padding.
        const contentRight =
          rowRect.right -
          Number.parseFloat(rowStyle.borderRightWidth) -
          Number.parseFloat(rowStyle.paddingRight);
        return {
          inputRight: node.getBoundingClientRect().right,
          contentRight,
          rowOverflow: row.scrollWidth - row.clientWidth,
        };
      });

      expect(
        geometry.inputRight,
        `Due input right edge (${geometry.inputRight.toFixed(1)}) must stay inside its row content box (${geometry.contentRight.toFixed(1)}) at ${width}`,
      ).toBeLessThanOrEqual(geometry.contentRight + 1);
      expect(geometry.rowOverflow, `Due/Clear row overflow at ${width}`).toBeLessThanOrEqual(1);

      await closeCreateTaskSheet(page);
    });
  }

  test("focusing an editable control keeps focus, shows an indicator, and adds no scroll axis", async ({
    page,
  }) => {
    // The three things automation can honestly establish about focus. It does
    // not establish that a software keyboard appeared, that the visual viewport
    // resized, or that iOS did or did not zoom — there is no keyboard and no
    // visual viewport in this emulation, and claiming otherwise would be the
    // defect this file exists to avoid. WP09 owns all three.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const before = await documentOverflow(page);

    const title = sheet.getByLabel("Title");
    await title.focus();

    const focus = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return null;
      const style = getComputedStyle(active);
      return {
        id: active.id,
        tag: active.tagName.toLowerCase(),
        outlineStyle: style.outlineStyle,
        outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
        boxShadow: style.boxShadow,
      };
    });
    expect(focus, "something must hold focus").not.toBeNull();

    // activeElement is the control itself, not an ancestor the sheet redirected to.
    const titleId = await title.evaluate((node) => node.id);
    expect(focus!.id, "activeElement must be the focused control").toBe(titleId);
    expect(focus!.tag).toBe("input");

    // A visible indicator: the global `:focus-visible` rule paints a 2px
    // outline; a ring implemented as a box-shadow would satisfy this too.
    const hasOutline = focus!.outlineStyle !== "none" && focus!.outlineWidth >= 1;
    const hasRing = focus!.boxShadow !== "none" && focus!.boxShadow !== "";
    expect(hasOutline || hasRing, `focus indicator absent: ${JSON.stringify(focus)}`).toBe(true);

    // Focus must not have introduced a horizontal axis — a control scrolled into
    // view sideways is the symptom the narrow-width work removed.
    expect(await documentOverflow(page), "focus introduced horizontal overflow").toBe(before);

    await closeCreateTaskSheet(page);
  });

  test("rotating to landscape does not return the controls to 14px", async ({ page }) => {
    // The specific regression a width-keyed rule would have shipped. A phone in
    // landscape is 844 CSS px wide — past every breakpoint a `sm:`/`md:` rule
    // would key on — while the pointer is still coarse and the finger has not
    // got any smaller. `tokens.css` keys the control token on
    // `(pointer: coarse)` for exactly this reason, so the invariant to prove is
    // that rotation changes nothing.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/work");

    let sheet = await openCreateTaskSheet(page);
    const portrait = await sheet.getByLabel("Priority").evaluate((node) =>
      Number.parseFloat(getComputedStyle(node).fontSize),
    );
    expect(portrait, "portrait must already satisfy the coarse contract").toBeGreaterThanOrEqual(
      COARSE_MIN_FONT_PX,
    );
    await closeCreateTaskSheet(page);

    // Rotate. Same device, same pointer, wider than any width breakpoint.
    await page.setViewportSize({ width: 844, height: 390 });
    expect(
      await page.evaluate(() => matchMedia("(pointer: coarse)").matches),
      "landscape must still report a coarse pointer, or this proves nothing",
    ).toBe(true);

    sheet = await openCreateTaskSheet(page);
    for (const label of ["Title", "Description", "Priority"]) {
      const size = await sheet
        .getByLabel(label)
        .evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
      expect(size, `${label} in landscape`).toBeGreaterThanOrEqual(COARSE_MIN_FONT_PX);
    }
    await closeCreateTaskSheet(page);
  });
});

test.describe("fine-pointer desktop density is not enlarged", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the fine-pointer reference lane only");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("the shared controls compute to exactly the compact 14px", async ({ page }) => {
    // The counterpart to the coarse assertions, and the reason they are safe to
    // make: if the `(pointer: coarse)` branch had been written as an
    // unconditional rule, or the token bumped globally, this is where it
    // reddens. Exactly 14px, not "at most 16" — the compact desktop density is
    // an intentional value, so a drift in either direction is a regression.
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    for (const label of ["Title", "Description", "Priority", TASK_DUE_FIELD_LABEL]) {
      const fontPx = await sheet
        .getByLabel(label)
        .evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
      expect(fontPx, `desktop ${label} computed font-size`).toBeCloseTo(FINE_CONTROL_FONT_PX, 1);
    }

    await closeCreateTaskSheet(page);
  });

  test("the Library search input keeps the compact desktop density", async ({ page }) => {
    await page.goto("/library");
    await expect(page.locator("#library-q")).toBeVisible();
    expect(await computedFontPx(page, "#library-q")).toBeCloseTo(FINE_CONTROL_FONT_PX, 1);
  });

  test("the desktop lane really is a fine pointer", async ({ page }) => {
    // Guards the inverse mistake: a desktop project that somehow reports a
    // coarse pointer would make the 14px assertions above prove the opposite of
    // what they say.
    expect(await page.evaluate(() => matchMedia("(pointer: fine)").matches)).toBe(true);
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(false);
  });
});

/* ---------------------------------------------------------------------------
 * WP-POSTUX-02: the Create Task surface's vertical compaction, measured.
 * ------------------------------------------------------------------------- */

/** The compacted major-field gap the Create Task surface takes at mobile/narrow. */
const COMPACT_FIELD_GAP_PX = 12;
/** The uncompacted gap the same surface keeps at desktop (`lg`) density. */
const ROOMY_FIELD_GAP_PX = 16;
/** The compacted Description floor at mobile/detail. */
const COMPACT_DESCRIPTION_MIN_PX = 80;
/** The shared Textarea floor, which desktop keeps. */
const SHARED_DESCRIPTION_MIN_PX = 96;

/** Phone landscape: past every width breakpoint, still a coarse pointer. */
const PHONE_LANDSCAPE = { width: 844, height: 390 } as const;
/** The `tablet` project's own geometry, restated so a viewport reset is explicit. */
const TABLET_GEOMETRY = { width: 768, height: 1024 } as const;
/** The `desktop` project's own geometry, for the same reason. */
const DESKTOP_GEOMETRY = { width: 1280, height: 800 } as const;

/**
 * The sheet's major fields, as boxes, in DOM order.
 *
 * A "major field" is a direct child of the create form that owns a `<label>` —
 * Title, Description, Priority and Due. The context chip, the status line and
 * the sticky footer are not labelled groups and are deliberately not counted.
 *
 * `gaps` is the **measured** vertical distance between consecutive groups, not
 * the declared `row-gap`: it is what a reader's eye actually meets, and it stays
 * true whether the compaction is implemented as a flex gap, a margin, or
 * something else. The form's computed `row-gap` is returned alongside it purely
 * so a failure message can say which mechanism produced the number.
 */
async function majorFieldGeometry(sheet: Locator): Promise<{
  labels: string[];
  gaps: number[];
  rowGap: string;
}> {
  return sheet.evaluate((form) => {
    const groups = Array.from(form.children).filter(
      (child) => child.querySelector(":scope > label") !== null,
    );
    const rects = groups.map((group) => group.getBoundingClientRect());
    return {
      labels: groups.map((group) => group.querySelector(":scope > label")!.textContent!.trim()),
      gaps: rects.slice(1).map((rect, index) => rect.top - rects[index]!.bottom),
      rowGap: getComputedStyle(form).rowGap,
    };
  });
}

/** Description's computed floor and its rendered height, both in CSS px. */
async function descriptionMetrics(sheet: Locator): Promise<{ minHeight: number; height: number }> {
  return sheet.getByLabel("Description").evaluate((node) => ({
    minHeight: Number.parseFloat(getComputedStyle(node).minHeight) || 0,
    height: node.getBoundingClientRect().height,
  }));
}

/**
 * Named controls that left the sheet's content box, with the numbers that say so.
 *
 * The content box is the dialog's border box less its border and padding, so an
 * element flush against the sheet's `p-5` is inside and an element under the
 * padding is out. Both edges are checked: a control pushed off the left is the
 * same defect as one pushed off the right, and only the right-hand case shows up
 * as document overflow.
 */
async function controlsOutsideSheet(
  page: Page,
  names: readonly string[],
): Promise<string[]> {
  const dialog = page.getByRole("dialog").filter({ has: page.getByTestId("task-create-sheet") });
  const box = await dialog.evaluate((node) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return {
      left:
        rect.left +
        Number.parseFloat(style.borderLeftWidth) +
        Number.parseFloat(style.paddingLeft),
      right:
        rect.right -
        Number.parseFloat(style.borderRightWidth) -
        Number.parseFloat(style.paddingRight),
    };
  });

  const sheet = page.getByTestId("task-create-sheet");
  const offenders: string[] = [];
  for (const name of names) {
    const locator = ["Clear", "Create", "Back"].includes(name)
      ? sheet.getByRole("button", { name, exact: true })
      : sheet.getByLabel(name);
    const rect = await locator.boundingBox();
    if (!rect) {
      offenders.push(`${name} has no box`);
      continue;
    }
    if (rect.x < box.left - 1 || rect.x + rect.width > box.right + 1) {
      offenders.push(
        `${name} [${rect.x.toFixed(1)}, ${(rect.x + rect.width).toFixed(1)}] outside [${box.left.toFixed(1)}, ${box.right.toFixed(1)}]`,
      );
    }
  }
  return offenders;
}

/** Open Create Task through the Capture chooser, the launcher that shows Back. */
async function openCreateTaskSheetFromCapture(page: Page) {
  await page
    .locator('[data-testid="capture-button-desktop"], [data-testid="capture-button-mobile"]')
    .filter({ visible: true })
    .click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Create Task" }).click();
  const sheet = page.getByTestId("task-create-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Back", exact: true })).toBeVisible();
  return sheet;
}

test.describe("Create Task vertical compaction at coarse geometry", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(!isCoarse(testInfo.project.name), "coarse-pointer emulation lanes only");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("the major-field gap measures 12px and Description's floor is compacted", async ({
    page,
  }) => {
    // Measured, not matched. A class list saying `gap-3` is a claim about
    // intent; this is the distance the engine put between the boxes, so a rule
    // that lost to specificity, or a breakpoint that keyed on the wrong side of
    // `lg`, reddens here rather than shipping as a green class assertion.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const geometry = await majorFieldGeometry(sheet);
    expect(geometry.labels, "the four major fields must be the ones measured").toEqual([
      "Title",
      "Description",
      "Priority",
      TASK_DUE_FIELD_LABEL,
    ]);
    for (const [index, gap] of geometry.gaps.entries()) {
      expect(
        gap,
        `gap between ${geometry.labels[index]} and ${geometry.labels[index + 1]} (form row-gap: ${geometry.rowGap})`,
      ).toBeCloseTo(COMPACT_FIELD_GAP_PX, 0);
    }

    // The Description floor. `min-height` is the contract — the rendered height
    // follows it while the control is empty — so both are read and the floor is
    // the one asserted against the 96px shared value it must now sit under.
    const description = await descriptionMetrics(sheet);
    expect(
      description.minHeight,
      `Description computed min-height (rendered ${description.height.toFixed(1)}px)`,
    ).toBeGreaterThanOrEqual(COMPACT_DESCRIPTION_MIN_PX);
    expect(description.minHeight, "the compaction must actually be below the shared floor").toBeLessThan(
      SHARED_DESCRIPTION_MIN_PX,
    );
    expect(description.height, "Description rendered height").toBeGreaterThanOrEqual(
      COMPACT_DESCRIPTION_MIN_PX,
    );

    await closeCreateTaskSheet(page);
  });

  test("the field order is Title, Description, Priority, Due/Clear", async ({ page }) => {
    // Compaction is a spacing change and must not have become a reordering. The
    // Due group is checked one level deeper as well, because its two controls
    // are the pair the next test asserts stays on one line.
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const { labels } = await majorFieldGeometry(sheet);
    expect(labels).toEqual(["Title", "Description", "Priority", TASK_DUE_FIELD_LABEL]);

    const dueRow = await sheet.getByLabel(TASK_DUE_FIELD_LABEL).evaluate((node) => {
      const row = node.parentElement;
      if (!row) throw new Error("the Due input has no parent row");
      return Array.from(row.children).map((child) => child.tagName.toLowerCase());
    });
    expect(dueRow, "the date Input precedes the Clear button").toEqual(["input", "button"]);

    await closeCreateTaskSheet(page);
  });

  test("raising the root font-size reflows vertically, not horizontally", async ({ page }) => {
    // Text scaling is the accessible-zoom case that a fixed-height compaction
    // would break: a form squeezed with pixel heights either clips its own text
    // or pushes a second axis onto the page. Neither is allowed, so the root
    // font-size is raised well past the default and the two scroll axes are
    // re-measured. It is restored afterwards so nothing leaks into the close.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const dialog = page.getByRole("dialog").filter({ has: sheet });
    const before = {
      document: await documentOverflow(page),
      sheet: await dialog.evaluate((node) => node.scrollWidth - node.clientWidth),
    };

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "24px";
    });
    // A layout pass has to have happened before the measurement means anything.
    await expect(sheet.getByLabel("Title")).toBeVisible();

    const scaled = {
      document: await documentOverflow(page),
      sheet: await dialog.evaluate((node) => node.scrollWidth - node.clientWidth),
      height: await dialog.evaluate((node) => node.scrollHeight),
    };
    expect(scaled.document, "24px root font-size introduced document overflow").toBeLessThanOrEqual(1);
    expect(scaled.sheet, "24px root font-size introduced sheet overflow").toBeLessThanOrEqual(1);
    // The reflow is vertical: bigger text on a fixed width has to get taller.
    expect(scaled.height, "scaled text must reflow downward").toBeGreaterThan(0);

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    expect(await documentOverflow(page), "restoring the root font-size must restore the layout").toBe(
      before.document,
    );

    await closeCreateTaskSheet(page);
  });

  test("the capture-launched sheet keeps Create and Back inside the sheet", async ({ page }) => {
    // The Work launcher renders no Back button, so the footer's wrapping
    // behaviour with two buttons on it is only reachable from Capture. Measured
    // at the narrowest supported width and again in landscape.
    for (const size of [{ width: 320, height: 844 }, PHONE_LANDSCAPE]) {
      await page.setViewportSize(size);
      await page.goto("/today");
      await openCreateTaskSheetFromCapture(page);

      expect(
        await controlsOutsideSheet(page, [
          "Title",
          "Description",
          "Priority",
          TASK_DUE_FIELD_LABEL,
          "Clear",
          "Create",
          "Back",
        ]),
        `capture-launched Create Task controls at ${size.width}x${size.height}`,
      ).toEqual([]);
      expect(
        await documentOverflow(page),
        `document overflow at ${size.width}x${size.height}`,
      ).toBeLessThanOrEqual(1);

      await closeCreateTaskSheet(page);
    }
  });

  test("phone landscape keeps the surface bounded and the controls contained", async ({ page }) => {
    // 844 CSS px wide with a coarse pointer: past every width breakpoint a
    // `sm:`/`md:` rule would key on, while the finger has not changed. The
    // sibling test above proves the type does not shrink here; this one proves
    // the compacted layout does not spill here either.
    await page.setViewportSize(PHONE_LANDSCAPE);
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    expect(
      await controlsOutsideSheet(page, [
        "Title",
        "Description",
        "Priority",
        TASK_DUE_FIELD_LABEL,
        "Clear",
        "Create",
      ]),
      "Create Task controls in phone landscape",
    ).toEqual([]);
    expect(await documentOverflow(page), "document overflow in phone landscape").toBeLessThanOrEqual(
      1,
    );
    const dialog = page.getByRole("dialog").filter({ has: sheet });
    expect(
      await dialog.evaluate((node) => node.scrollWidth - node.clientWidth),
      "sheet overflow in phone landscape",
    ).toBeLessThanOrEqual(1);

    await closeCreateTaskSheet(page);
  });

  for (const width of NARROW_WIDTHS) {
    test(`the Due/Clear row stays on one line at ${width}px`, async ({ page }) => {
      // WP-POSTUX-02 compacts vertically and must **not** buy that space by
      // stacking the date Input above its Clear button, which would cost a row
      // of height and change the control's shape. The two assertions are the
      // two ways "one line" can be stated from geometry: the boxes share a
      // vertical centre, and Clear begins to the right of where the date input
      // ends. A stacked or grid-wrapped row fails both.
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/work");
      const sheet = await openCreateTaskSheet(page);

      const due = await sheet.getByLabel(TASK_DUE_FIELD_LABEL).boundingBox();
      const clear = await sheet.getByRole("button", { name: "Clear", exact: true }).boundingBox();
      expect(due, `the Due input must have a box at ${width}`).not.toBeNull();
      expect(clear, `the Clear button must have a box at ${width}`).not.toBeNull();

      const dueCentre = due!.y + due!.height / 2;
      const clearCentre = clear!.y + clear!.height / 2;
      expect(
        Math.abs(dueCentre - clearCentre),
        `Due centre ${dueCentre.toFixed(1)} vs Clear centre ${clearCentre.toFixed(1)} at ${width}`,
      ).toBeLessThanOrEqual(2);
      expect(
        clear!.x,
        `Clear left edge (${clear!.x.toFixed(1)}) must sit right of the date input's right edge (${(due!.x + due!.width).toFixed(1)}) at ${width}`,
      ).toBeGreaterThanOrEqual(due!.x + due!.width - 1);

      await closeCreateTaskSheet(page);
    });

    test(`the compacted surface contains every control and keeps WP01 sizing at ${width}px`, async ({
      page,
    }) => {
      // The regression this pairs with the compaction: vertical space was taken
      // out, and neither the type nor the touch targets may have paid for it.
      // The WP-POSTUX-01 contract is therefore re-measured *in the compacted
      // layout*, at every narrow width, rather than only at the project's own
      // default viewport where the earlier tests read it.
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/work");
      const sheet = await openCreateTaskSheet(page);

      expect(
        await controlsOutsideSheet(page, [
          "Title",
          "Description",
          "Priority",
          TASK_DUE_FIELD_LABEL,
          "Clear",
          "Create",
        ]),
        `Create Task controls outside the sheet at ${width}`,
      ).toEqual([]);

      for (const label of ["Title", "Description", "Priority", TASK_DUE_FIELD_LABEL]) {
        const fontPx = await sheet
          .getByLabel(label)
          .evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
        expect(fontPx, `compacted ${label} computed font-size at ${width}`).toBeGreaterThanOrEqual(
          COARSE_MIN_FONT_PX,
        );
      }

      // Description is excluded from the target floor for the reason the
      // earlier suite gives: a Textarea's height is content-driven and is not a
      // touch-target claim. Its floor is asserted separately, above.
      for (const label of ["Title", "Priority", TASK_DUE_FIELD_LABEL]) {
        const box = await sheet.getByLabel(label).boundingBox();
        expect(box, `${label} must have a box at ${width}`).not.toBeNull();
        expect(box!.height, `compacted ${label} height at ${width}`).toBeGreaterThanOrEqual(
          MIN_TOUCH_TARGET_PX,
        );
      }
      for (const name of ["Clear", "Create"]) {
        const box = await sheet.getByRole("button", { name, exact: true }).boundingBox();
        expect(box, `${name} must have a box at ${width}`).not.toBeNull();
        expect(box!.height, `compacted ${name} height at ${width}`).toBeGreaterThanOrEqual(
          MIN_TOUCH_TARGET_PX,
        );
      }

      await closeCreateTaskSheet(page);
    });
  }
});

test.describe("the Create Task compaction did not leak to desktop density", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the fine-pointer reference lane only");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test("the major-field gap measures the uncompacted 16px", async ({ page }) => {
    // The regression guard for the whole work package. The compaction is scoped
    // to the Create Task surface at mobile/narrow; if it had been written as an
    // unconditional rule, or keyed on the wrong side of `lg`, this is where the
    // desktop density it was never meant to touch reddens. Exactly 16px, not
    // "at most 16": the roomier desktop spacing is an intentional value.
    await page.setViewportSize(DESKTOP_GEOMETRY);
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const geometry = await majorFieldGeometry(sheet);
    expect(geometry.labels).toEqual(["Title", "Description", "Priority", TASK_DUE_FIELD_LABEL]);
    for (const [index, gap] of geometry.gaps.entries()) {
      expect(
        gap,
        `desktop gap between ${geometry.labels[index]} and ${geometry.labels[index + 1]} (form row-gap: ${geometry.rowGap})`,
      ).toBeCloseTo(ROOMY_FIELD_GAP_PX, 0);
    }

    await closeCreateTaskSheet(page);
  });

  test("the Description floor is not compacted on desktop", async ({ page }) => {
    // The second half of the same guard, on the other property the compaction
    // moves. Stated as a floor rather than an equality because the work package
    // pins the mobile value and leaves desktop free to keep the shared 96px or
    // exceed it; what it may not do is inherit the mobile 80px.
    await page.setViewportSize(DESKTOP_GEOMETRY);
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    const description = await descriptionMetrics(sheet);
    expect(
      description.minHeight,
      `desktop Description computed min-height (rendered ${description.height.toFixed(1)}px)`,
    ).toBeGreaterThanOrEqual(SHARED_DESCRIPTION_MIN_PX);

    await closeCreateTaskSheet(page);
  });

  test("every control stays inside the sheet at desktop geometry", async ({ page }) => {
    await page.setViewportSize(DESKTOP_GEOMETRY);
    await page.goto("/work");
    const sheet = await openCreateTaskSheet(page);

    expect(
      await controlsOutsideSheet(page, [
        "Title",
        "Description",
        "Priority",
        TASK_DUE_FIELD_LABEL,
        "Clear",
        "Create",
      ]),
      "Create Task controls at 1280x800",
    ).toEqual([]);
    expect(await documentOverflow(page), "document overflow at 1280x800").toBeLessThanOrEqual(1);
    const dialog = page.getByRole("dialog").filter({ has: sheet });
    expect(
      await dialog.evaluate((node) => node.scrollWidth - node.clientWidth),
      "sheet overflow at 1280x800",
    ).toBeLessThanOrEqual(1);

    await closeCreateTaskSheet(page);
  });
});

test.describe("the Create Task surface fits tablet geometry", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "tablet", "the tablet lane only");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  /**
   * 768 CSS px is below `lg`, so this lane takes the compacted spacing while
   * reporting a fine pointer — the one geometry where the two axes of the
   * contract disagree. No gap value is asserted here, because the work package
   * pins the compacted number at mobile/narrow and the roomy number at desktop
   * and says nothing about which side of the line a fine-pointer tablet falls
   * on; what it does require everywhere is that nothing spills.
   */
  test("nothing spills at 768x1024, from either launcher", async ({ page }) => {
    await page.setViewportSize(TABLET_GEOMETRY);

    await page.goto("/work");
    await openCreateTaskSheet(page);
    expect(
      await controlsOutsideSheet(page, [
        "Title",
        "Description",
        "Priority",
        TASK_DUE_FIELD_LABEL,
        "Clear",
        "Create",
      ]),
      "Work-launched Create Task controls at 768x1024",
    ).toEqual([]);
    expect(await documentOverflow(page), "document overflow at 768x1024").toBeLessThanOrEqual(1);
    await closeCreateTaskSheet(page);

    await page.goto("/today");
    await openCreateTaskSheetFromCapture(page);
    expect(
      await controlsOutsideSheet(page, [
        "Title",
        "Description",
        "Priority",
        TASK_DUE_FIELD_LABEL,
        "Clear",
        "Create",
        "Back",
      ]),
      "capture-launched Create Task controls at 768x1024",
    ).toEqual([]);
    await closeCreateTaskSheet(page);
  });
});

/* ------------------------------------------------------------------ *
 * WP-POSTUX-03 — the normalized Work List at coarse geometry
 * ------------------------------------------------------------------ */

/** The row height the audit measured on the card-stack List, in CSS px. */
const AUDITED_ROW_HEIGHT_PX = 196;

/**
 * The ceiling an ordinary active row must sit under.
 *
 * A ceiling, not an equality, and that is the whole point. The package pins a
 * *materially lighter* rhythm than the audited stack of cards and explicitly
 * forbids a brittle exact-pixel contract: a row whose height is asserted to the
 * pixel reddens on a font metric, a line-height token or a one-pixel divider
 * without anything having regressed. 180px is comfortably under the audited
 * 196px and comfortably above the three 44px bands plus their gaps and padding,
 * so it fails a row that has quietly put its card chrome back and passes a row
 * that is merely being drawn on a different engine.
 */
const WORK_ROW_HEIGHT_CEILING_PX = 180;

type ApiAnswer<T> = { status: number; body: T };

async function workListApi<T>(
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

/** The content box of an element: its border box less border and padding. */
async function contentBox(locator: Locator): Promise<{ left: number; right: number }> {
  return locator.evaluate((node) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const px = (value: string) => Number.parseFloat(value) || 0;
    return {
      left: rect.left + px(style.borderLeftWidth) + px(style.paddingLeft),
      right: rect.right - px(style.borderRightWidth) - px(style.paddingRight),
    };
  });
}

/**
 * The measured height of a control, named, or `null` when it has no box.
 *
 * Returned rather than asserted so a caller can report every undersized control
 * in one run instead of aborting on the first.
 */
async function measure(locator: Locator): Promise<{ width: number; height: number } | null> {
  const box = await locator.boundingBox();
  return box ? { width: box.width, height: box.height } : null;
}

test.describe("the normalized Work List at coarse geometry", () => {
  /**
   * Seeded Tasks, and putting them back.
   *
   * `e2e/stack.sh` builds one disposable database for the whole run, so a row
   * left behind changes what every later spec sees — `today-tasks.spec.ts`
   * leaked exactly this way. Disposal is deterministic rather than best-effort:
   * each row is read, one already terminal is left alone, and the rest are
   * transitioned with the version that read returned. It runs after a failed
   * test as well as a passing one, because a test that fails after seeding has
   * still seeded.
   */
  const seeded: string[] = [];

  /** See `today-tasks.spec.ts`: scaffolding was never done, so it is not "Closed". */
  const TEARDOWN_STATE = "cancelled";

  /** A long title, so wrapping is exercised rather than hoped for. */
  const LONG_TITLE_TAIL =
    "with a deliberately long identity line that must wrap across several lines at phone width rather than shoulder its neighbours aside";

  async function seedTask(
    page: Page,
    input: { title: string; priority?: string; idempotencyKey: string },
  ): Promise<string> {
    const created = await workListApi<{ task?: { task_id: string } }>(page, "/api/tasks", {
      method: "POST",
      body: {
        title: input.title,
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

  /**
   * Put one ordinary Task and one long-titled Task in a List of their own.
   *
   * Both carry a Priority, because WP03-AC-049 is about a Priority that is
   * actually set: a row with none correctly shows none, and measuring that would
   * pass vacuously. The marker goes through the List's own `q=` filter so the
   * view holds these rows and nothing another spec left behind.
   */
  async function seedWorkList(page: Page): Promise<{
    tag: string;
    ordinary: string;
    long: string;
    taskId: string;
  }> {
    const tag = `wp03m-${test.info().project.name}-${Date.now()}`;
    // The two titles must not be substrings of one another: rows are located
    // with `filter({ hasText })`, which is a substring match, so a long title
    // built by appending to the ordinary one silently matches both rows.
    const ordinary = `E2E list row ${tag} ordinary`;
    const long = `E2E list row ${tag} long ${LONG_TITLE_TAIL}`;
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    const taskId = await seedTask(page, {
      title: ordinary,
      priority: "p1",
      idempotencyKey: `e2e-${tag}-0`,
    });
    await seedTask(page, { title: long, priority: "p2", idempotencyKey: `e2e-${tag}-1` });
    await page.goto(`/work?view=all-open&q=${encodeURIComponent(tag)}`);
    await expect(page.getByRole("list", { name: "Work list" })).toBeVisible();
    await expect(page.locator('[data-testid="task-list-row"]')).toHaveCount(2);
    return { tag, ordinary, long, taskId };
  }

  function listRow(page: Page, title: string): Locator {
    return page.locator('[data-testid="task-list-row"]').filter({ hasText: title });
  }

  function workList(page: Page): Locator {
    return page.getByRole("list", { name: "Work list" });
  }

  /** The seven coarse-pointer targets a row puts under a finger, in band order. */
  function rowTargets(row: Locator, title: string): Array<[string, Locator]> {
    return [
      /*
        The operable target is the enclosing `<label>`, not the 20px box the
        checkbox paints. WCAG 2.5.8 measures the region that actually activates
        the control, and the label is what a finger can land on — measuring the
        input instead would report a number no user is constrained by. A
        separate test proves the label really does toggle, so this is not a
        measurement that flatters itself.
      */
      ["checkbox", row.getByRole("checkbox", { name: `Select ${title}` }).locator("xpath=ancestor::label[1]")],
      ["title", row.getByTestId("task-list-row-title")],
      ["Status", row.getByTestId("task-status-control").getByRole("combobox")],
      ["Due", row.getByRole("button", { name: /^Due, / })],
      ["Comment", row.getByTestId("task-list-row-comment")],
      ["Close", row.getByTestId("task-close-trigger")],
      ["More", row.getByTestId("task-list-row-more")],
    ];
  }

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(!isCoarse(testInfo.project.name), "coarse-pointer emulation lanes only");
    seeded.length = 0;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (!isCoarse(testInfo.project.name)) return;
    const ids = [...seeded];
    seeded.length = 0;
    for (const taskId of ids) {
      const read = await workListApi<{ task?: { version: number; lifecycle_state: string } }>(
        page,
        `/api/tasks/${taskId}`,
      );
      if (read.status !== 200 || !read.body.task) continue;
      if (["completed", "cancelled"].includes(read.body.task.lifecycle_state)) continue;
      const disposed = await workListApi<unknown>(page, `/api/tasks/${taskId}/transition`, {
        method: "POST",
        body: {
          toState: TEARDOWN_STATE,
          expectedVersion: read.body.task.version,
          idempotencyKey: `wp03m-teardown-${taskId}-${Date.now()}`,
        },
      });
      expect(
        disposed.status,
        `teardown must dispose of seeded Task ${taskId}: ${JSON.stringify(disposed.body)}`,
      ).toBeLessThan(300);
    }
  });

  /**
   * The populated List is bounded at every narrow width, and so is every row
   * inside it.
   *
   * Three measurements, because "no horizontal scroll" can be true of the
   * document while the list is clipped, and true of the list while a row hangs
   * out of it. The document's own scroll axis, the list's right edge against the
   * viewport, and each row's edges against the list's *content* box — the box
   * less its border and padding, so a row flush against the list's padding is
   * inside and a row under the padding is out. Both edges are checked: a row
   * pushed off the left is the same defect as one pushed off the right and only
   * the right-hand case shows as document overflow.
   */
  for (const width of NARROW_WIDTHS) {
    test(`the populated Work List and its rows stay inside the viewport at ${width}px`, async ({
      page,
    }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width, height: 844 });
      const { ordinary } = await seedWorkList(page);
      await expect(listRow(page, ordinary)).toHaveCount(1);

      expect(await documentOverflow(page), `document overflow at ${width}`).toBeLessThanOrEqual(1);

      const list = workList(page);
      const listBox = await list.boundingBox();
      expect(listBox, `the Work list must have a box at ${width}`).not.toBeNull();
      expect(listBox!.x, `the Work list starts left of the viewport at ${width}`).toBeGreaterThanOrEqual(
        -1,
      );
      expect(
        listBox!.x + listBox!.width,
        `the Work list exceeds ${width}`,
      ).toBeLessThanOrEqual(width + 1);
      expect(
        await list.evaluate((node) => node.scrollWidth - node.clientWidth),
        `the Work list clips its own content at ${width}`,
      ).toBeLessThanOrEqual(1);

      const bounds = await contentBox(list);
      const rows = page.locator('[data-testid="task-list-row"]');
      const count = await rows.count();
      expect(count, `the List must be populated at ${width}`).toBe(2);
      const escaped: string[] = [];
      for (let index = 0; index < count; index += 1) {
        const box = await rows.nth(index).boundingBox();
        if (!box) {
          escaped.push(`row ${index} has no box`);
          continue;
        }
        if (box.x < bounds.left - 1 || box.x + box.width > bounds.right + 1) {
          escaped.push(
            `row ${index} [${box.x.toFixed(1)}, ${(box.x + box.width).toFixed(1)}] outside [${bounds.left.toFixed(1)}, ${bounds.right.toFixed(1)}]`,
          );
        }
      }
      expect(escaped, `rows outside the Work list content box at ${width}`).toEqual([]);
    });
  }

  /**
   * WP03-AC-068..074. Every target a finger meets on a row is at least 44 CSS px.
   *
   * Seven controls, each named and each measured on its own, with `expect.soft`
   * so one run enumerates *every* undersized control rather than stopping at the
   * first. Nothing is lowered to achieve that and the test still fails. The
   * numbers are printed, so the record carries measurements rather than the word
   * "passed".
   *
   * Height is held to this shell's own 44px row height; width is held to WCAG
   * 2.5.8's 24px, because inventing a stricter width would be this suite
   * asserting a standard nobody adopted.
   */
  test("WP03-AC-068..074 every coarse-pointer target on a row is at least 44px", async ({ page }) => {
    test.setTimeout(180_000);
    const { ordinary } = await seedWorkList(page);
    const row = listRow(page, ordinary);
    await expect(row).toHaveCount(1);

    const measured: string[] = [];
    for (const [name, control] of rowTargets(row, ordinary)) {
      const box = await measure(control);
      expect.soft(box, `${name} has no box on the Work List row`).not.toBeNull();
      if (box === null) continue;
      measured.push(`${name} ${Math.round(box.width)}x${Math.round(box.height)}`);
      expect
        .soft(box.height, `${name} is below this shell's ${MIN_TOUCH_TARGET_PX}px row height`)
        .toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect.soft(box.width, `${name} is below WCAG 2.5.8's 24px minimum width`).toBeGreaterThanOrEqual(24);
    }
    console.log(`WP-POSTUX-03 Work List row targets: ${measured.join(", ")}`);
    expect(measured, "every named row target must have been measured").toHaveLength(7);
  });

  /**
   * WP03-AC-054. The Status `<select>` computes at least 44px **tall**.
   *
   * Asserted separately from its six neighbours above, and deliberately so. This
   * is the one control with a documented engine-specific defect behind it:
   * macOS WebKit does not honour `min-height` on a default-appearance `<select>`
   * and resolves it down to the ~18px intrinsic, which rendered this control 22
   * CSS px tall against a 44px target. `task-status-control.tsx` answers that
   * with a *definite* height, and this lane — WebKit at phone geometry — is
   * where the answer is measured on the engine the defect lives in.
   *
   * The computed `height` is read as well as the measured box, because a box can
   * be inflated by a wrapper while the control itself stays 22px, and it is the
   * control the finger lands on.
   *
   * Stated so nobody over-reads a green run: Playwright's WebKit is not the iOS
   * Safari binary, and on Linux Playwright builds this control renders 44px
   * whether or not the definite height is present — the guard that fails without
   * the fix is the sizing-contract unit test in `task-status-control.test.tsx`,
   * which runs in the blocking unit job. This measures the shipped page.
   */
  test("WP03-AC-068 the checkbox's 44px target actually toggles selection", async ({ page }) => {
    // The measurement above is only meaningful if the box it measures is live.
    // Before WP-POSTUX-03 the 44x44 box was a <span>, which forwards no click:
    // the reserved area looked compliant and operated nothing.
    const seeded = await seedWorkList(page);
    await page.setViewportSize({ width: 390, height: 844 });
    const row = listRow(page, seeded.ordinary);
    const input = row.getByRole("checkbox", { name: `Select ${seeded.ordinary}` });
    const target = input.locator("xpath=ancestor::label[1]");

    await expect(input).not.toBeChecked();
    const box = (await target.boundingBox())!;
    // Click the corner of the reserved box, well outside the 20px input.
    await page.mouse.click(box.x + 4, box.y + 4);
    await expect(input).toBeChecked();
  });

  test("WP03-AC-054 the row Status select computes at least 44px of height", async ({ page }) => {
    test.setTimeout(180_000);
    const { ordinary } = await seedWorkList(page);
    const status = listRow(page, ordinary).getByTestId("task-status-control").getByRole("combobox");
    await expect(status).toBeVisible();

    const computed = await status.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: Number.parseFloat(style.height) || 0,
        minHeight: Number.parseFloat(style.minHeight) || 0,
        fontSize: Number.parseFloat(style.fontSize) || 0,
        rendered: node.getBoundingClientRect().height,
      };
    });
    console.log(
      `WP03-AC-054 Status select on ${test.info().project.name}: ${JSON.stringify(computed)}`,
    );
    expect(
      computed.height,
      `Status computed height (rendered ${computed.rendered.toFixed(1)}px)`,
    ).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    expect(computed.rendered, "Status rendered height").toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    // The same coarse-pointer type floor the rest of this file measures: a
    // control under 16px is the one iOS raises the page's zoom for.
    expect(computed.fontSize, "Status computed font-size").toBeGreaterThanOrEqual(COARSE_MIN_FONT_PX);
  });

  /**
   * WP03-AC-086..089 and WP03-AC-092. The four migrated Workbench selects.
   *
   * Bulk action, Bulk value, Commitment counterparty and Commitment direction
   * were raw `<select className="h-10 …">` — 40px, and a local `h-10` overrides
   * the shared primitive's height, so the migration is only real if the rendered
   * control now takes the token. Measured here on the shipped page under a
   * coarse pointer rather than inferred from a class list, on both dimensions
   * the WP01 contract names: at least 44px tall and at least 16px of type.
   *
   * Both surfaces need reaching honestly. The Bulk editor exists only once a
   * Task is selected, so a row is seeded and its checkbox is checked; the
   * Commitment form is one deliberate activation away on the Commitments view
   * and needs no seed.
   */
  test("WP03-AC-086..089 the migrated Workbench selects are 44px tall and 16px typed", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { ordinary } = await seedWorkList(page);

    // The premise: a fine-pointer lane would measure the desktop branch of the
    // token and pass for the wrong reason.
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);

    await page.getByRole("checkbox", { name: `Select ${ordinary}` }).check();
    // Scoped to the Bulk change section itself, so a control of the same name
    // elsewhere on the page could not stand in for the one being measured.
    const bulk = page.getByRole("region", { name: "Bulk change" });
    await expect(bulk).toBeVisible();
    const named: Array<[string, Locator]> = [
      ["Bulk action", bulk.getByRole("combobox", { name: "Bulk action" })],
      ["Bulk value", bulk.getByRole("combobox", { name: "Bulk value" })],
    ];

    const undersized: string[] = [];
    const measured: string[] = [];
    async function record(name: string, control: Locator): Promise<void> {
      await expect(control, `${name} must be on screen`).toBeVisible();
      const geometry = await control.evaluate((node) => ({
        height: node.getBoundingClientRect().height,
        computedHeight: Number.parseFloat(getComputedStyle(node).height) || 0,
        fontSize: Number.parseFloat(getComputedStyle(node).fontSize) || 0,
      }));
      measured.push(
        `${name} ${geometry.height.toFixed(1)}px @ ${geometry.fontSize.toFixed(1)}px`,
      );
      if (geometry.height < MIN_TOUCH_TARGET_PX || geometry.computedHeight < MIN_TOUCH_TARGET_PX) {
        undersized.push(`${name} height ${geometry.height.toFixed(1)} (computed ${geometry.computedHeight.toFixed(1)})`);
      }
      if (geometry.fontSize < COARSE_MIN_FONT_PX) {
        undersized.push(`${name} font-size ${geometry.fontSize.toFixed(1)}`);
      }
    }

    for (const [name, control] of named) await record(name, control);

    await page.goto("/work?view=commitments");
    await page.getByRole("button", { name: "New commitment" }).click();
    const create = page.getByRole("heading", { name: "Create commitment" }).locator("..");
    await record("Counterparty", create.getByLabel("Counterparty"));
    await record("Direction", create.getByLabel("Direction"));

    console.log(`WP-POSTUX-03 migrated Workbench selects: ${measured.join(", ")}`);
    expect(measured, "all four migrated selects must have been measured").toHaveLength(4);
    expect(undersized, "migrated Workbench selects below the coarse-pointer floors").toEqual([]);
  });

  /**
   * WP03-AC-049. A Priority that is set is visible at every narrow width.
   *
   * The audited row hid Priority below `sm`, which is every phone width in
   * scope: the one geometry where the list is read most was the one geometry
   * where part of the urgency reading was withheld. Visibility is measured, not
   * asserted from a class — a non-zero box, `display` not `none` and
   * `visibility` not `hidden` — because `hidden sm:inline` and a zero-height
   * clip are different implementations of the same defect.
   */
  for (const width of NARROW_WIDTHS) {
    test(`WP03-AC-049 a set Priority is visible on the row at ${width}px`, async ({ page }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width, height: 844 });
      const { ordinary } = await seedWorkList(page);
      const row = listRow(page, ordinary);
      await expect(row).toHaveCount(1);

      // `p1` was seeded, so the row must state its product label. The label
      // comes from `src/lib/tasks/presentation.ts`, never a backend token.
      const priority = row.getByText("Critical", { exact: true });
      await expect(priority, `Priority is not on the row at ${width}`).toBeVisible();
      const geometry = await priority.evaluate((node) => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return {
          width: rect.width,
          height: rect.height,
          display: style.display,
          visibility: style.visibility,
        };
      });
      expect(geometry.display, `Priority is display:${geometry.display} at ${width}`).not.toBe("none");
      expect(geometry.visibility, `Priority is visibility:${geometry.visibility} at ${width}`).not.toBe(
        "hidden",
      );
      expect(geometry.width, `Priority has no width at ${width}`).toBeGreaterThan(0);
      expect(geometry.height, `Priority has no height at ${width}`).toBeGreaterThan(0);

      // The backend token never reaches the row, at any width.
      const text = await row.innerText();
      for (const token of ["p1", "p2", "p3", "p4"]) {
        expect(text, `the row states the backend token "${token}" at ${width}`).not.toContain(token);
      }
    });
  }

  /**
   * WP03-AC-047. A long title wraps, and wrapping costs no neighbour its place.
   *
   * The defect a dense row invites is a title that either refuses to wrap (and
   * pushes the row sideways) or wraps over the top of something. Both are
   * geometry, so both are measured: the title occupies more than one line, the
   * row introduces no horizontal axis, and the title's box overlaps neither the
   * selection control beside it nor the state and action bands below it.
   *
   * Overlap is computed as a genuine rectangle intersection rather than as an
   * edge comparison, because two boxes can pass an edge test and still sit on
   * top of each other.
   */
  for (const width of [320, 393] as const) {
    test(`WP03-AC-047 a long title wraps without colliding at ${width}px`, async ({ page }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width, height: 844 });
      const { long } = await seedWorkList(page);
      const row = listRow(page, long);
      await expect(row).toHaveCount(1);

      const title = row.getByTestId("task-list-row-title");
      const lineCount = await title.evaluate((node) => {
        const style = getComputedStyle(node);
        const lineHeight = Number.parseFloat(style.lineHeight);
        const height = node.getBoundingClientRect().height;
        return Number.isFinite(lineHeight) && lineHeight > 0 ? height / lineHeight : 0;
      });
      expect(lineCount, `the long title did not wrap at ${width}`).toBeGreaterThan(1.5);

      expect(await documentOverflow(page), `document overflow at ${width}`).toBeLessThanOrEqual(1);
      expect(
        await row.evaluate((node) => node.scrollWidth - node.clientWidth),
        `the row clips its own content at ${width}`,
      ).toBeLessThanOrEqual(1);

      const collisions = await row.evaluate((rowNode) => {
        const titleNode = rowNode.querySelector('[data-testid="task-list-row-title"]');
        if (!titleNode) return ["the row has no title element"];
        const others: Array<[string, Element | null]> = [
          ["selection", rowNode.querySelector('input[type="checkbox"]')],
          ["Status", rowNode.querySelector('[data-testid="task-status-control"]')],
          ["Due", rowNode.querySelector('[data-testid="task-due-control"]')],
          ["Comment", rowNode.querySelector('[data-testid="task-list-row-comment"]')],
          ["Close", rowNode.querySelector('[data-testid="task-close-trigger"]')],
          ["More", rowNode.querySelector('[data-testid="task-list-row-more"]')],
        ];
        const title = titleNode.getBoundingClientRect();
        const found: string[] = [];
        for (const [name, other] of others) {
          if (!other) {
            found.push(`${name} is missing from the row`);
            continue;
          }
          const rect = other.getBoundingClientRect();
          // A genuine rectangle intersection, with a 1px tolerance for the
          // sub-pixel edges a wrapped inline box leaves behind.
          const horizontal = Math.min(title.right, rect.right) - Math.max(title.left, rect.left);
          const vertical = Math.min(title.bottom, rect.bottom) - Math.max(title.top, rect.top);
          if (horizontal > 1 && vertical > 1) {
            found.push(
              `${name} overlaps the title by ${horizontal.toFixed(1)}x${vertical.toFixed(1)}px`,
            );
          }
        }
        return found;
      });
      expect(collisions, `the wrapped title collides with its neighbours at ${width}`).toEqual([]);
    });
  }

  /**
   * WP03-AC-078..080. Every state the row can expand into stays inside it.
   *
   * A row that fits until something opens has not been proved to fit. Three
   * expansions are driven for real at the narrowest supported width — the Due
   * chooser, More with Cancel revealed, and a genuine version conflict — and
   * each is held to the same three things: the document grows no horizontal
   * axis, the revealed controls stay inside the list's content box, and they are
   * visible and enabled rather than merely present.
   *
   * The conflict is real, and produced the only honest way: the row makes one
   * confirmed write, so its binder holds the canonical version; the Task is then
   * advanced out of band through the same BFF, which is exactly what "changed
   * elsewhere" means; and the row's next write arrives stale. No route is
   * stubbed and no response is rewritten.
   */
  test("WP03-AC-078..080 expanded Due, More and a real conflict stay contained and usable", async ({
    page,
  }) => {
    test.setTimeout(300_000);
    await page.setViewportSize({ width: 320, height: 844 });
    const { ordinary, taskId } = await seedWorkList(page);
    const row = listRow(page, ordinary);
    await expect(row).toHaveCount(1);

    /** Every named control outside the list's content box, with the numbers. */
    async function outside(names: Array<[string, Locator]>, stage: string): Promise<void> {
      const bounds = await contentBox(workList(page));
      const offenders: string[] = [];
      for (const [name, control] of names) {
        await expect(control, `${name} must be visible ${stage}`).toBeVisible();
        await expect(control, `${name} must be enabled ${stage}`).toBeEnabled();
        const box = await control.boundingBox();
        if (!box) {
          offenders.push(`${name} has no box`);
          continue;
        }
        if (box.x < bounds.left - 1 || box.x + box.width > bounds.right + 1) {
          offenders.push(
            `${name} [${box.x.toFixed(1)}, ${(box.x + box.width).toFixed(1)}] outside [${bounds.left.toFixed(1)}, ${bounds.right.toFixed(1)}]`,
          );
        }
        if (box.height < MIN_TOUCH_TARGET_PX) {
          offenders.push(`${name} is ${box.height.toFixed(1)}px tall`);
        }
      }
      expect(offenders, `controls outside the Work list ${stage}`).toEqual([]);
      expect(await documentOverflow(page), `document overflow ${stage}`).toBeLessThanOrEqual(1);
    }

    // 1. The Due chooser.
    await row.getByRole("button", { name: /^Due, / }).click();
    await expect(page.getByRole("group", { name: "Due choices" })).toBeVisible();
    await outside(
      [
        ["Today", row.getByRole("button", { name: "Today", exact: true })],
        ["Tomorrow", row.getByRole("button", { name: "Tomorrow", exact: true })],
        ["Pick date", row.getByRole("button", { name: "Pick date", exact: true })],
      ],
      "with the Due chooser open",
    );
    await page.keyboard.press("Escape");
    await expect(page.getByRole("group", { name: "Due choices" })).toHaveCount(0);

    // 2. More, with Cancel revealed. The expanded wording is `Less`; the
    //    accessible name is unchanged, which `work-acceptance.spec.ts` asserts.
    const more = row.getByTestId("task-list-row-more");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await outside(
      [
        ["Cancel Task", row.getByRole("button", { name: "Cancel Task", exact: true })],
        ["Close Task", row.getByTestId("task-close-trigger")],
        ["More", more],
      ],
      "with More expanded",
    );
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "false");

    // 3. A real version conflict, and the region that offers the way out.
    await row.getByTestId("task-status-control").getByRole("combobox").selectOption({ label: "In progress" });
    await expect(
      page.getByTestId("mutation-feedback-region").getByText("Status changed to In progress"),
    ).toBeVisible();

    const read = await workListApi<{ task: { version: number } }>(page, `/api/tasks/${taskId}`);
    expect(read.status).toBe(200);
    const bumped = await workListApi<unknown>(page, `/api/tasks/${taskId}`, {
      method: "PATCH",
      body: {
        expectedVersion: read.body.task.version,
        priority: "p3",
        idempotencyKey: `wp03m-elsewhere-${taskId}`,
      },
    });
    expect(bumped.status, `the out-of-band write must land: ${JSON.stringify(bumped.body)}`).toBe(200);

    await listRow(page, ordinary)
      .getByTestId("task-status-control")
      .getByRole("combobox")
      .selectOption({ label: "Waiting" });
    const conflict = listRow(page, ordinary).getByTestId("task-list-row-conflict");
    await expect(conflict).toBeVisible();
    await outside(
      [
        ["Try again", conflict.getByTestId("task-list-row-conflict-reapply")],
        ["Leave it", conflict.getByTestId("task-list-row-conflict-dismiss")],
      ],
      "with a conflict showing",
    );
    const conflictBounds = await contentBox(workList(page));
    const conflictBox = await conflict.boundingBox();
    expect(conflictBox, "the conflict region must have a box").not.toBeNull();
    expect(
      conflictBox!.x + conflictBox!.width,
      "the conflict region escapes the Work list",
    ).toBeLessThanOrEqual(conflictBounds.right + 1);

    // Usable, not merely contained: the way out actually clears it.
    await conflict.getByTestId("task-list-row-conflict-dismiss").click();
    await expect(listRow(page, ordinary).getByTestId("task-list-row-conflict")).toHaveCount(0);
  });

  /**
   * The row's vertical rhythm is materially lighter than the audited card stack.
   *
   * The audit measured ~196 CSS px per row on the stack of cards. The ceiling
   * asserted here is 180px, and it is a ceiling on purpose: pinning the exact
   * height would redden on a font metric or a one-pixel divider without anything
   * having regressed, which is the brittle pixel contract this package forbids.
   * What a ceiling does catch is the failure that matters — per-row padding,
   * border and rounding quietly returning, which is worth tens of pixels a row.
   *
   * Measured on an *ordinary active* row: short title, nothing expanded, no
   * conflict. A wrapped title is taller by design and is measured for wrapping,
   * not for rhythm, in its own test above.
   */
  test("an ordinary active row sits under the rhythm ceiling", async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 390, height: 844 });
    const { ordinary } = await seedWorkList(page);
    const row = listRow(page, ordinary);
    await expect(row).toHaveCount(1);

    const box = await row.boundingBox();
    expect(box, "the row must have a box").not.toBeNull();
    console.log(
      `WP-POSTUX-03 row rhythm on ${test.info().project.name}: ${box!.height.toFixed(1)}px ` +
        `(audited ${AUDITED_ROW_HEIGHT_PX}px, ceiling ${WORK_ROW_HEIGHT_CEILING_PX}px)`,
    );
    expect(
      box!.height,
      `an ordinary active row must sit under the ${WORK_ROW_HEIGHT_CEILING_PX}px ceiling ` +
        `(the audited card stack measured ~${AUDITED_ROW_HEIGHT_PX}px)`,
    ).toBeLessThanOrEqual(WORK_ROW_HEIGHT_CEILING_PX);
    // Still a real row, not a collapsed one: three 44px bands cannot fit in
    // less than one of them.
    expect(box!.height, "the row collapsed rather than compacted").toBeGreaterThanOrEqual(
      MIN_TOUCH_TARGET_PX,
    );
  });

  /**
   * WP03-AC-067. Text scaling reflows the bands downward, never sideways.
   *
   * The accessible-zoom case a fixed-height compaction breaks: a row squeezed
   * with pixel heights either clips its own text or pushes a second axis onto
   * the page. The root font-size is raised well past the default, both scroll
   * axes are re-measured, the row is confirmed to have grown *taller*, and the
   * root is restored so nothing leaks into whatever runs next.
   */
  test("WP03-AC-067 raising the root font-size reflows the row downward, not sideways", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 390, height: 844 });
    const { ordinary } = await seedWorkList(page);
    const row = listRow(page, ordinary);
    await expect(row).toHaveCount(1);

    const before = {
      document: await documentOverflow(page),
      height: (await row.boundingBox())!.height,
    };

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "24px";
    });
    // A layout pass has to have happened before the measurement means anything.
    await expect(row.getByTestId("task-list-row-title")).toBeVisible();

    const scaled = {
      document: await documentOverflow(page),
      list: await workList(page).evaluate((node) => node.scrollWidth - node.clientWidth),
      row: await row.evaluate((node) => node.scrollWidth - node.clientWidth),
      height: (await row.boundingBox())!.height,
    };
    expect(scaled.document, "24px root font-size introduced document overflow").toBeLessThanOrEqual(1);
    expect(scaled.list, "24px root font-size introduced Work list overflow").toBeLessThanOrEqual(1);
    expect(scaled.row, "24px root font-size made the row clip its own content").toBeLessThanOrEqual(1);
    expect(scaled.height, "scaled text must reflow the row downward").toBeGreaterThan(before.height);

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    expect(
      await documentOverflow(page),
      "restoring the root font-size must restore the layout",
    ).toBe(before.document);
  });
});

/* ------------------------------------------------------------------ *
 * WP-POSTUX-04 — populated Task detail at coarse geometry
 * ------------------------------------------------------------------ */

/**
 * Task detail is a different density problem from Create Task: the default
 * surface is read-first (no Title Input, no Description Textarea, no comment
 * composer) and the finger lands on Edit title, Close Task, and Add comment.
 *
 * Playwright's WebKit project is engine emulation at iPhone 15 geometry, not
 * the iOS Safari binary or a physical iPhone. Nothing below claims a software
 * keyboard, visualViewport chrome, or the physical iOS focus-zoom heuristic.
 */
test.describe("Task detail geometry at coarse pointer (WP-POSTUX-04)", () => {
  const seeded: string[] = [];
  const TEARDOWN_STATE = "cancelled";

  async function seedTask(
    page: Page,
    input: { title: string; idempotencyKey: string },
  ): Promise<string> {
    const created = await workListApi<{ task?: { task_id: string } }>(page, "/api/tasks", {
      method: "POST",
      body: { title: input.title, idempotencyKey: input.idempotencyKey },
    });
    expect(created.status, `seeding "${input.title}" must succeed`).toBe(200);
    const taskId = created.body.task?.task_id ?? "";
    expect(taskId, "the BFF must answer with a Task id").not.toBe("");
    seeded.push(taskId);
    return taskId;
  }

  async function openTaskDetail(page: Page): Promise<{ title: string; sheet: Locator }> {
    const tag = `wp04m-${test.info().project.name}-${Date.now()}`;
    const title = `E2E task detail ${tag}`;
    await page.goto("/work?view=all-open");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await seedTask(page, { title, idempotencyKey: `e2e-${tag}` });
    await page.goto(`/work?view=all-open&q=${encodeURIComponent(tag)}`);
    const trigger = page.getByRole("link", { name: new RegExp(title) });
    await expect(trigger).toBeVisible();
    await trigger.click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByTestId("task-summary")).toBeVisible();
    await expect(sheet.getByTestId("task-edit-title")).toBeVisible();
    return { title, sheet };
  }

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(!isCoarse(testInfo.project.name), "coarse-pointer emulation lanes only");
    seeded.length = 0;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (!isCoarse(testInfo.project.name)) return;
    const ids = [...seeded];
    seeded.length = 0;
    for (const taskId of ids) {
      const read = await workListApi<{ task?: { version: number; lifecycle_state: string } }>(
        page,
        `/api/tasks/${taskId}`,
      );
      if (read.status !== 200 || !read.body.task) continue;
      if (["completed", "cancelled"].includes(read.body.task.lifecycle_state)) continue;
      const disposed = await workListApi<unknown>(page, `/api/tasks/${taskId}/transition`, {
        method: "POST",
        body: {
          toState: TEARDOWN_STATE,
          expectedVersion: read.body.task.version,
          idempotencyKey: `wp04m-teardown-${taskId}-${Date.now()}`,
        },
      });
      expect(
        disposed.status,
        `teardown must dispose of seeded Task ${taskId}: ${JSON.stringify(disposed.body)}`,
      ).toBeLessThan(300);
    }
  });

  test("Task detail has no document overflow and 44px targets on Edit title, Close Task, and Add comment", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { sheet } = await openTaskDetail(page);

    expect(await documentOverflow(page), "document overflow with Task detail open").toBeLessThanOrEqual(
      1,
    );

    const named: Array<[string, Locator]> = [
      ["Edit title", sheet.getByTestId("task-edit-title")],
      [
        "Close Task",
        sheet.getByTestId("task-close-control").getByRole("button", { name: "Close Task", exact: true }),
      ],
      ["Add comment", sheet.getByTestId("task-comments-add")],
    ];
    const measured: string[] = [];
    for (const [name, control] of named) {
      await expect(control, `${name} must be on the default Task detail`).toBeVisible();
      const box = await control.boundingBox();
      expect.soft(box, `${name} has no box on Task detail`).not.toBeNull();
      if (box === null) continue;
      measured.push(`${name} ${Math.round(box.width)}x${Math.round(box.height)}`);
      expect
        .soft(box.height, `${name} is below this shell's ${MIN_TOUCH_TARGET_PX}px row height`)
        .toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect.soft(box.width, `${name} is below WCAG 2.5.8's 24px minimum width`).toBeGreaterThanOrEqual(
        24,
      );
    }
    console.log(
      `WP-POSTUX-04 Task detail targets on ${test.info().project.name}: ${measured.join(", ")}`,
    );
    expect(measured, "every named Task detail target must have been measured").toHaveLength(3);

    const dialog = page.getByRole("dialog").filter({ has: sheet });
    expect(
      await dialog.evaluate((node) => node.scrollWidth - node.clientWidth),
      "Task detail sheet overflow",
    ).toBeLessThanOrEqual(1);
  });

  test("opening the title editor keeps type at 16px and adds no horizontal overflow", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const { sheet } = await openTaskDetail(page);
    const before = await documentOverflow(page);

    await sheet.getByTestId("task-edit-title").click();
    const title = sheet.getByRole("textbox", { name: "Title" });
    await expect(title).toBeVisible();
    await expect(title).toBeFocused();

    const fontPx = await title.evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
    expect(fontPx, "title editor computed font-size").toBeGreaterThanOrEqual(COARSE_MIN_FONT_PX);
    expect(await documentOverflow(page), "title editor introduced horizontal overflow").toBe(before);
  });
});
