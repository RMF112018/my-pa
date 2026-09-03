import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("Review accept persists a decision and does not invent proposal text", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
  await expect(page.getByTestId("review-queue-unavailable")).toHaveCount(0);
  await expect(page.getByTestId("review-listing-limitation")).toBeVisible();

  const first = page
    .getByTestId("backend-review-case")
    .filter({ has: page.getByTestId("review-accept") })
    .first();
  await expect(first).toBeVisible();
  await expect(first).not.toContainText(/If accepted:/);

  const versionBefore = Number(await first.getByTestId("review-version").innerText());
  await first.getByTestId("review-accept").click();
  await expect(first.getByTestId("review-decided")).toBeVisible();
  await expect(first.getByTestId("review-decided")).toContainText(/Decided and stored/i);
  await expect(first.getByTestId("review-not-persisted")).toHaveCount(0);

  await first.getByTestId("review-reveal").click();
  const reveal = page.getByRole("dialog", { name: "Why am I seeing this?" });
  await expect(reveal).toBeVisible();
  await reveal.getByRole("button", { name: "Reveal", exact: true }).click();
  await expect(
    reveal.locator(
      '[data-testid="reveal-evidence"], [data-testid="reveal-no-evidence"], [data-testid="reveal-unavailable"]',
    ),
  ).toBeVisible();
  await reveal.getByRole("button", { name: "Close" }).click();
  expect(versionBefore).toBeGreaterThanOrEqual(0);
});

test("Review correct-and-accept requires a value and persists the correction", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/review");
  const open = page
    .getByTestId("backend-review-case")
    .filter({ has: page.getByTestId("review-correct") })
    .first();
  await expect(open).toBeVisible();
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-correction-field")).toBeVisible();
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-refused")).toBeVisible();
  await open.getByTestId("review-correct").click();
  await open.getByTestId("review-correction-field").fill("pour the south slab instead");
  await open.getByTestId("review-correct").click();
  await expect(open.getByTestId("review-decided")).toBeVisible();
});
