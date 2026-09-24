/**
 * R02-WP10 Phase 8 — responsive hardening over the Phase 4-7 Project Controls
 * surfaces.
 *
 * Not row-numbered (`IMPL-6-PHASE8-9-TESTS.md` §3): proves the Picker,
 * Register (`RegisterTable`/`RegisterCardList`), Inspector and authoring
 * surfaces fit the required width matrix across desktop/tablet/mobile
 * without overflow, clipping or unreachable controls.
 *
 * Carries the required literal sentinel test (checked verbatim by
 * `verify-e2e-selection.mjs`, and by this campaign's own
 * `test_constraint_run02_ci_selection.py`) and this file's half of the four
 * required `@run02-mobile` tests (the other two live in
 * `capture-constraint.spec.ts` — see that file's header for the split).
 *
 * **The Picker portion of the width-matrix sentinel is honestly red.**
 * `<ProjectPicker>` is not mounted at this head — see
 * `project-controls-run02.spec.ts`'s header note for the full repro. Its own
 * overlay is still opened for real below, and the sentinel test's own Picker
 * assertion is expected to fail for exactly that reason until the
 * Integrator's Phase-9 wiring lands.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";
import { LIVE_URL } from "../playwright.config";

const PROJECT = "prj_e2ecst0000000001";
const SEEDED_CATEGORY = "ccat_e2ecst0000000001";

function constraintsRoute(projectId: string): string {
  return `/work/projects/${projectId}/constraints`;
}

const RUN = Date.now().toString(36);
function marker(step: string): string {
  return `e2e-run02-resp-${RUN}-${step}`;
}

/** The four phone widths the responsive brief names, plus tablet and desktop. */
const NARROW_WIDTHS = [320, 375, 390, 430] as const;
const WIDTH_MATRIX = [
  ...NARROW_WIDTHS.map((width) => ({ width, height: 844 })),
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
] as const;

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

// =============================================================================
// The required literal sentinel — checked verbatim by CI tooling.
// =============================================================================

test("[RUN02-RESPONSIVE] Project controls opened overlays fit the required width matrix", async ({ page }) => {
  test.setTimeout(180_000);
  for (const { width, height } of WIDTH_MATRIX) {
    await page.setViewportSize({ width, height });

    // Register (table on desktop/tablet, card list on the narrow widths).
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await expect(page.getByTestId("register-table").or(page.getByTestId("register-card-list"))).toBeVisible({
      timeout: 15_000,
    });
    expect(await horizontalOverflow(page), `Register at ${width}x${height}`).toBeLessThanOrEqual(1);

    // Create Constraint.
    await page.getByTestId("register-new-constraint").click();
    await expect(page.getByTestId("authoring-description")).toBeVisible();
    expect(await horizontalOverflow(page), `Create Constraint at ${width}x${height}`).toBeLessThanOrEqual(1);
    await page.getByTestId("authoring-cancel").click();

    // Inspector (open the seeded row).
    await page.getByTestId("register-search").fill("Switchgear");
    const row = page.getByTestId("register-table").or(page.getByTestId("register-card-list"));
    await expect(row).toContainText("1.01", { timeout: 15_000 });
    await page.getByRole("button", { name: "1.01" }).first().click();
    await expect(page.getByTestId("constraint-inspector")).toBeVisible();
    expect(await horizontalOverflow(page), `Inspector at ${width}x${height}`).toBeLessThanOrEqual(1);
    await page.getByTestId("inspector-close-panel").click();

    // Category administration.
    await page.getByTestId("open-categories").click();
    await expect(page.getByTestId("category-table")).toBeVisible();
    expect(await horizontalOverflow(page), `Category admin at ${width}x${height}`).toBeLessThanOrEqual(1);
    await page.getByTestId("category-close").click();

    // The Project Picker — honestly red, see this file's header note. Mounted
    // (once the Integrator's staged patch lands) only on `/work/projects/:id`
    // routes, per `IMPL-2-context-header.patch`'s own gating.
    await page.goto(constraintsRoute(PROJECT));
    const picker = page.getByRole("combobox", { name: "Project Picker" });
    await expect(picker, "see this file's header note — the Picker is not mounted at this head").toBeVisible({
      timeout: 5_000,
    });
    expect(await horizontalOverflow(page), `Project Picker at ${width}x${height}`).toBeLessThanOrEqual(1);
  }
});

// =============================================================================
// Non-sentinel responsive coverage across the three fixture viewports.
// =============================================================================

test("the Register switches from a table to a card list at the mobile breakpoint without loss of Project identity", async ({
  page,
}) => {
  await page.goto("/work/constraints");
  await expect(page.getByTestId("register-table").or(page.getByTestId("register-card-list"))).toBeVisible({
    timeout: 15_000,
  });
  const project = test.info().project.name;
  if (project === "mobile") {
    await expect(page.getByTestId("register-card-list")).toBeVisible();
    await expect(page.getByTestId("register-table")).toHaveCount(0);
  } else {
    await expect(page.getByTestId("register-table")).toBeVisible();
  }
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
});

test("authoring and direct-action dialogs remain fully reachable and unclipped at this project's own viewport", async ({
  page,
}) => {
  await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
  await page.getByTestId("register-new-constraint").click();
  await expect(page.getByTestId("authoring-description")).toBeVisible();
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
  const description = marker("responsive-dialog");
  await page.getByTestId("authoring-description").fill(description);
  await page.getByTestId("authoring-category").selectOption(SEEDED_CATEGORY);
  // PRODUCT GAP (see project-controls-run02.spec.ts's header note and its
  // `addPartyMeViaPopover` helper): the BIC Popover portals outside the
  // native <dialog>'s top layer and is intercepted by the underlying page.
  await page.getByTestId("authoring-bic-add").click();
  await expect(page.getByTestId("authoring-bic-add-me")).toBeVisible({ timeout: 5_000 });
  await page.getByTestId("authoring-bic-add-me").click({ timeout: 8_000 });
  await page.getByTestId("authoring-publish").click();
  await expect(page.getByTestId("constraint-inspector")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("inspector-close").click();
  await expect(page.getByTestId("direct-action-confirm")).toBeVisible();
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
  await page.getByTestId("direct-action-cancel").click();
});

// =============================================================================
// @run02-mobile sentinels (this file's half of the required four)
// =============================================================================

test("@run02-mobile Picker All Projects to Project", async ({ page }) => {
  test.skip(!["mobile", "mobile-webkit"].includes(test.info().project.name), "phone-geometry sentinel");
  // The Picker mounts (once the Integrator's staged
  // `IMPL-2-context-header.patch` lands) only on `/work/projects/:id`
  // routes, and choosing All Projects from it navigates to `/work` — which
  // is not itself project-aware, so the Picker cannot remain mounted while
  // *showing* All Projects as its own settled value. This proves both
  // directions of the one round trip the title names: from a Project's own
  // Picker to All Projects, and — by an authorized deep link, per
  // `PC-CM-SCOPE-AC-009` — back to a Project through it again.
  await page.request.post("/api/project-scope", {
    headers: { origin: LIVE_URL, "content-type": "application/json" },
    data: { scope: "ALL_PROJECTS" },
  });
  await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
  await expect(page.getByTestId("constraints-live-workspace")).toBeVisible();
  const picker = page.getByRole("combobox", { name: "Project Picker" });
  // Honestly red at this head — see this file's header note. Written for
  // real against the intended control so it is the first thing to go green
  // once the Integrator mounts it.
  await expect(picker, "see this file's header note — the Picker is not mounted at this head").toBeVisible({
    timeout: 5_000,
  });
  // The deep link overrode the All-Projects preference just set above
  // (`PC-CM-SCOPE-AC-009`), so the Picker's own settled value is this Project.
  await expect(picker).toHaveValue(PROJECT);
  await picker.selectOption("ALL_PROJECTS");
  await expect(page).toHaveURL(/\/work$/);
  await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
  await expect(page.getByRole("combobox", { name: "Project Picker" })).toHaveValue(PROJECT);
});

test("@run02-mobile portfolio to Project Constraint navigation", async ({ page }) => {
  test.skip(!["mobile", "mobile-webkit"].includes(test.info().project.name), "phone-geometry sentinel");
  await page.request.post("/api/project-scope", {
    headers: { origin: LIVE_URL, "content-type": "application/json" },
    data: { scope: "PROJECT", projectId: PROJECT },
  });
  await page.goto("/situations");
  await expect(page.getByRole("heading", { name: "Situations", level: 1 })).toBeVisible();
  const panel = page.getByTestId("work-constraints-panel");
  await expect(panel).toBeVisible();
  await panel.click();
  await expect(page).toHaveURL(/\/work\/(constraints|projects\/.*\/constraints)/);
  const workspace = page.getByTestId("constraints-live-workspace").or(page.getByTestId("portfolio-constraints-page"));
  await expect(workspace).toBeVisible({ timeout: 15_000 });
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
});
