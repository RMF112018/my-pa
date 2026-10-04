import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

const taskCollection = (url: URL) => url.pathname === "/api/tasks";

async function createTask(page: Page, title: string): Promise<void> {
  await page.getByRole("button", { name: "New task" }).click();
  const sheet = page.getByTestId("task-create-sheet");
  await sheet.getByLabel("Title").fill(title);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) =>
      taskCollection(new URL(candidate.url())) && candidate.request().method() === "POST",
    ),
    sheet.getByRole("button", { name: "Create", exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(sheet).toHaveCount(0);
  await expect(page.getByRole("link", { name: new RegExp(title) })).toBeVisible();
}

async function revalidate(page: Page, status = 200): Promise<void> {
  const [response] = await Promise.all([
    page.waitForResponse((candidate) =>
      taskCollection(new URL(candidate.url())) && candidate.request().method() === "GET",
    ),
    page.evaluate(() => window.dispatchEvent(new Event("focus"))),
  ]);
  expect(response.status()).toBe(status);
}

async function expectControls(page: Page, marker: string, draft = marker): Promise<void> {
  await expect(page.getByRole("textbox", { name: "Search tasks" })).toHaveValue(draft);
  await expect(page.getByRole("combobox", { name: "Archive", exact: true })).toHaveValue("exclude");
  await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Work views" })).toHaveText("Unscheduled");
  const parameters = new URL(page.url()).searchParams;
  expect(parameters.get("q")).toBe(marker);
  expect(parameters.get("view")).toBe("unscheduled");
  expect(parameters.get("tz")).toBe("America/New_York");
}

test.describe("WP03 current Task compatibility", () => {
  let marker: string;
  let alpha: string;
  let beta: string;

  test.beforeEach(async ({ page }) => {
    marker = `wp03-${crypto.randomUUID()}`;
    alpha = `Synthetic ${marker} alpha`;
    beta = `Synthetic ${marker} beta`;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
    await page.goto(`/work?view=unscheduled&q=${marker}&tz=America%2FNew_York`);
    await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
    // Confirmed creates and all reads reach the established BFF/gateway/database.
    await createTask(page, alpha);
    await createTask(page, beta);
    await expect(page.locator("[data-work-item]")).toHaveCount(2);
  });

  test("WP03-DR-004 current list, search, archive filter and Work view stay functional", async ({ page }) => {
    const search = page.getByRole("textbox", { name: "Search tasks" });
    await search.fill(alpha);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByRole("link", { name: new RegExp(alpha) })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(beta) })).toHaveCount(0);
    await expect(page.locator("[data-work-item]")).toHaveCount(1);
    expect(new URL(page.url()).searchParams.get("q")).toBe(alpha);

    await page.getByText("Filters", { exact: true }).click();
    const archive = page.getByRole("combobox", { name: "Archive", exact: true });
    await archive.selectOption("only");
    await expect(page.locator('[data-state="empty"]')).toBeVisible();
    await expect(page.locator("[data-work-item]")).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get("archived")).toBe("only");
    await archive.selectOption("exclude");
    await expect(page.getByRole("link", { name: new RegExp(alpha) })).toBeVisible();
    await expect(page.locator("[data-work-item]")).toHaveCount(1);

    await page.getByRole("button", { name: "Work views" }).click();
    await page.getByRole("menuitem", { name: "All open", exact: true }).click();
    await expect(page.getByRole("link", { name: new RegExp(alpha) })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("view")).toBe("all-open");
    await expect(search).toHaveValue(alpha);
    await expect(archive).toHaveValue("exclude");
  });

  test("WP03-DR-004 WP03-DR-006 successful foreground revalidation preserves controls and selection", async ({ page }) => {
    await page.getByText("Filters", { exact: true }).click();
    const selection = page.getByRole("checkbox", { name: `Select ${alpha}`, exact: true });
    await selection.check();
    const draft = `${marker} unsubmitted draft`;
    await page.getByRole("textbox", { name: "Search tasks" }).fill(draft);

    await revalidate(page);

    await expectControls(page, marker, draft);
    await expect(selection).toBeChecked();
    await expect(page.getByRole("link", { name: new RegExp(alpha) })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(beta) })).toBeVisible();
    await expect(page.locator("[data-work-item]")).toHaveCount(2);
    await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
  });

  test("WP03-DR-004 WP03-DR-006 failed refresh retains confirmed rows and recovers without resetting controls", async ({ page }) => {
    await page.getByText("Filters", { exact: true }).click();
    const selection = page.getByRole("checkbox", { name: `Select ${alpha}`, exact: true });
    await selection.check();
    // Only failure injection is intercepted; successful reads remain real.
    await page.route(taskCollection, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "unavailable", message: "Synthetic refresh failure" } }),
      });
    });
    await revalidate(page, 503);
    await expect(page.getByTestId("mutation-feedback-region").getByText("Task updates are temporarily unavailable.")).toBeVisible();
    await expectControls(page, marker);
    await expect(selection).toBeChecked();
    await expect(page.getByRole("link", { name: new RegExp(alpha) })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(beta) })).toBeVisible();
    await expect(page.locator("[data-work-item]")).toHaveCount(2);
    await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
    await expect(page.getByText("Synthetic refresh failure", { exact: true })).toHaveCount(0);

    await page.unroute(taskCollection);
    await revalidate(page);
    await expectControls(page, marker);
    await expect(selection).toBeChecked();
    await expect(page.locator("[data-work-item]")).toHaveCount(2);
  });

  test("WP03-DR-004 current Task detail opens and closes with preserved Work URL and focus", async ({ page }) => {
    const trigger = page.getByRole("link", { name: new RegExp(alpha) });
    const workUrl = page.url();
    await trigger.click();
    const sheet = page.getByTestId("task-compact-sheet");
    await expect(sheet.getByRole("heading", { name: alpha, exact: true })).toBeVisible();
    await expect(page).toHaveURL(/task=tsk_/);
    const parameters = new URL(page.url()).searchParams;
    expect(parameters.get("q")).toBe(marker);
    expect(parameters.get("view")).toBe("unscheduled");
    expect(parameters.get("tz")).toBe("America/New_York");
    await page.getByRole("button", { name: "Close panel", exact: true }).click();
    await expect(sheet).toHaveCount(0);
    await expect(page).toHaveURL(workUrl);
    await expect(trigger).toBeFocused();
    await expect(page.locator("[data-work-item]")).toHaveCount(2);
  });
});
