import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

async function api<T>(page: Page, pathName: string): Promise<ApiAnswer<T>> {
  return page.evaluate(async (target) => {
    const response = await fetch(target, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    return { status: response.status, body: (await response.json()) as T };
  }, pathName);
}

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

test("foreign entity_id is not_found with no existence leak and no merge control", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const foreign = "ent_bbbbbbbb22222222";
  const answer = await api<{ error?: { errorClass?: string; message?: string } }>(
    page,
    `/api/people/${foreign}`,
  );
  expect(answer.status).toBe(404);
  expect(answer.body.error?.errorClass).toBe("not_found");
  const serialized = JSON.stringify(answer.body);
  expect(serialized).not.toMatch(/exist/i);
  expect(serialized).not.toMatch(/another principal/i);
  expect(serialized).not.toMatch(/belongs to/i);

  await page.goto(`/people/${foreign}`);
  await expect(page.getByTestId("people-profile-unavailable")).toBeVisible();
  await expect(page.getByTestId("people-profile")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
  const copy = (await page.getByTestId("people-profile-unavailable").innerText()).toLowerCase();
  expect(copy).not.toMatch(/exist/);
  expect(copy).not.toMatch(/another principal/);
  expect(copy).not.toMatch(/belongs to/);
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
