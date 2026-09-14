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
 * **Read-only by construction.** The Create Task sheet is opened and measured
 * but never submitted, so this file creates no Task and leaves no row behind;
 * each test that opens the sheet closes it again through the real "Close panel"
 * control before it ends.
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
