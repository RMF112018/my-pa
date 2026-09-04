import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("Intelligence is a working surface over seeded report artifacts", async ({ page }) => {
  test.setTimeout(180_000);

  await page.goto("/intelligence");
  await expect(page.getByRole("heading", { name: "Intelligence", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "History" })).toBeVisible();
  await expect(page.getByTestId("intelligence-unavailable")).toHaveCount(0);
  await expect(page.getByTestId("intelligence-listing")).toBeVisible();

  const listed = page.getByTestId("intelligence-report").first();
  await expect(listed).toBeVisible();
  await expect(listed).toContainText("E2E morning brief collector");
  await expect(listed).not.toContainText("scraped item one");
  await expect(page.locator("[data-testid='brief-item']")).toHaveCount(0);
  await expect(page.getByText(/task from brief/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);

  const readiness = page.getByTestId("intelligence-readiness");
  if (await readiness.count()) {
    await expect(readiness).toBeVisible();
    await expect(page.getByTestId("intelligence-readiness-not-health")).toContainText(
      /not a claim that the system is healthy/i,
    );
    const members = page.getByTestId("intelligence-readiness-member");
    if (await members.count()) {
      await expect(members.first()).toBeVisible();
      const states = await page.getByTestId("intelligence-readiness-member-state").allTextContents();
      expect(states.some((state) => state !== "READY")).toBe(true);
    }
  }

  await listed.getByRole("link").click();
  await expect(page).toHaveURL(/\/intelligence\/reports\/rpt_/);
  await expect(page.getByTestId("intelligence-report-detail")).toBeVisible();
  await expect(page.getByTestId("intelligence-body-markdown")).toContainText("scraped item one");
  await expect(page.locator("[data-testid='brief-item']")).toHaveCount(0);
  await expect(page.getByText(/task from brief/i)).toHaveCount(0);

  const structured = page.getByTestId("intelligence-structured");
  await structured.locator("summary").click();
  await expect(page.getByTestId("intelligence-structured-present")).toContainText(
    /not a Brief section\/item schema/i,
  );
  await expect(page.getByTestId("intelligence-structured-keys")).toContainText("lane");
  await expect(page.getByTestId("intelligence-structured-keys")).toContainText("marker");
  await expect(page.getByTestId("intelligence-structured-present")).not.toContainText(
    "scraped item one",
  );

  const provenance = page.getByTestId("intelligence-provenance");
  await provenance.locator("summary").click();
  await expect(provenance).toContainText(/Report-level provenance|provenance refs/i);

  await page.goto("/intelligence");
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/intelligence\/history/);
  await expect(page.getByRole("heading", { name: "Intelligence history", level: 1 })).toBeVisible();
  await expect(page.getByTestId("intelligence-history")).toBeVisible();
  await expect(page.getByText("E2E morning brief collector")).toBeVisible();
  await expect(page.getByTestId("intelligence-history")).not.toContainText("scraped item one");
});
