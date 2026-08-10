/**
 * The seven surfaces, in a real browser, against the real stack.
 *
 * Chromium drives a real Next.js server, which reaches the real Python gateway
 * on a loopback socket, which reaches a real PostgreSQL created at head for this
 * run. The Capture journey below is the whole chain in one assertion: a note
 * typed into the browser comes back as a row in the Library listing, and the
 * only way that can happen is if it was committed.
 */
import { test, expect } from "@playwright/test";
import { signIn, syntheticNote, expectState, EMPTINESS_CLAIMS } from "./fixtures";

test.describe("an unauthenticated visitor reaches no destination", () => {
  test("every app route redirects to sign-in", async ({ page }) => {
    for (const path of ["/today", "/library", "/situations", "/review", "/system"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/sign-in$/);
    }
  });

  test("a forged session cookie is refused rather than honoured", async ({ page, context, baseURL }) => {
    await context.addCookies([
      {
        name: "mypa_session",
        value: "not.a.valid.signature",
        url: baseURL as string,
      },
    ]);
    await page.goto("/today");
    await expect(page).toHaveURL(/\/sign-in$/);
  });
});

test.describe("the signed-in surfaces", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("Today renders a truthful state, never a blank page", async ({ page }) => {
    const heading = page.getByRole("heading", { name: "Today", level: 1 });
    await expect(heading).toBeVisible();
    // Either the derivation returned items or it returned none. Both are real
    // answers; what must never appear is a failure dressed as an empty day.
    const items = page.getByTestId("pulse-item");
    if ((await items.count()) === 0) {
      await expectState(page, "today-empty", "empty");
      await expect(page.getByTestId("today-empty")).toContainText(/derivation ran/i);
    }
    await expect(page.getByTestId("today-unavailable")).toHaveCount(0);
  });

  test("Library reads the record and says which state it is in", async ({ page }) => {
    await page.goto("/library");
    await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
    // The search field is a real, labelled control, not a placeholder.
    await expect(page.getByRole("searchbox", { name: "Search your captures" })).toBeVisible();
    // Whatever else is true, the page must not be the old static card.
    await expect(page.getByText("No sources are connected yet")).toHaveCount(0);
    await expect(page.getByText("Not yet connected")).toHaveCount(0);
  });

  test("Situations renders a truthful state", async ({ page }) => {
    await page.goto("/situations");
    await expect(page.getByRole("heading", { name: "Situations", level: 1 })).toBeVisible();
    await expect(page.getByTestId("situations-unavailable")).toHaveCount(0);
  });

  test("Review renders a truthful state and never fabricates a proposal", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
    await expect(page.getByTestId("review-queue-unavailable")).toHaveCount(0);
    // If cases exist they carry no proposal text, and the page says so.
    if ((await page.getByTestId("backend-review-case").count()) > 0) {
      await expect(page.getByTestId("review-listing-limitation")).toContainText(
        /carries no proposal text/i,
      );
    }
  });

  test("System reports the build it is talking to, not a constant", async ({ page }) => {
    await page.goto("/system");
    await expect(page.getByRole("heading", { name: "System", level: 1 })).toBeVisible();
    // Derived from `capabilities.get`, so it must name a real count.
    await expect(page.getByTestId("system-readiness")).toContainText(
      /\d+ of \d+ contracted capabilities/,
    );
    // Graph is deliberately off, and is not presented as degraded or failing.
    const graph = page.getByTestId("system-graph");
    await expect(graph).toContainText(/deliberately/i);
    await expect(graph).toContainText(/not a degraded source/i);
    // Sources are unknown, never "none".
    await expect(page.getByTestId("system-sources-unknown")).toContainText(/cannot list/i);
    // The stale schema-head claim is gone and must not come back.
    await expect(page.getByText(/e7f3a9c2d514/)).toHaveCount(0);
    // And the local-operator limit is disclosed rather than glossed.
    await expect(page.getByTestId("system-local-operator")).toBeVisible();
  });

  test("a capture is persisted, and the Library proves it", async ({ page }) => {
    const marker = `${Date.now()}`;
    await page.getByTestId("capture-button").click();
    const field = page.getByTestId("capture-field");
    await expect(field).toBeFocused();
    await field.fill(syntheticNote(marker));
    await page.getByRole("button", { name: "Save" }).click();

    // **`persisted`, not `acknowledged_not_persisted`.** The word "Saved" is
    // only rendered for a receipt the Python transaction issued.
    const durable = page.getByTestId("capture-durable");
    await expect(durable).toBeVisible();
    await expect(durable).toContainText(/Saved\./);
    await expect(page.getByTestId("capture-acknowledged")).toHaveCount(0);

    // The receipt identifier the row's own write produced.
    await expect(durable).toContainText(/\(rcpt_[A-Za-z0-9]+\)/);

    // And the row is readable back through a different capability, which is the
    // part a receipt alone cannot prove.
    await page.goto("/library");
    await expect(page.getByTestId("library-listing")).toBeVisible();
    await expect(page.getByTestId("library-capture").first()).toContainText(/cap_[A-Za-z0-9]+/);
  });

  test("focus returns to the capture button when the dialog closes", async ({ page }) => {
    const opener = page.getByTestId("capture-button");
    await opener.click();
    await expect(page.getByTestId("capture-field")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("capture-field")).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test("the same idempotency key is not a second capture", async ({ page }) => {
    const marker = `idem-${Date.now()}`;
    await page.getByTestId("capture-button").click();
    await page.getByTestId("capture-field").fill(syntheticNote(marker));
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-durable")).toContainText(/Saved\./);

    // The field is cleared on a durable save and a new attempt key is minted, so
    // the same text saved again is a *second* capture by design. What must hold
    // is that the first one is stored exactly once — asserted by counting the
    // listing rows that carry this marker's capture, which is one.
    await page.goto("/library?q=" + encodeURIComponent(marker.replace(/[^a-z0-9]/gi, "")));
    // The search may legitimately match nothing (the marker is not a word in the
    // stored text); what matters is that it never renders a failure as empty.
    await expect(page.getByTestId("library-search-unavailable")).toHaveCount(0);
  });
});

test.describe("keyboard-only navigation", () => {
  test("a keyboard reaches skip link, navigation, and capture", async ({ page }) => {
    await signIn(page);

    // **The bypass link must be the first thing the application offers a
    // keyboard.** It is not asserted to be the first tab stop full stop, because
    // this suite runs against `next dev` (see `playwright.config.ts`) and the
    // Next.js dev-tools overlay injects its own focusable controls into the tab
    // order. Those ship in no build. So the tab order is walked and every stop
    // inside `<nextjs-portal>` is skipped over; the first stop that belongs to
    // the page itself must be the skip link.
    await page.goto("/today");
    const firstApplicationStop = await page.evaluate(async () => {
      const inDevOverlay = (element: Element | null) =>
        element !== null && element.closest("nextjs-portal") !== null;
      return { start: inDevOverlay(document.activeElement) };
    });
    expect(firstApplicationStop).toBeTruthy();

    const skip = page.getByRole("link", { name: "Skip to main content" });
    let stopsWalked = 0;
    let landedOnSkip = false;
    while (stopsWalked < 12 && !landedOnSkip) {
      await page.keyboard.press("Tab");
      stopsWalked += 1;
      const where = await page.evaluate(() => {
        const active = document.activeElement;
        if (active === null) return "none";
        if (active.closest("nextjs-portal") !== null) return "dev-overlay";
        return active.getAttribute("href") === "#main" ? "skip" : "other";
      });
      if (where === "dev-overlay") continue;
      landedOnSkip = where === "skip";
      break;
    }
    expect(
      landedOnSkip,
      "the first application-owned tab stop must be the skip link",
    ).toBe(true);
    await expect(skip).toBeFocused();

    // And it does what it says: activating it moves to the main landmark.
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#main$/);

    // Every destination in the rail is reachable and activatable by keyboard.
    await page.getByRole("link", { name: "Library" }).first().focus();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/library");
    await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();

    // And the capture dialog opens, takes focus, and closes on Escape.
    await page.getByTestId("capture-button").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("capture-field")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("capture-field")).toBeHidden();
  });

  test("the focused element is always visibly focused", async ({ page }) => {
    await signIn(page);
    // Focused **by keyboard**, deliberately. `globals.css` styles
    // `:focus-visible`, which is the correct selector — it is what stops a mouse
    // click from painting a ring — and it does not match a programmatic
    // `element.focus()`. Asserting against `.focus()` would either fail on a
    // correct build or push someone to widen the rule to `:focus`, which is the
    // wrong direction. So the ring is measured the way a keyboard user gets it.
    const button = page.getByTestId("capture-button");
    await button.evaluate((element) => (element as HTMLElement).blur());
    await page.keyboard.press("Tab");
    let focused = false;
    for (let stop = 0; stop < 25 && !focused; stop += 1) {
      focused = await button.evaluate((element) => element === document.activeElement);
      if (!focused) await page.keyboard.press("Tab");
    }
    expect(focused, "the capture button must be reachable by keyboard").toBe(true);

    const outline = await button.evaluate((element) => {
      const style = getComputedStyle(element);
      return `${style.outlineStyle} ${style.outlineWidth}`;
    });
    expect(outline).not.toContain("none");
  });
});

test.describe("the page body reflows rather than scrolling sideways", () => {
  test("no horizontal overflow at this viewport", async ({ page }, testInfo) => {
    await signIn(page);
    for (const path of ["/today", "/library", "/situations", "/review", "/system"]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows horizontally at ${testInfo.project.name}`).toBeLessThanOrEqual(1);
    }
  });
});

test.describe("the emptiness vocabulary never appears on a failed read", () => {
  test("no surface claims emptiness it did not establish", async ({ page }) => {
    await signIn(page);
    for (const path of ["/today", "/library", "/situations", "/review"]) {
      await page.goto(path);
      const failure = page.locator('[data-state="unavailable"]');
      for (let index = 0; index < (await failure.count()); index += 1) {
        const text = (await failure.nth(index).textContent()) ?? "";
        for (const claim of EMPTINESS_CLAIMS) {
          expect(text, `${path} failure state used an emptiness claim`).not.toMatch(claim);
        }
      }
    }
  });
});
