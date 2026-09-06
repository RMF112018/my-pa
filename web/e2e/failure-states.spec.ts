/**
 * What every surface does when the application gateway is genuinely not there.
 *
 * **Nothing is stubbed to produce this.** These specs run against a second Next
 * server whose `MYPA_GATEWAY_URL` names a loopback port nothing listens on, so
 * the connection is really refused, the real transport really catches it, and
 * the real error mapping really produces `unavailable`. A route interception in
 * the browser could not have reached this path at all — the gateway call is made
 * on the server — and a mocked `callGateway` would have proved something about
 * the mock.
 *
 * The claim under test is the single most important one in this package: **an
 * unreachable backend must not render as an empty record.** A person who reads
 * "you have not captured anything yet" when the truth is "we could not ask"
 * has been told a fact about their own record that nothing established.
 */
import { test, expect } from "@playwright/test";
import { DEAD_GATEWAY_URL } from "../playwright.config";
import { signIn, expectState, EMPTINESS_CLAIMS } from "./fixtures";

test.use({ baseURL: DEAD_GATEWAY_URL });

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

const SURFACES = [
  { path: "/knowledge", testId: "library-unavailable", heading: "Knowledge" },
  { path: "/today", testId: "today-unavailable", heading: "Today" },
  { path: "/review", testId: "review-queue-unavailable", heading: "Review" },
  { path: "/work", testId: "state-unavailable", heading: "Work" },
  { path: "/intelligence", testId: "intelligence-unavailable", heading: "Intelligence" },
  // People without `q` is the idle prompt, not a search. The unresolved-mentions
  // panel swallows a failed read, so the dead-gateway search path is `?q=`.
  { path: "/people?q=synthetic-dead-gateway", testId: "people-search-unavailable", heading: "People" },
  // Search is a client fetch after paint; the gateway timeout is 10s per fan-out.
  {
    path: "/search?q=synthetic-dead-gateway",
    testId: "search-unavailable",
    heading: "Search",
    visibleTimeout: 45_000,
  },
  // `/canvas` without a seed is `canvas-seed-required` and never asks the gateway.
  {
    path: "/canvas?focusEntityId=ent_syntheticdeadgw01",
    testId: "canvas-unavailable",
    heading: "Map",
  },
  { path: "/knowledge/goodnotes", testId: "goodnotes-notebooks-unavailable", heading: "GoodNotes" },
] as const;

for (const surface of SURFACES) {
  test(`${surface.heading} states the failure and claims nothing`, async ({ page }) => {
    if ("visibleTimeout" in surface) test.setTimeout(180_000);
    await page.goto(surface.path);
    await expect(page.getByRole("heading", { name: surface.heading, level: 1 })).toBeVisible();
    const timeout = "visibleTimeout" in surface ? surface.visibleTimeout : undefined;
    await expect(page.getByTestId(surface.testId)).toBeVisible({ timeout });
    await expectState(page, surface.testId, "unavailable");

    const region = page.getByTestId(surface.testId);
    if (surface.heading === "Search") {
      // Federated Search still returns HTTP 200 with per-domain unavailable
      // coverage when the gateway is down. The panel must not call that empty.
      await expect(region).toContainText(/could not be searched|could not be read/i);
    } else {
      await expect(region).toContainText(/did not answer/i);
      await expect(region).toContainText(/nothing was retrieved/i);
    }

    const text = (await region.textContent()) ?? "";
    for (const claim of EMPTINESS_CLAIMS) {
      expect(text, `${surface.path} claimed emptiness on a failed read`).not.toMatch(claim);
    }

    // And no empty-state region is rendered anywhere on the page.
    await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
  });
}

test("System says the build could not describe itself", async ({ page }) => {
  await page.goto("/system");
  await expectState(page, "system-unavailable", "unavailable");
  // Identity is still shown, because it does not come from the gateway.
  await expect(page.getByTestId("system-principal-id")).toBeVisible();
  // And Graph is still reported as deliberately off, not as a casualty.
  await expect(page.getByTestId("system-graph")).toContainText(/deliberately/i);
});

test("a capture against a dead gateway is never rendered as saved", async ({ page }) => {
  await page.goto("/today");
  await page.getByTestId("capture-button").click();
  await page.getByTestId("capture-field").fill("E2E synthetic note — dead gateway path.");
  await page.getByRole("button", { name: "Save" }).click();

  // The request reached this server, which could not reach the gateway. That is
  // `unavailable`: nothing stored, note kept in the field, retry is meaningful.
  const unavailable = page.getByTestId("capture-unavailable");
  await expect(unavailable).toBeVisible();
  await expect(unavailable).toContainText(/Not saved/i);
  await expect(unavailable).toContainText(/still in the field/i);
  await expect(page.getByTestId("capture-durable")).toHaveCount(0);
  // The note really is still there — this is the difference between a stated
  // failure and a lost note.
  await expect(page.getByTestId("capture-field")).toHaveValue(/dead gateway path/);
});
