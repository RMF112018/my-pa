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
  await expect(page.getByTestId("people-search-hits")).toHaveCount(0);

  await page.getByRole("searchbox", { name: "Search people" }).fill("Pat Synthetic");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("people-search-hits")).toBeVisible();
  await expect(page.getByRole("link", { name: "Pat Synthetic" })).toBeVisible();

  await page.getByRole("link", { name: "Pat Synthetic" }).click();
  await expect(page).toHaveURL(/\/people\/ent_/);
  await expect(page).not.toHaveURL(/entityId=/);
  await expect(page.getByTestId("people-profile")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pat Synthetic", level: 1 })).toBeVisible();
  await expect(page.getByTestId("people-entity-id")).toBeVisible();
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /split|observe|author/i })).toHaveCount(0);
  if (await page.getByTestId("people-assignments-current").count()) {
    await expect(page.getByTestId("people-assignments-current")).toBeVisible();
  }
  if (await page.getByTestId("people-assignments-historical").count()) {
    await expect(page.getByTestId("people-assignments-historical")).toBeVisible();
  }

  const entityId = (await page.getByTestId("people-entity-id").textContent())?.trim() ?? "";
  expect(entityId).toMatch(/^ent_/);
  await page.goto(`/people?entityId=${encodeURIComponent(entityId)}`);
  await expect(page).toHaveURL(new RegExp(`/people/${entityId}$`));
  await expect(page.getByTestId("people-profile")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pat Synthetic", level: 1 })).toBeVisible();

  await page.goto("/people");
  await page.getByLabel("Resolve a reference").fill("Alex Chen");
  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(page.getByTestId("people-resolve-outcome")).toBeVisible();
  await expect(page.getByTestId("people-resolve-outcome")).toContainText(/ambiguous/i);
  await expect(page.getByTestId("people-resolve-candidates")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open profile" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
});

test("People search and profile reflow at a narrow viewport", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/people");
  await expect(page.getByRole("searchbox", { name: "Search people" })).toBeVisible();
  await expect(page.getByLabel("Resolve a reference")).toBeVisible();
  await page.getByRole("searchbox", { name: "Search people" }).fill("Pat Synthetic");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: "Pat Synthetic" }).click();
  await expect(page.getByTestId("people-profile")).toBeVisible();
  const profile = page.getByTestId("people-profile");
  const box = await profile.boundingBox();
  expect(box).not.toBeNull();
  expect(box && box.width).toBeLessThanOrEqual(375);

  await page.setViewportSize({ width: 1280, height: 720 });
  await expect(page.getByTestId("people-profile")).toBeVisible();
  await expect(page.getByTestId("people-entity-id")).toBeVisible();
});
