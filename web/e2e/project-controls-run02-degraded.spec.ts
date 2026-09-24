/**
 * R02-WP10 Phase 8 — degraded/failure-state hardening for Project Controls.
 *
 * Not row-numbered (`IMPL-6-PHASE8-9-TESTS.md` §3): pushes harder on the
 * actual transport-failure paths — a genuinely unreachable gateway, a
 * malformed HTTP-200 success, and rate limiting — than what
 * `PC-CM-FE-AC-122/125/126/127/129` already assert functionally in
 * `project-controls-run02.spec.ts`.
 *
 * **House convention, read directly from `web/e2e/failure-states.spec.ts`
 * per this worker's dispatch.** That file's technique for "the gateway is
 * genuinely not there" is a second real Next server pointed at a loopback
 * port nothing listens on (`DEAD_GATEWAY_URL`) — not a browser-level mock —
 * because the capability call happens server-side and a `page.route`
 * interception cannot reach it. This file reuses that exact mechanism for
 * its gateway-unavailable coverage. Malformed-success and rate-limiting are
 * shapes a dead gateway cannot produce (a dead gateway is always a refusal,
 * never a well-formed-but-wrong 200, and never a 429); those two use
 * `page.route` against the real, live stack instead — the same technique
 * `today-tasks.spec.ts` and `work-mutations.spec.ts` already use elsewhere
 * in this repository for the same reason.
 */
import { expect, test } from "@playwright/test";
import { DEAD_GATEWAY_URL } from "../playwright.config";
import { signIn } from "./fixtures";

const PROJECT = "prj_e2ecst0000000001";
const SEEDED_CATEGORY = "ccat_e2ecst0000000001";

const RUN = Date.now().toString(36);
function marker(step: string): string {
  return `e2e-run02-deg-${RUN}-${step}`;
}

// =============================================================================
// A genuinely unreachable gateway (dead-gateway server, per house convention).
// =============================================================================

test.describe("gateway genuinely unavailable", () => {
  test.use({ baseURL: DEAD_GATEWAY_URL });

  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("the exact-Project Constraint workspace states unavailable and claims no Constraints, no false zero", async ({
    page,
  }) => {
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await expect(page.getByTestId("register-unavailable")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/^0 Constraints/)).toHaveCount(0);
    await expect(page.getByTestId("register-empty-project")).toHaveCount(0);
  });

  test("the portfolio Constraint route states unavailable rather than an empty portfolio", async ({ page }) => {
    await page.goto("/work/constraints");
    await expect(page.getByTestId("portfolio-constraints-unavailable")).toBeVisible({ timeout: 30_000 });
  });

  test("the Work command center's Constraints panel states unavailable, and the rest of the page still renders", async ({
    page,
  }) => {
    await page.goto("/situations");
    await expect(page.getByRole("heading", { name: "Situations", level: 1 })).toBeVisible();
    await expect(page.getByTestId("work-constraints-unavailable")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("work-constraints-panel")).toHaveCount(0);
  });

  test("a dead gateway blocks every write entry point rather than offering a form that can only fail silently", async ({
    page,
  }) => {
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await expect(page.getByTestId("register-unavailable")).toBeVisible({ timeout: 30_000 });
    // The Register's own read failed, so its New Constraint entry point does
    // not render at all — there is no dialog here that could go on to fail a
    // write silently or optimistically.
    await expect(page.getByTestId("register-new-constraint")).toHaveCount(0);
  });
});

// =============================================================================
// Malformed HTTP-200 successes (page.route, real stack otherwise).
// =============================================================================

test.describe("malformed successful responses fail closed", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  // PRODUCT GAP (reported, not fixed here — see this worker's handoff, and
  // the identical, fully-diagnosed note on `[PC-CM-FE-AC-126]` in
  // `project-controls-run02.spec.ts`): `constraint-live.ts`'s `overview()`
  // reads `value.syncHealth.state` with no validation that `syncHealth`
  // exists on the malformed body, throwing an uncaught client-side
  // `TypeError` instead of a caught "failed" read outcome — `Overview` may
  // never reach `overview-unavailable`. Bounded below rather than left at the
  // suite's 90s default.
  test("a malformed Overview answer is unavailable, never rendered as a valid one", async ({ page }) => {
    await page.route(`**/api/project-controls/projects/${PROJECT}/constraints/overview`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ shape: "backend", overview: { totalOpen: "not-a-number" } }),
      });
    });
    await page.goto(`/work/projects/${PROJECT}/constraints`);
    await expect(
      page.getByTestId("overview-unavailable"),
      "PRODUCT GAP — constraint-live.ts's overview() throws an uncaught TypeError reading " +
        "value.syncHealth.state on a malformed-but-200 body instead of classifying it as a read failure. See handoff.",
    ).toBeVisible({ timeout: 20_000 });
    await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints/overview`);
  });

  // PRODUCT GAP (reported, not fixed here — see this worker's handoff, and
  // the identical, fully-diagnosed note on `[PC-CM-FE-AC-126]` in
  // `project-controls-run02.spec.ts`): `constraint-live.ts`'s `readCategories`
  // calls `response.value.categories.map(category)` with no validation that
  // `categories` is actually an array, throwing an uncaught client-side
  // `TypeError` instead of a caught "failed" read outcome. Bounded below
  // rather than left at the suite's 90s default.
  test("a malformed Category list answer is stated as a read failure, not an empty scheme", async ({ page }) => {
    await page.route(`**/api/project-controls/projects/${PROJECT}/constraint-categories?**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ shape: "backend", categories: { not: "an-array" } }),
      });
    });
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await expect(
      page.getByText(/categories could not be read/i),
      "PRODUCT GAP — constraint-live.ts's readCategories throws an uncaught TypeError calling .map() on a " +
        "malformed-but-200 body instead of classifying it as a read failure. See handoff.",
    ).toBeVisible({ timeout: 20_000 });
    await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraint-categories?**`);
  });

  test("a malformed publish success is not shown as a confirmed Constraint", async ({ page }) => {
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await page.getByTestId("register-new-constraint").click();
    const description = marker("malformed-publish");
    await page.getByTestId("authoring-description").fill(description);
    await page.getByTestId("authoring-category").selectOption(SEEDED_CATEGORY);
    // PRODUCT GAP (see project-controls-run02.spec.ts's header note and its
    // `addPartyMeViaPopover` helper): the BIC Popover portals outside the
    // native <dialog>'s top layer and is intercepted by the underlying page.
    await page.getByTestId("authoring-bic-add").click();
    await expect(page.getByTestId("authoring-bic-add-me")).toBeVisible({ timeout: 5_000 });
    await page.getByTestId("authoring-bic-add-me").click({ timeout: 8_000 });
    await page.route(`**/api/project-controls/projects/${PROJECT}/constraints`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ shape: "backend", disposition: "applied", constraint: { constraintId: 12345 } }),
      });
    });
    await page.getByTestId("authoring-publish").click();
    await expect(page.getByTestId("authoring-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("authoring-description")).toHaveValue(description);
    await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints`);
  });
});

// =============================================================================
// Rate limiting (page.route, real stack otherwise).
// =============================================================================

test.describe("rate limiting preserves input and offers only manual retry", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("a rate-limited Category create preserves its authored fields", async ({ page }) => {
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    await page.getByTestId("open-categories").click();
    await page.getByTestId("category-create").click();
    const title = marker("rate-limited-category");
    await page.getByTestId("category-form-prefix").fill("4");
    await page.getByTestId("category-form-title").fill(title);
    await page.route(`**/api/project-controls/projects/${PROJECT}/constraint-categories`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ error: { errorClass: "rate_limited", code: "e2e_forced_rate_limit" } }),
      });
    });
    await page.getByTestId("category-form-submit").click();
    await expect(page.getByTestId("category-form-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("category-form-title")).toHaveValue(title);
    await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraint-categories`);
  });

  test("a rate-limited inline Register edit does not auto-retry, and the attempted value stays in the editor", async ({
    page,
  }) => {
    await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
    const constraintId = "cst_e2ecst0000000002";
    let attempts = 0;
    await page.route(
      `**/api/project-controls/projects/${PROJECT}/constraints/${constraintId}`,
      async (route) => {
        if (route.request().method() !== "PATCH") return route.continue();
        attempts += 1;
        await route.fulfill({
          status: 429,
          contentType: "application/json",
          body: JSON.stringify({ error: { errorClass: "rate_limited", code: "e2e_forced_rate_limit" } }),
        });
      },
    );
    await page.getByTestId(`register-inline-due-${constraintId}`).fill("2027-03-01");
    await expect(page.getByTestId(`register-inline-due-error-${constraintId}`)).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(500);
    expect(attempts, "no automatic retry must have fired").toBe(1);
    await expect(page.getByTestId(`register-inline-due-${constraintId}`)).toHaveValue("2027-03-01");
    await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints/${constraintId}`);
  });
});
