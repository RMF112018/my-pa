/**
 * T18 — the Capture Project control, as somebody actually operates it.
 *
 * Labels, keyboard, focus, live feedback and width. The sentinel title below is
 * named by the responsive and mobile-WebKit selection guards, so this file
 * cannot be silently dropped from either lane.
 *
 * **What the automation can and cannot say.** It can assert the accessible name
 * of the control, that the keyboard reaches and operates it, that focus returns
 * where it should across the Task handoff, and that nothing overflows at four
 * phone widths. It cannot assert the pixels of a native select popup: the
 * platform draws that outside the document, and no DOM geometry describes it.
 * That remains open for physical-device and VoiceOver acceptance and is recorded
 * as open rather than asserted away.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { openCaptureNote, signIn, syntheticNote, visibleCaptureButton } from "./fixtures";

type Page = import("@playwright/test").Page;

/** The four widths the brief names. */
const WIDTHS = [320, 375, 390, 430] as const;

async function hasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
}

test.describe("WP08 Capture Project accessibility", () => {
  test("the control has a real label and an explicit No Project choice", async ({ page }) => {
    await signIn(page);
    await openCaptureNote(page);

    const select = page.getByLabel("Project");
    await expect(select).toBeVisible();
    await expect(select).toHaveAttribute("id", /.+/);
    // The explicit choice is offered, and it is the one selected by default.
    await expect(select.locator("option", { hasText: "No Project" })).toHaveCount(1);
    await expect(select).toHaveValue("");
  });

  test("the chooser is operable from the keyboard alone", async ({ page, browserName }) => {
    await signIn(page);
    await visibleCaptureButton(page).focus();
    await page.keyboard.press("Enter");
    const launcher = page.getByRole("dialog", { name: "Search or create" });
    const initial = launcher.getByRole("group", { name: "Search or New", exact: true });
    await expect(initial.getByRole("button")).toHaveText(["Search", "New"]);
    await expect(initial.getByRole("button", { name: "Search", exact: true })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(initial.getByRole("button", { name: "New", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    const choices = launcher.getByRole("group", { name: "Create new", exact: true });
    await expect(choices.getByRole("button")).toHaveText(["Create Task", "Quick Note", "Conversation Log"]);
    await expect(choices.getByRole("button", { name: "Create Task", exact: true })).toBeFocused();
    // macOS WebKit skips buttons with plain Tab by default. Option+Tab reaches
    // every control; the invariant remains keyboard-only navigation.
    const nextControlKey = browserName === "webkit" && process.platform === "darwin" ? "Alt+Tab" : "Tab";
    await page.keyboard.press(nextControlKey);
    await expect(choices.getByRole("button", { name: "Quick Note", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("capture-field")).toBeVisible();
    await expect(page.getByTestId("capture-field")).toBeFocused();

    // The Project control is reachable by keyboard from the field.
    const select = page.getByTestId("capture-project-select");
    await page.keyboard.press(nextControlKey);
    await expect(select).toBeFocused();
    await expect(page.getByLabel("Project")).toBeFocused();
  });

  test("a populated chooser offers its authorized Projects", async ({ page }) => {
    await signIn(page);
    const response = await page.request.get("/api/projects");
    const body = (await response.json()) as { projects?: { projectId?: string }[] };
    const rows = body.projects ?? [];
    test.skip(rows.length === 0, "this stack seeds no Project for the synthetic Principal");

    await openCaptureNote(page);
    const select = page.getByTestId("capture-project-select");
    // Nonempty execution: the options are the authorized page plus No Project.
    await expect(select.locator("option")).toHaveCount(rows.length + 1);
    await select.selectOption(rows[0]!.projectId!);
    await expect(select).toHaveValue(rows[0]!.projectId!);
  });

  test("the opened Capture surface has no axe violations", async ({ page }) => {
    await signIn(page);
    await openCaptureNote(page);
    await expect(page.getByTestId("capture-project-select")).toBeVisible();

    const results = await new AxeBuilder({ page })
      // Scan the active canonical Dialog or phone Sheet.
      .include('dialog[open], [role="dialog"][data-state="open"]')
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });

  test("saving announces its outcome in a live region", async ({ page }) => {
    await signIn(page);
    await openCaptureNote(page);
    const note = syntheticNote("wp08-a11y-live");
    await page.getByTestId("capture-field").fill(note);
    await page.getByRole("button", { name: "Save" }).click();

    // Whatever the outcome, it is announced rather than only styled.
    const announced = page.locator('[role="status"], [role="alert"]').filter({ visible: true });
    await expect(announced.first()).toBeVisible();
  });

  test("focus returns to Capture after the Task handoff and back", async ({ page }) => {
    await signIn(page);
    await visibleCaptureButton(page).click();
    const launcher = page.getByRole("dialog", { name: "Search or create" });
    await expect(launcher.getByRole("button", { name: "Search", exact: true })).toBeFocused();
    await launcher.getByRole("button", { name: "New", exact: true }).click();
    await launcher.getByRole("button", { name: "Create Task", exact: true }).click();
    await expect(page.getByTestId("task-create-sheet")).toBeVisible();

    await page.getByTestId("task-create-back").click();
    await expect(launcher.getByRole("group", { name: "Create new", exact: true })).toBeVisible();
    await expect(launcher.getByRole("button", { name: "Create Task", exact: true })).toBeFocused();
    // There is exactly one overlay: New is resumed, not stacked under Task.
    await expect(page.getByTestId("task-create-sheet")).toHaveCount(0);
    await expect(page.locator('dialog[open], [role="dialog"][data-state="open"]').filter({ visible: true })).toHaveCount(1);
  });

  test("WP08 Capture Project opened controls preserve focus and width", async ({ page }) => {
    await signIn(page);

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await openCaptureNote(page);

      const select = page.getByTestId("capture-project-select");
      await expect(select).toBeVisible();
      await select.focus();
      await expect(select).toBeFocused();

      // Nothing at this width pushes the document sideways.
      expect(await hasHorizontalOverflow(page), `horizontal overflow at ${width}px`).toBe(false);

      // The control stays within the viewport and keeps a coarse-pointer height.
      const box = await select.boundingBox();
      expect(box, `the Project control has no box at ${width}px`).toBeTruthy();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
      expect(box!.height).toBeGreaterThanOrEqual(44);

      // And focus is still inside the surface after the measurement.
      await expect(page.getByLabel("Project")).toBeFocused();
      await page.getByTestId("capture-close").click();
      await page.keyboard.press("Escape").catch(() => undefined);
    }
  });
});
