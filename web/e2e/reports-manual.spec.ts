/**
 * Reports Modernization WP07 (U8(d), RM-AC-019): the manual standalone Reports
 * UI over the real stack.
 *
 * Browser → the /reports pages → the same-origin /api/reports BFF routes (one
 * route, one capability) → the server-only gateway transport → `POST
 * /v1/reports.*` on the Python HTTP gateway → the same `ApplicationService`
 * handlers the remote MCP facade runs → the disposable PostgreSQL `e2e/stack.sh`
 * creates, migrates and drops. No fixture satisfies an assertion here; every
 * state shown is read back from the gateway.
 *
 * Journey: Standalone list → New report (markdown) → Publish → view → Edit
 * (title, reason) → version 2 → history shows two versions → Archive (confirm)
 * → the Archived filter lists it → Move to Trash → Trash lists it → Restore
 * (returns the prior state: archived) → Restore → active. A second test opens
 * Edit, bumps the version through the page's own BFF (a second writer), saves
 * in the first and sees the stale message with the draft kept.
 *
 * Titles carry a per-run stamp so a rerun against a reused database never
 * reads a previous run's report. The spec mutates only reports it publishes
 * itself; no seeded record is touched. Desktop project only.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

const RUN = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;

function title(step: string): string {
  return `E2E synthetic report ${step} ${RUN}`;
}

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the manual Reports journey runs on the desktop project");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

/** The report id in the current `/reports/grpt_…` URL. */
function reportIdOf(page: Page): string {
  const match = /\/reports\/(grpt_[A-Za-z0-9]+)/.exec(new URL(page.url()).pathname);
  expect(match, page.url()).not.toBeNull();
  return (match as RegExpExecArray)[1];
}

/** Run one lifecycle action from the report view through its confirm dialog. */
async function lifecycle(page: Page, action: "Archive" | "Move to Trash" | "Restore", reason?: string): Promise<void> {
  const actions = page.getByRole("region", { name: "Report actions" });
  await actions.getByRole("button", { name: action, exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  if (reason) await dialog.getByLabel("Reason (optional)").fill(reason);
  await dialog.getByRole("button", { name: action, exact: true }).click();
  await expect(page.getByTestId("report-action-feedback")).toContainText(`${action}: done.`);
}

/** The report view's "State" fact (the header badge says the same words). */
async function expectState(page: Page, words: "Active" | "Archived" | "In Trash"): Promise<void> {
  const facts = page.locator("dl[aria-label=\"Report details\"]");
  await expect(facts.getByRole("definition").filter({ hasText: new RegExp(`^${words}$`) })).toHaveCount(1);
}

/** A same-origin BFF call from inside the page, as the browser client makes it. */
async function bff(page: Page, path: string, document: Record<string, unknown>): Promise<{ status: number; body: Record<string, unknown> }> {
  return page.evaluate(
    async ({ target, payload }) => {
      const response = await fetch(target, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      return { status: response.status, body: (await response.json()) as Record<string, unknown> };
    },
    { target: path, payload: document },
  );
}

test("a standalone report is published, edited, archived, trashed and restored through the manual UI", async ({ page }) => {
  test.setTimeout(180_000);
  const original = title("journey");
  const revised = `${original} revised`;

  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Show")).toHaveValue("standalone");
  // No purge, hold, retention or permanent-delete control anywhere on the surface.
  await expect(page.getByRole("button", { name: /purge|hold|retention|permanently|empty trash/i })).toHaveCount(0);

  await page.getByRole("link", { name: "New report" }).click();
  await expect(page).toHaveURL(/\/reports\/new$/);
  const form = page.getByRole("form", { name: "New report" });
  await form.getByLabel(/^Title/).fill(original);
  await expect(form.getByLabel("Format")).toHaveValue("markdown");
  await form.getByLabel("Body").fill("# Synthetic\n\nE2E synthetic markdown body.");
  await form.getByLabel(/^Tags/).fill("e2e-synthetic");
  await form.getByRole("button", { name: "Publish" }).click();

  await expect(page).toHaveURL(/\/reports\/grpt_[A-Za-z0-9]+$/);
  const reportId = reportIdOf(page);
  const view = page.getByTestId("report-view");
  await expect(view.getByRole("heading", { name: original, level: 1 })).toBeVisible();
  await expect(view.getByText("E2E synthetic markdown body.")).toBeVisible();
  await expect(view.getByRole("definition").filter({ hasText: "1 of 1" })).toBeVisible();
  await expectState(page, "Active");

  await page.getByRole("region", { name: "Report actions" }).getByRole("link", { name: "Edit" }).click();
  await expect(page).toHaveURL(new RegExp(`/reports/${reportId}/edit$`));
  const edit = page.getByRole("form", { name: "Edit report" });
  await edit.getByLabel(/^Title/).fill(revised);
  await edit.getByLabel(/Reason for the change/).fill("E2E synthetic revision.");
  await edit.getByRole("button", { name: "Save" }).click();

  await expect(page).toHaveURL(new RegExp(`/reports/${reportId}$`));
  await expect(view.getByRole("heading", { name: revised, level: 1 })).toBeVisible();
  await expect(view.getByRole("definition").filter({ hasText: "2 of 2" })).toBeVisible();

  await page.getByRole("tab", { name: "History" }).click();
  const versions = page.getByRole("list", { name: "Version list" });
  await expect(versions.getByRole("listitem")).toHaveCount(2);
  await expect(versions).toContainText("Version 1");
  await expect(versions).toContainText("Version 2");
  await expect(versions).toContainText("Reason: E2E synthetic revision.");
  await page.getByRole("tab", { name: "Content" }).click();

  await lifecycle(page, "Archive", "E2E synthetic archive.");
  await expectState(page, "Archived");

  await page.goto("/reports");
  await page.getByLabel("State").selectOption("archived");
  const archivedList = page.getByRole("list", { name: "Reports" });
  await expect(archivedList.getByRole("link", { name: revised })).toBeVisible();

  await page.goto(`/reports/${reportId}`);
  await expect(view.getByRole("heading", { name: revised, level: 1 })).toBeVisible();
  await lifecycle(page, "Move to Trash");
  await expectState(page, "In Trash");

  await page.goto("/reports/trash");
  const trash = page.getByRole("list", { name: "Reports in Trash" });
  const trashed = trash.getByRole("listitem").filter({ has: page.getByRole("link", { name: revised }) });
  await expect(trashed).toBeVisible();
  await trashed.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByTestId("report-action-feedback")).toContainText(`Restored "${revised}".`);

  // Restore from Trash returns the state the delete left: archived.
  await page.goto(`/reports/${reportId}`);
  await expect(view.getByRole("heading", { name: revised, level: 1 })).toBeVisible();
  await expectState(page, "Archived");
  await lifecycle(page, "Restore");
  await expectState(page, "Active");

  await page.getByRole("tab", { name: "History" }).click();
  const events = page.getByRole("list", { name: "Lifecycle event list" });
  await expect(events.getByRole("listitem")).toHaveCount(4);
});

test("a save against a version another writer moved shows the stale message and keeps the draft", async ({ page }) => {
  test.setTimeout(120_000);
  const original = title("conflict");
  const published = await bff(page, "/api/reports", {
    title: original,
    content: { format: "markdown", body: "E2E synthetic conflict body." },
    idempotencyKey: `e2e-reports-${RUN}-publish`,
  });
  expect(published.status, JSON.stringify(published.body)).toBe(200);
  const reportId = String(published.body.report_id);
  expect(reportId).toMatch(/^grpt_/);

  await page.goto(`/reports/${reportId}/edit`);
  const edit = page.getByRole("form", { name: "Edit report" });
  const draftTitle = `${original} my draft`;
  await edit.getByLabel(/^Title/).fill(draftTitle);
  await edit.getByLabel(/Reason for the change/).fill("E2E synthetic draft.");

  // A second writer moves the head to version 2 after this editor loaded version 1.
  const bumped = await bff(page, `/api/reports/${reportId}/update`, {
    expectedVersion: 1,
    patch: { title: `${original} by another writer` },
    changeReason: "E2E synthetic concurrent edit.",
    idempotencyKey: `e2e-reports-${RUN}-bump`,
  });
  expect(bumped.status, JSON.stringify(bumped.body)).toBe(200);
  expect(bumped.body.version_number).toBe(2);

  await edit.getByRole("button", { name: "Save" }).click();
  const notice = page.getByTestId("report-edit-notice");
  await expect(notice).toHaveAttribute("data-kind", "stale");
  await expect(notice).toContainText("This report changed since you opened it (now version 2).");
  // Never overwritten, never auto-retried: the draft is still in the form.
  await expect(page).toHaveURL(new RegExp(`/reports/${reportId}/edit$`));
  await expect(edit.getByLabel(/^Title/)).toHaveValue(draftTitle);
  await expect(notice.getByRole("button", { name: "Review latest" })).toBeVisible();
});
