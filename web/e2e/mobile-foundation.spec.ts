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
import { expect, test, type Page } from "@playwright/test";

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
