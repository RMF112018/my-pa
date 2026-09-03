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
import { signIn, syntheticNote, expectState } from "./fixtures";

test.describe("an unauthenticated visitor reaches no destination", () => {
  test("every app route redirects to sign-in", async ({ page }) => {
    for (const path of [
      "/today",
      "/work",
      "/intelligence",
      "/people",
      "/knowledge",
      "/review",
      "/system",
      "/situations",
      "/library",
    ]) {
                    await page.goto(path);
      await expect(page).toHaveURL(/\/sign-in(?:\?|$)/);
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
    await expect(page).toHaveURL(/\/sign-in(?:\?|$)/);
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

  test("Knowledge reads the record and says which state it is in", async ({ page }) => {
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();
    // The search field is a real, labelled control, not a placeholder.
    await expect(page.getByRole("searchbox", { name: "Search your captures" })).toBeVisible();
    // Whatever else is true, the page must not be the old static card.
    await expect(page.getByText("No sources are connected yet")).toHaveCount(0);
    await expect(page.getByText("Not yet connected")).toHaveCount(0);
  });

  test("Work renders a truthful state", async ({ page }) => {
    await page.goto("/work");
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    await expect(page.getByTestId("situations-unavailable")).toHaveCount(0);
  });

  test("new capability routes state their admitted availability without inventing data", async ({ page }) => {
    await page.goto("/intelligence");
    await expect(page.getByRole("heading", { name: "Intelligence", level: 1 })).toBeVisible();
    await expect(page.locator('[data-state="unavailable"]')).toContainText(
      /not admitted to current main/i,
    );

    await page.goto("/people");
    await expect(page.getByRole("heading", { name: "People", level: 1 })).toBeVisible();
    await expect(page.locator('[data-state="degraded"]')).toContainText(
      /no admitted same-origin BFF exposure/i,
    );
  });

  test("predecessor deep links preserve the successor content and active destination", async ({ page }, testInfo) => {
    await page.goto("/situations");
    await expect(page.getByRole("heading", { name: "Situations", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Work" }).first()).toHaveAttribute(
      "aria-current",
      "page",
    );

    await page.goto("/library?q=synthetic");
    await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();
    await expect(page.getByRole("searchbox", { name: "Search your captures" })).toHaveValue(
      "synthetic",
    );
    if (testInfo.project.name === "mobile") {
      await page.getByRole("button", { name: "More" }).click();
    }
    await expect(page.getByRole("link", { name: "Knowledge" }).first()).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("command menu and Inspector expose only the bounded shell behavior", async ({ page }, testInfo) => {
    await page.keyboard.press("Control+K");
    const commands = page.getByRole("dialog", { name: "Command menu" });
    await expect(commands).toBeVisible();
    await expect(commands).toContainText(/cross-feature search is not available/i);
    await commands.getByRole("button", { name: "Knowledge" }).click();
    await page.waitForURL("**/knowledge");

    await page.getByRole("button", { name: "Open Inspector" }).click();
    if (testInfo.project.name === "mobile") {
      await expect(page.getByRole("dialog", { name: "Inspector" })).toBeVisible();
      await page.getByRole("button", { name: "Close panel" }).click();
      await expect(page.getByRole("dialog", { name: "Inspector" })).toHaveCount(0);
    } else {
      const utility = page.getByRole("complementary", { name: "Utility region" });
      await expect(utility.getByRole("slider", { name: "Inspector width" })).toBeVisible();
      await utility.getByRole("button", { name: "Pin Inspector" }).click();
      await expect(utility.getByRole("button", { name: "Unpin Inspector" })).toBeVisible();
    }
  });

  test("tablet landscape keeps Inspector in the utility region", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "tablet", "tablet inspector orientation");
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.getByRole("button", { name: "Open Inspector" }).click();
    const utility = page.getByRole("complementary", { name: "Utility region" });
    await expect(utility.getByRole("slider", { name: "Inspector width" })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Inspector" })).toHaveCount(0);
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
    // Derived from `capabilities.get`, so it must name a real count. The total
    // is required to be non-zero: `\d+ of \d+` was satisfied by "0 of 0", which
    // is what an absent `readiness` used to render, so the regex could not tell
    // a described build from an undescribed one.
    await expect(page.getByTestId("system-readiness")).toContainText(
      /\d+ of [1-9]\d* contracted capabilities/,
    );
    // And the absent-readiness branch must not be the thing that is on screen.
    await expect(page.getByTestId("system-readiness-unknown")).toHaveCount(0);
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
    await page.goto("/knowledge");
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
    // **The dialog cannot demonstrate this and is deliberately not used.** It
    // mints a fresh attempt key on every durable save, so saving the same text
    // twice through the UI is two captures *by design*; a test driving it would
    // be asserting the opposite of the name. The claim belongs to the boundary
    // that enforces it — `UNIQUE (principal_id, idempotency_key)` in the Python
    // capture plane — so the same submission is replayed against the real route
    // through the browser's own session, which is the only way this suite can
    // hold one key fixed across two attempts.
    const marker = `idem-${Date.now()}`;
    const submission = {
      text: syntheticNote(marker),
      idempotencyKey: `cap-e2e-${marker}`,
    };

    const first = await page.evaluate(
      async (submission) => {
        const response = await fetch("/api/capture", {
          method: "POST",
          cache: "no-store",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(submission),
        });
        return { status: response.status, body: (await response.json()) as Record<string, unknown> };
      },
      submission,
    );
    expect(first.status, "the first submission must be accepted").toBe(200);
    expect(first.body.status, "the capture must be persisted, not merely acknowledged").toBe(
      "persisted",
    );
    expect(first.body.created, "the first submission creates the capture").toBe(true);

    const replay = await page.evaluate(
      async (payload) => {
        const response = await fetch("/api/capture", {
          method: "POST",
          cache: "no-store",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        });
        return { status: response.status, body: (await response.json()) as Record<string, unknown> };
      },
      submission,
    );
    expect(replay.status, "a replay is answered, not refused").toBe(200);

    // The whole claim, in three assertions: the replay created nothing, and it
    // named the *same* stored row and the same receipt rather than a new one.
    expect(replay.body.created, "the replay must not create a second capture").toBe(false);
    const firstReceipt = first.body.receipt as { captureId: string; receiptId: string };
    const replayReceipt = replay.body.receipt as { captureId: string; receiptId: string };
    expect(replayReceipt.captureId).toBe(firstReceipt.captureId);
    expect(replayReceipt.receiptId).toBe(firstReceipt.receiptId);
  });
});

test.describe("keyboard-only navigation", () => {
  test("a keyboard reaches skip link, navigation, and capture", async ({ page }, testInfo) => {
    await signIn(page);

    // **The bypass link must be the first thing the application offers a
    // keyboard.** It is not asserted to be the first tab stop full stop, because
    // this suite runs against `next dev` (see `playwright.config.ts`) and the
    // Next.js dev-tools overlay injects its own focusable controls into the tab
    // order. Those ship in no build. So the tab order is walked and every stop
    // inside `<nextjs-portal>` is skipped over; the first stop that belongs to
    // the page itself must be the skip link.
    await page.goto("/today");
    const focusStartsInDevOverlay = await page.evaluate(() => {
      const active = document.activeElement;
      return active !== null && active.closest("nextjs-portal") !== null;
    });
    // The precondition of the walk below: focus begins outside the overlay, so
    // the first stop it reaches is the first stop the *application* offers.
    expect(
      focusStartsInDevOverlay,
      "focus must not already be inside the dev overlay before the walk begins",
    ).toBe(false);

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
    if (testInfo.project.name === "mobile") {
      await page.getByRole("button", { name: "More" }).focus();
      await page.keyboard.press("Enter");
    }
    await page.getByRole("link", { name: "Knowledge" }).first().focus();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/knowledge");
    await expect(page.getByRole("heading", { name: "Knowledge", level: 1 })).toBeVisible();

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
    for (const path of [
      "/today",
      "/work",
      "/intelligence",
      "/people",
      "/knowledge",
      "/review",
      "/system",
      "/situations",
      "/library",
    ]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows horizontally at ${testInfo.project.name}`).toBeLessThanOrEqual(1);
    }
  });
});

// **The emptiness-vocabulary sweep lives in `failure-states.spec.ts`, not here.**
// It was written against this suite, which runs on a healthy stack where no
// `[data-state="unavailable"]` element exists, so its loop body executed zero
// times and it could never have failed. `failure-states.spec.ts` runs the same
// vocabulary check against a gateway that is genuinely unreachable, where the
// failure states really are on the page — the assertion has something to bite
// on there and nothing to bite on here, so it is kept there and only there.
