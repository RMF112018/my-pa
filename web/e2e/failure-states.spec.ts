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
 *
 * Not a required e2e-critical member. WP28 runs this file as advisory
 * `frontend / degraded-gateway` after pointing `MYPA_SESSION_SERVICE_URL` at the
 * live gateway while `MYPA_GATEWAY_URL` remains unreachable. Playwright WebKit
 * is not Safari; this job is Chromium desktop only.
 */
import { test, expect } from "@playwright/test";
import { DEAD_GATEWAY_URL } from "../playwright.config";
import { signIn, expectState, EMPTINESS_CLAIMS, openCaptureNote } from "./fixtures";

test.use({ baseURL: DEAD_GATEWAY_URL });

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

/**
 * Turn diagnostics on for this browser, through the one route that can.
 *
 * WP07 made raw transport text diagnostic presentation, governed globally and
 * off by default. WP08-RT-F010 then closed the vocabulary: the gateway's own
 * `ErrorEnvelope.message` ("the application gateway did not answer") is dropped
 * at the boundary and is never rendered in either mode, and what names the
 * unreachable gateway with diagnostics on is the allowlisted machine code
 * `gateway_unreachable` alongside its class and `HTTP 503`. The assertions
 * below therefore test that spelling; none of them was deleted.
 *
 * The *operational* half of this file's claim is unaffected and is still
 * asserted in the default mode: the state is `unavailable`, it is an `alert`,
 * it says nothing was retrieved, it offers Retry, and it never claims
 * emptiness. What moves behind the policy is only the naming of the gateway.
 *
 * The session-service is live on this server even though the capability
 * gateway is not, so this write succeeds while every capability read fails —
 * which is exactly the situation the file exists to exercise.
 */
async function enableDiagnostics(page: import("@playwright/test").Page): Promise<void> {
  const response = await page.request.post("/api/system/diagnostics", {
    headers: { origin: DEAD_GATEWAY_URL, "content-type": "application/json" },
    data: { enabled: true },
  });
  expect(response.status()).toBe(200);
}

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
      // Diagnostics are off by default, so the gateway is not named. What must
      // survive is the operational truth: a failed read, stated as one, and no
      // claim about what the person holds. The clarification is the sentence
      // every unavailable state shares, whatever its per-surface heading.
      await expect(region).toContainText(/nothing was retrieved/i);
      // And the diagnostic half is absent. The token asserted here is the one
      // the closed vocabulary actually emits for this failure — the same token
      // the diagnostics-on test below requires — so this discriminates between
      // the two modes rather than naming a string neither mode renders.
      await expect(region).not.toContainText(/gateway_unreachable/i);
    }

    const text = (await region.textContent()) ?? "";
    for (const claim of EMPTINESS_CLAIMS) {
      expect(text, `${surface.path} claimed emptiness on a failed read`).not.toMatch(claim);
    }

    // And no empty-state region is rendered anywhere on the page.
    await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
  });
}

test("no raw transport text reaches the browser while diagnostics are off", async ({
  page,
}) => {
  // WP07 / F-01. Rendering the diagnostic and hiding it on the client is the
  // "server-render then strip" pattern the contract rejects, and a DOM
  // assertion cannot see it: a client component's props are serialized into
  // the RSC Flight payload that ships inside the HTML, before any client gate
  // runs. So this reads the server's own bytes.
  //
  // `view-source` on a failed read used to disclose the gateway's raw message
  // on every one of these surfaces. It must disclose no transport detail at
  // all. The two patterns below are the ones the closed vocabulary emits for a
  // dead gateway with diagnostics on — the allowlisted code and the rendered
  // status — so each would really be found in these bytes in the other mode.
  const cookies = await page.context().cookies();
  const header = cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");

  for (const path of [
    "/work",
    "/today",
    "/knowledge",
    "/review",
    "/intelligence",
    "/people?q=synthetic-dead-gateway",
    "/knowledge/goodnotes",
  ]) {
    const response = await page.request.get(path, { headers: { cookie: header } });
    expect(response.status(), path).toBe(200);
    const body = await response.text();
    expect(body, `${path} served a transport code while diagnostics were off`).not.toMatch(
      /gateway_unreachable/i,
    );
    expect(body, `${path} served a transport status while diagnostics were off`).not.toMatch(
      /HTTP 503/i,
    );
  }
});

test("Work names the unreachable gateway once diagnostics are on", async ({ page }) => {
  await enableDiagnostics(page);
  await page.goto("/work");
  const region = page.getByTestId("state-unavailable");
  await expect(region).toBeVisible();
  // The gateway is named by the allowlisted machine code, which is what the
  // closed vocabulary carries in place of the dropped `ErrorEnvelope.message`.
  await expect(region).toContainText(/gateway_unreachable/i);
  // Turning diagnostics on adds the transport detail; it must not change what
  // the state *means*, so the operational assertions are repeated here.
  await expect(region).toContainText(/nothing was retrieved/i);
  const text = (await region.textContent()) ?? "";
  for (const claim of EMPTINESS_CLAIMS) {
    expect(text, "an unavailable read claimed emptiness with diagnostics on").not.toMatch(claim);
  }
});

test("root System asks the gateway nothing while diagnostics are off", async ({ page }) => {
  await page.goto("/system");
  // The page's only gateway reads exist to render diagnostics, so with
  // diagnostics off there is no read to fail and nothing to report as
  // unavailable. Reporting one would be inventing a failure that never
  // happened.
  await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
    "aria-checked",
    "false",
  );
  await expect(page.getByTestId("system-unavailable")).toHaveCount(0);
  await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
});

test("System says the build could not describe itself", async ({ page }) => {
  await enableDiagnostics(page);
  await page.goto("/system");
  await expectState(page, "system-unavailable", "unavailable");
  // Identity is still shown, because it does not come from the gateway.
  await expect(page.getByTestId("system-principal-id")).toBeVisible();
  // And Graph is still reported as deliberately off, not as a casualty.
  await expect(page.getByTestId("system-graph")).toContainText(/deliberately/i);
});

test("a capture against a dead gateway is never rendered as saved", async ({ page }) => {
  await page.goto("/today");
  await openCaptureNote(page);
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
