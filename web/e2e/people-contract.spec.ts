import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("People search, profile, and resolve keep ambiguity visible", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/people");
  await expect(page.getByRole("heading", { name: "People", level: 1 })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search people" })).toBeVisible();
  await expect(page.getByText(/no admitted same-origin BFF exposure/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
  await expect(page.getByTestId("people-idle")).toBeVisible();

  await page.getByRole("searchbox", { name: "Search people" }).fill("Pat Synthetic");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("people-search-hits")).toBeVisible();
  await expect(page.getByRole("link", { name: "Pat Synthetic" })).toBeVisible();

  await page.getByRole("link", { name: "Pat Synthetic" }).click();
  await expect(page.getByTestId("people-profile")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pat Synthetic", level: 2 })).toBeVisible();

  await page.goto("/people");
  await page.getByLabel("Resolve a reference").fill("Alex Chen");
  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(page.getByTestId("people-resolve-outcome")).toBeVisible();
  await expect(page.getByTestId("people-resolve-outcome")).toContainText(/ambiguous/i);
  await expect(page.getByTestId("people-resolve-candidates")).toBeVisible();
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
});
