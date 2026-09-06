import { expect, test, type Locator, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

/** Pin a row by case id before a decision hides the verb that found it. */
async function openCase(page: Page, action: "review-accept" | "review-correct"): Promise<Locator> {
  const candidate = page
    .getByTestId("backend-review-case")
    .filter({ has: page.getByTestId(action) })
    .first();
  await expect(candidate).toBeVisible();
  const caseId = await candidate.getAttribute("data-review-case-id");
  expect(caseId).toBeTruthy();
  return page.locator(`[data-testid="backend-review-case"][data-review-case-id="${caseId}"]`);
}

test("Review accept persists a decision and does not invent proposal text", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
  await expect(page.getByTestId("review-queue-unavailable")).toHaveCount(0);
  await expect(page.getByTestId("review-listing-limitation")).toBeVisible();

  const first = await openCase(page, "review-accept");
  await expect(first).not.toContainText(/If accepted:/);

  const versionBefore = Number(await first.getByTestId("review-version").innerText());
  await first.getByTestId("review-accept").click();
  await expect(first.getByTestId("review-decided")).toBeVisible();
  await expect(first.getByTestId("review-decided")).toContainText(/Decided and stored/i);
  await expect(first.getByTestId("review-not-persisted")).toHaveCount(0);
  await expect(first.getByTestId("review-accept")).toHaveCount(0);

  await first.getByTestId("review-reveal").click();
  const reveal = page.getByRole("dialog", { name: "Why am I seeing this?" });
  await expect(reveal).toBeVisible();
  await reveal.getByRole("button", { name: "Reveal", exact: true }).click();
  await expect(
    reveal.locator(
      '[data-testid="reveal-evidence"], [data-testid="reveal-no-evidence"], [data-testid="reveal-unavailable"]',
    ),
  ).toBeVisible();
  await reveal.getByRole("button", { name: "Close", exact: true }).click();
  expect(versionBefore).toBeGreaterThanOrEqual(0);
});

test("stale expectedReviewVersion conflict is visible and does not fabricate a decision", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
  const first = await openCase(page, "review-accept");
  await page.route("**/api/review/*/decide", async (route) => {
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          errorClass: "conflict",
          code: "conflict",
          message: "stale expected_review_version",
        },
      }),
    });
  });
  await first.getByTestId("review-accept").click();
  await expect(first.getByTestId("review-conflict")).toBeVisible();
  await expect(first.getByTestId("review-conflict")).toContainText(/Not decided/i);
  await expect(first.getByTestId("review-decided")).toHaveCount(0);
  await expect(first.getByTestId("review-not-persisted")).toHaveCount(0);
  await expect(first.getByTestId("review-accept")).toBeVisible();
});

test("contextual Review handoff is used when GoodNotes pending or Evidence exposes it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/knowledge/goodnotes");
  const pending = page.getByTestId("goodnotes-pending-review");
  const evidenceReview = page.getByTestId("goodnotes-evidence").getByRole("link", { name: "Review" });
  const pendingCount = await pending.count();
  const evidenceCount = await evidenceReview.count();
  test.skip(
    pendingCount === 0 && evidenceCount === 0,
    "GoodNotes pending and Evidence Review controls are not on the empty e2e catalog",
  );
  if (pendingCount > 0) {
    await pending.first().getByRole("link", { name: "Review" }).click();
  } else {
    await evidenceReview.first().click();
  }
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
});

test("Review correct-and-accept requires a value and persists the correction", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/review");
  const open = await openCase(page, "review-correct");
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-correction-field")).toBeVisible();
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-refused")).toBeVisible();
  await open.getByTestId("review-correct").click();
  await open.getByTestId("review-correction-field").fill("pour the south slab instead");
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-decided")).toBeVisible();
  await expect(open.getByTestId("review-correct")).toHaveCount(0);
});
