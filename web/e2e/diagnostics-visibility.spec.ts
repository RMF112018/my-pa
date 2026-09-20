/**
 * Global diagnostic visibility, in a real browser against the live stack.
 *
 * The unit suite proves the parser, the route and the provider in isolation.
 * What only a browser can establish is the part the contract actually cares
 * about: that a signed-in person who has never touched the toggle sees an
 * application in which the diagnostics were never written — in the DOM, in the
 * accessibility tree, and across a server round trip — and that the preference
 * they do set survives navigation, reload and a new browser context.
 *
 * **The no-flash assertion is the one worth reading carefully.** It does not
 * watch for a flicker, because watching is a race and a race that passes proves
 * nothing. It reads the *server's own HTML* for the page before any JavaScript
 * runs. If diagnostics were rendered on the server and stripped at hydration —
 * the pattern the contract explicitly rejects — the markup would be in that
 * response, and no amount of client-side tidying would remove it from there.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

/** Every diagnostic hook the System page renders when diagnostics are on. */
const SYSTEM_DIAGNOSTIC_TEST_IDS = [
  "system-principal-id",
  "system-identity-subject",
  "system-readiness",
  "system-available",
  "system-worker-planes",
  "system-source-commit",
  "system-pwa-this-browser",
  "system-refresh",
];

async function gotoSystem(page: Page): Promise<void> {
  await page.goto("/system");
  // The page heading by its own id. A name match on "System" is ambiguous once
  // diagnostics are on, because "Who you are to this system" is a heading too.
  await expect(page.locator("#system-heading")).toBeVisible();
}

async function toggle(page: Page) {
  return page.getByTestId("show-diagnostics-toggle");
}

/** Turn diagnostics on and wait for the server to have accepted it. */
async function turnOn(page: Page): Promise<void> {
  const control = await toggle(page);
  await expect(control).toHaveAttribute("aria-checked", "false");
  const accepted = page.waitForResponse(
    (response) =>
      response.url().includes("/api/system/diagnostics") && response.request().method() === "POST",
  );
  await control.click();
  const response = await accepted;
  expect(response.status()).toBe(200);
  await expect(control).toHaveAttribute("aria-checked", "true");
}

test.describe("diagnostics are off until someone turns them on", () => {
  test("a fresh signed-in browser shows one control and no diagnostics", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);

    const control = await toggle(page);
    await expect(control).toHaveAttribute("role", "switch");
    await expect(control).toHaveAttribute("aria-checked", "false");

    // Exactly one control in the whole application, and it is here.
    await expect(page.getByRole("switch")).toHaveCount(1);
    await expect(page.getByRole("switch", { name: /show diagnostics/i })).toBeVisible();

    for (const testId of SYSTEM_DIAGNOSTIC_TEST_IDS) {
      await expect(page.getByTestId(testId)).toHaveCount(0);
    }

    // No placeholder standing in for the hidden content.
    await expect(page.getByText(/diagnostics are hidden/i)).toHaveCount(0);
  });

  test("the server never renders diagnostics into the HTML while off", async ({ page, request }) => {
    await signIn(page);
    await gotoSystem(page);

    // Read the server's own response for /system, carrying this browser's
    // cookies, with no client JavaScript involved at all.
    const cookies = await page.context().cookies();
    const header = cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");
    const response = await request.get("/system", { headers: { cookie: header } });
    expect(response.status()).toBe(200);
    const html = await response.text();

    expect(html).toContain("Show diagnostics");
    // If any of these were server-rendered and removed at hydration, they would
    // still be here. Their absence is what rules out the SSR-then-strip pattern.
    for (const testId of SYSTEM_DIAGNOSTIC_TEST_IDS) {
      expect(html).not.toContain(`data-testid="${testId}"`);
    }
    expect(html).not.toContain("contracted capabilities");
    expect(html).not.toContain("last heartbeat");
  });

  test("no query parameter turns diagnostics on", async ({ page }) => {
    await signIn(page);
    for (const query of [
      "?diagnostics=1",
      "?diagnostics=true",
      "?debug=1",
      "?showDiagnostics=true",
    ]) {
      await page.goto(`/system${query}`);
      await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
        "aria-checked",
        "false",
      );
      await expect(page.getByTestId("system-readiness")).toHaveCount(0);
    }
  });

  test("a malformed preference cookie resolves off", async ({ page, context }) => {
    await signIn(page);
    // A value this application did not write carries no authority.
    const url = new URL(page.url());
    await context.addCookies([
      {
        name: "my-pa-diagnostics",
        value: "v1.not-a-binding.on",
        domain: url.hostname,
        path: "/",
      },
    ]);
    await gotoSystem(page);
    await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await expect(page.getByTestId("system-readiness")).toHaveCount(0);
  });
});

test.describe("turning diagnostics on and off", () => {
  test("on renders governed diagnostics with no second control", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);
    await turnOn(page);

    await expect(page.getByTestId("system-principal-id")).toBeVisible();
    await expect(page.getByTestId("system-source-commit")).toBeVisible();

    // ON is presentation authority only: it does not add a second switch.
    await expect(page.getByRole("switch")).toHaveCount(1);
  });

  test("off unmounts diagnostics and their focus targets", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);
    await turnOn(page);
    await expect(page.getByTestId("system-refresh")).toBeVisible();

    const control = await toggle(page);
    const accepted = page.waitForResponse(
      (response) =>
        response.url().includes("/api/system/diagnostics") &&
        response.request().method() === "POST",
    );
    await control.click();
    await accepted;

    await expect(control).toHaveAttribute("aria-checked", "false");
    for (const testId of SYSTEM_DIAGNOSTIC_TEST_IDS) {
      await expect(page.getByTestId(testId)).toHaveCount(0);
    }
    // The control that was removed must not have left focus stranded on a
    // detached node.
    await expect(page.locator("body")).toBeFocused({ timeout: 2000 }).catch(async () => {
      // Some engines move focus to the toggle instead; either is a live node.
      await expect(control).toBeFocused();
    });
  });

  test("the accepted preference survives navigation and reload", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);
    await turnOn(page);

    await page.goto("/today");
    await gotoSystem(page);
    await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await page.reload();
    await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.getByTestId("system-readiness")).toBeVisible();
  });

  test("the toggle is operable from the keyboard alone", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);
    const control = await toggle(page);
    await control.focus();
    await expect(control).toBeFocused();

    const accepted = page.waitForResponse(
      (response) =>
        response.url().includes("/api/system/diagnostics") &&
        response.request().method() === "POST",
    );
    await page.keyboard.press("Enter");
    await accepted;
    await expect(control).toHaveAttribute("aria-checked", "true");
  });
});

test.describe("the preference belongs to the session that set it", () => {
  test("a signed-out browser comes back to diagnostics off", async ({ page }) => {
    await signIn(page);
    await gotoSystem(page);
    await turnOn(page);

    // Sign out clears the preference along with the session.
    //
    // The `Origin` header is required, not incidental: `admitBrowserMutation`
    // refuses a state-changing request that does not prove it came from this
    // origin, and a 403 here would leave the session standing and make the
    // assertion below measure nothing.
    const origin = new URL(page.url()).origin;
    const signedOut = await page.request.delete("/api/session", {
      headers: { origin },
    });
    expect(signedOut.status()).toBe(200);
    await signIn(page);
    await gotoSystem(page);
    await expect(page.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await expect(page.getByTestId("system-readiness")).toHaveCount(0);
  });

  test("a separate browser context does not inherit the preference", async ({ page, browser }) => {
    await signIn(page);
    await gotoSystem(page);
    await turnOn(page);

    // A new context is a different browser profile: nothing carries over.
    const fresh = await browser.newContext();
    const freshPage = await fresh.newPage();
    await signIn(freshPage);
    await gotoSystem(freshPage);
    await expect(freshPage.getByTestId("show-diagnostics-toggle")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await fresh.close();
  });
});

test.describe("ordinary product truth is unaffected", () => {
  test("Today renders real content, and still does once diagnostics are on", async ({ page }) => {
    // Scope note. This asserts what it can see from outside: Today reaches a
    // non-empty rendered surface in each mode. It deliberately does not diff the
    // two readings — this suite shares one synthetic stack and other specs
    // create Tasks between the two navigations, so a region-by-region
    // comparison measures that data flux rather than the mode. An earlier
    // attempt did exactly that and failed in CI for exactly that reason. The
    // per-surface "product truth survives OFF" claims are made where they can
    // be made deterministically — in the component suites, against fixed data.
    await signIn(page);

    await page.goto("/today");
    await expect(page.getByRole("heading", { name: /today/i }).first()).toBeVisible();
    const offText = (await page.locator("main").textContent()) ?? "";
    expect(offText.trim().length).toBeGreaterThan(0);

    await gotoSystem(page);
    await turnOn(page);
    await page.goto("/today");
    await expect(page.getByRole("heading", { name: /today/i }).first()).toBeVisible();
    const onText = (await page.locator("main").textContent()) ?? "";
    expect(onText.trim().length).toBeGreaterThan(0);
  });

  test("System Security stays reachable and independent of diagnostics", async ({ page }) => {
    await signIn(page);
    await page.goto("/system/security");
    // Passkey and recovery administration is separately authorized and must not
    // depend on a presentation preference.
    await expect(page.getByRole("heading").first()).toBeVisible();
    expect(page.url()).toContain("/system/security");
  });
});
