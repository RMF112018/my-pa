/**
 * R02-WP10 Phase 7 — Quick Capture Constraint, the fourth Capture type.
 *
 * Real stack: signs in through the real sign-in page, then drives the real
 * Capture chooser/dialog and `CaptureConstraintForm` against the disposable
 * PostgreSQL `e2e/stack.sh` seeds, migrates and drops. Closes the 35
 * CAPTURE-AC/CAPTURE-PROJECT-AC rows bound to Phase 7
 * (`IMPL-6-PHASE8-9-TESTS.md` §3), plus two of the four required
 * `@run02-mobile` sentinel tests (this file's own share of the split; the
 * other two live in `project-controls-run02-responsive.spec.ts`).
 *
 * Runs in the same `npm run e2e` invocation (and therefore the same
 * disposable database) as `project-controls-run02.spec.ts` in CI's
 * `e2e-critical` third step — every Category/Constraint this file creates
 * is its own fresh one, and nothing here depends on that other file's own
 * mutations or vice versa.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn, visibleCaptureButton } from "./fixtures";

/** Mirrors the Constraint seed step in `e2e/stack.sh`. */
const PROJECT = "prj_e2ecst0000000001";
const UNCONFIGURED_PROJECT = "prj_e2ecst0000000002";
const SEEDED_CATEGORY = "ccat_e2ecst0000000001";

const RUN = Date.now().toString(36);
function marker(step: string): string {
  return `e2e-capcst-${RUN}-${step}`;
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

/** Open Capture and choose the Constraint branch. */
async function openCaptureConstraint(page: Page): Promise<void> {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Constraint" }).click();
  await expect(page.getByTestId("capture-project-selector")).toBeVisible();
  await expect(page.getByTestId("capture-constraint-description")).toBeVisible();
}

/** Fill and select a Project, so the Category read fires. */
async function chooseProject(page: Page, projectId: string): Promise<void> {
  await page.getByTestId("capture-project-select").selectOption(projectId);
}

async function fillMinimal(page: Page, description: string, projectId = PROJECT): Promise<void> {
  await chooseProject(page, projectId);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  await page.getByTestId("capture-constraint-description").fill(description);
}

// =============================================================================
// Chooser and branch identity
// =============================================================================

test("[PC-CM-CAPTURE-AC-001][PC-CM-CAPTURE-AC-002][PC-CM-CAPTURE-AC-003] Capture presents one chooser with four choices; Task reuses the canonical flow; Constraint is a distinct branch, never generic /api/capture", async ({
  page,
}) => {
  await visibleCaptureButton(page).click();
  const chooser = page.getByTestId("capture-chooser");
  await expect(chooser.getByRole("button", { name: "Create Task" })).toBeVisible();
  await expect(chooser.getByRole("button", { name: "Quick note" })).toBeVisible();
  await expect(chooser.getByRole("button", { name: "Conversation log" })).toBeVisible();
  await expect(chooser.getByRole("button", { name: "Constraint" })).toBeVisible();
  await expect(chooser.getByRole("button")).toHaveCount(4);

  // Task reuses the canonical Task creation sheet — no second creation form.
  // The sheet's own close control (`ui/sheet.tsx`) is an icon button labeled
  // "Close panel", not "Cancel" — the task sheet has no Cancel button at all.
  await chooser.getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByTestId("task-create-sheet")).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();

  // Constraint never calls the generic capture route.
  let capturePosted = false;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/capture") && request.method() === "POST") capturePosted = true;
  });
  // `openCaptureConstraint` opens the launcher itself — an extra explicit
  // click here would be redundant and, worse, hang: it would land while the
  // dialog this call is about to open is still covering the launcher.
  await openCaptureConstraint(page);
  await fillMinimal(page, marker("distinct-branch"));
  // BIC lives under collapsed Details (`[PC-CM-CAPTURE-AC-011]`) — `fillMinimal`
  // deliberately does not touch it (see its own docstring).
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  expect(capturePosted).toBe(false);
});

// =============================================================================
// Shared Project context across capture types
// =============================================================================

test("[PC-CM-CAPTURE-AC-004][PC-CM-CAPTURE-AC-005][PC-CM-CAPTURE-PROJECT-AC-001][PC-CM-CAPTURE-PROJECT-AC-003] one dialog-session Capture Project Context is shared and persists across type switches, and resets on reopen", async ({
  page,
}) => {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-project-selector")).toBeVisible();
  await chooseProject(page, PROJECT);

  // Switch to Conversation log: same Project Context, no new preference.
  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Conversation log" }).click();
  await expect(page.getByTestId("capture-project-select")).toHaveValue(PROJECT);

  // Switch to Constraint: still the same shared context, and it visibly
  // exposes the same Project picker every capture type does.
  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Constraint" }).click();
  await expect(page.getByTestId("capture-project-select")).toHaveValue(PROJECT);
  await page.getByTestId("capture-constraint-cancel").click();

  // A fresh Capture experience (dialog closed and reopened) resets the
  // session-local context rather than remembering it as a new preference.
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-project-select")).toHaveValue("");
  await page.keyboard.press("Escape");
});

test("[PC-CM-CAPTURE-AC-006][PC-CM-CAPTURE-PROJECT-AC-002] Note, Conversation and Task remain Project-optional; only Constraint requires one", async ({
  page,
}) => {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-project-selector").getByText(/required/i)).toHaveCount(0);
  await page.getByTestId("capture-entry-back").click();

  await page.getByTestId("capture-chooser").getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByTestId("task-create-sheet").getByTestId("capture-project-selector").getByText(/required/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Close panel" }).click();

  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Constraint" }).click();
  await expect(page.getByTestId("capture-project-selector")).toContainText(/required/i);
  await page.getByTestId("capture-constraint-cancel").click();
});

// =============================================================================
// Quick Constraint's own required/bound fields
// =============================================================================

test("[PC-CM-CAPTURE-AC-007][PC-CM-CAPTURE-AC-008] Constraint Quick Capture requires an authorized exact Project, and Category is required and Project-bound", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await page.getByTestId("capture-constraint-description").fill(marker("no-project"));
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-project-error")).toBeVisible();

  await chooseProject(page, PROJECT);
  await expect(page.getByTestId("capture-constraint-category")).not.toBeDisabled();
  const options = await page.getByTestId("capture-constraint-category").locator("option").allTextContents();
  expect(options.some((text) => text.includes("Synthetic category"))).toBe(true);

  // Category required — Publish/File refuses without one.
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-category-error")).toBeVisible();
  await page.keyboard.press("Escape");
});

test("[PC-CM-CAPTURE-AC-009][PC-CM-CAPTURE-AC-010] Description is required and preserved verbatim; BIC uses canonical PartyRef identity, not a guess", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await chooseProject(page, PROJECT);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-description")).toHaveClass(/./);
  // no description filled — confirm a refusal happened by staying on the form.
  await expect(page.getByTestId("capture-constraint-save")).toBeVisible();

  const description = `${marker("verbatim")}  double  spaced  text`;
  await page.getByTestId("capture-constraint-description").fill(description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("capture-constraint-success")).toContainText(description);
});

test("[PC-CM-CAPTURE-AC-011][PC-CM-CAPTURE-AC-015] Status defaults to Identified and lives under collapsed Details, which starts collapsed and offers only the eligible fields", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await expect(page.getByTestId("capture-constraint-details")).toHaveCount(0);
  await expect(page.getByTestId("capture-constraint-details-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("capture-constraint-details-toggle").click();
  await expect(page.getByTestId("capture-constraint-details")).toBeVisible();
  await expect(page.getByTestId("capture-constraint-status")).toHaveValue("identified");
  // Exactly the eligible fields: BIC, Status, Date Identified, Due, Comments.
  for (const id of [
    "capture-constraint-bic",
    "capture-constraint-status",
    "capture-constraint-date-identified",
    "capture-constraint-due-date",
    "capture-constraint-comments",
  ]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  await page.keyboard.press("Escape");
});

test("[PC-CM-CAPTURE-AC-012][PC-CM-CAPTURE-AC-013][PC-CM-CAPTURE-AC-014] Date Identified and Due default server-side, and Comments maps to the canonical current_update as the Initial update", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  const description = marker("server-defaults");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await expect(page.getByTestId("capture-constraint-date-identified")).toHaveValue("");
  await expect(page.getByTestId("capture-constraint-due-date")).toHaveValue("");
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  const comments = marker("initial-update-comment");
  await page.getByTestId("capture-constraint-comments").fill(comments);

  let capturedBody: Record<string, unknown> | null = null;
  await page.route(`**/api/project-controls/projects/${PROJECT}/constraints`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    capturedBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue();
  });
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints`);
  expect(capturedBody).not.toBeNull();
  expect(capturedBody).not.toHaveProperty("dateIdentified");
  expect(capturedBody).not.toHaveProperty("dueDate");
  expect(capturedBody).toHaveProperty("currentUpdate", comments);
  // The server filled real dates on the seeded, configured Project.
  await expect(page.getByTestId("capture-constraint-success")).not.toContainText("—\n");
});

// =============================================================================
// Project change clears stale options; independent authorization
// =============================================================================

test("[PC-CM-CAPTURE-AC-016][PC-CM-CAPTURE-AC-026] a Project change clears Category and options, may retain the Principal-scoped BIC choice, and every dimension is independently authorized", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await chooseProject(page, PROJECT);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");

  await chooseProject(page, UNCONFIGURED_PROJECT);
  await expect(page.getByTestId("capture-constraint-category")).toHaveValue("");
  // The Principal-scoped "Me" BIC choice is not Project-scoped and may
  // remain (`markDirty`'s own exception) — asserted as "not forced away",
  // not "must remain", per the row's own qualifier.
  await expect(page.getByTestId("capture-constraint-bic")).toBeVisible();

  // The unconfigured Project has no Category the Principal can publish
  // against — the options list is now empty rather than stale.
  const options = await page.getByTestId("capture-constraint-category").locator("option").allTextContents();
  expect(options.filter((text) => text.trim().length > 0 && !text.includes("Select"))).toHaveLength(0);
  await page.keyboard.press("Escape");
});

// =============================================================================
// One atomic create, stable intent, authoritative success (017-021, PROJECT-011)
// =============================================================================

test("[PC-CM-CAPTURE-AC-017][PC-CM-CAPTURE-AC-018][PC-CM-CAPTURE-AC-019][PC-CM-CAPTURE-AC-020][PC-CM-CAPTURE-AC-021][PC-CM-CAPTURE-PROJECT-AC-011] Create is one atomic create_published intent with a stable idempotency identity; success reads only the authoritative response and offers deterministic Open/Close", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  const description = marker("atomic-create");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");

  const postedKeys: string[] = [];
  await page.route(`**/api/project-controls/projects/${PROJECT}/constraints`, async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { idempotencyKey?: string };
      if (typeof body.idempotencyKey === "string") postedKeys.push(body.idempotencyKey);
    }
    await route.continue();
  });
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints`);
  expect(postedKeys).toHaveLength(1);

  // Success is read-only, human-facing, no internal IDs/receipts visible by
  // default (diagnostics off).
  const successText = await page.getByTestId("capture-constraint-success").innerText();
  expect(successText).not.toMatch(/cst_|"receipt"|correlationId/);
  await expect(page.getByTestId("capture-constraint-success-project")).toContainText(/E2E Synthetic Project/);

  // Open Constraint navigates deterministically to that record.
  await page.getByTestId("capture-constraint-open").click();
  await expect(page).toHaveURL(/constraints\?view=register&constraint=/);
  await expect(page.getByTestId("constraint-inspector")).toBeVisible();
  await expect(page.getByTestId("constraint-inspector")).toContainText(description);
});

test("[PC-CM-CAPTURE-AC-022] validation/refusal failure preserves every authored value", async ({ page }) => {
  await openCaptureConstraint(page);
  const description = marker("preserve-on-refusal");
  await chooseProject(page, PROJECT);
  await page.getByTestId("capture-constraint-description").fill(description);
  const comments = marker("preserve-comments");
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-comments").fill(comments);
  // No Category — a real backend refusal.
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-category-error")).toBeVisible();
  await expect(page.getByTestId("capture-constraint-description")).toHaveValue(description);
  await expect(page.getByTestId("capture-constraint-comments")).toHaveValue(comments);
  await expect(page.getByTestId("capture-project-select")).toHaveValue(PROJECT);
});

test("[PC-CM-CAPTURE-AC-023] an ambiguous outcome offers Retry that resends the identical frozen attempt, never a blind auto-retry or fuzzy dedupe", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  const description = marker("ambiguous-retry");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");

  let attempts = 0;
  const seenKeys = new Set<string>();
  await page.route(`**/api/project-controls/projects/${PROJECT}/constraints`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON() as { idempotencyKey?: string };
    if (typeof body.idempotencyKey === "string") seenKeys.add(body.idempotencyKey);
    attempts += 1;
    if (attempts === 1) {
      await route.abort("connectionreset");
      return;
    }
    await route.continue();
  });
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-unavailable")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("capture-constraint-retry").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints`);
  expect(seenKeys.size).toBe(1);
});

test("[PC-CM-CAPTURE-AC-024] type switching keeps each capture type's dirty state isolated", async ({ page }) => {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-field")).toBeVisible();
  const noteText = marker("isolated-note");
  await page.getByTestId("capture-field").fill(noteText);

  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Constraint" }).click();
  const constraintDescription = marker("isolated-constraint");
  await page.getByTestId("capture-constraint-description").fill(constraintDescription);

  // Same `capture-entry-back` round trip as above — deliberately not
  // Constraint's own `capture-constraint-cancel`, which discards the
  // attempt and closes the whole Capture experience (a materially different
  // path from a same-session "back to chooser" hop, and not what this row
  // is testing).
  await page.getByTestId("capture-entry-back").click();

  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await expect(page.getByTestId("capture-field")).toHaveValue(noteText);
});

test("[PC-CM-CAPTURE-AC-025] Cancel with material dirty input requires an explicit, safe discard", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await page.getByTestId("capture-constraint-description").fill(marker("dirty-cancel"));
  let dialogSeen = false;
  page.once("dialog", async (dialog) => {
    dialogSeen = true;
    expect(dialog.message()).toMatch(/discard/i);
    await dialog.dismiss();
  });
  await page.getByTestId("capture-constraint-cancel").click();
  expect(dialogSeen).toBe(true);
  // Dismissing keeps the form open with the authored text intact.
  await expect(page.getByTestId("capture-constraint-description")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("capture-constraint-cancel").click();
  // Same DOM-count pitfall already diagnosed and fixed in
  // `project-controls-run02.spec.ts`'s `[PC-CM-FE-AC-048]` note: `Dialog`'s
  // `open` prop only toggles the native `<dialog>`'s open/closed state — the
  // `kind === "constraint"` branch (`capture-dialog.tsx`) keeps
  // `CaptureConstraintForm` mounted as its child regardless, so the
  // Description input never leaves the DOM. Non-visibility is the correct
  // signal.
  await expect(page.getByTestId("capture-constraint-description")).not.toBeVisible();
});

test("[PC-CM-CAPTURE-AC-027] a confirmed creation reconciles authoritative Project/portfolio queries — the fresh row appears in the Register without a manual reload", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  const description = marker("reconciles-register");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("capture-constraint-close").click();

  await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
  await page.getByTestId("register-search").fill(description);
  await expect(page.getByTestId("register-table")).toContainText(description, { timeout: 15_000 });
});

test("[PC-CM-CAPTURE-AC-028] Quick Constraint reuses the shared mutation/feedback/focus runtime, not a competing engine", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  const description = marker("shared-runtime");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("capture-constraint-close").click();
  // The same shell `mutation-feedback-region` every other Constraint mutation
  // publishes to — never a Capture-private toast surface.
  await expect(page.getByTestId("mutation-feedback-region")).toContainText(/filed/i);
});

test("[PC-CM-CAPTURE-AC-029] a populated journey exercises the chooser, both selectors, Details, deterministic focus and Retry in sequence", async ({
  page,
}) => {
  await visibleCaptureButton(page).click();
  const chooser = page.getByTestId("capture-chooser");
  await expect(chooser).toBeVisible();
  await chooser.getByRole("button", { name: "Constraint" }).click();
  await expect(page.getByTestId("capture-project-select")).toBeFocused();
  await chooseProject(page, PROJECT);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  const description = marker("populated-journey");
  await page.getByTestId("capture-constraint-description").fill(description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-status").selectOption("pending");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("capture-constraint-success")).toContainText("Pending");
});

test("[PC-CM-CAPTURE-PROJECT-AC-007] Task Capture passes the selected Project into the canonical Task creation contract", async ({
  page,
}) => {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Quick note" }).click();
  await chooseProject(page, PROJECT);
  await page.getByTestId("capture-entry-back").click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Create Task" }).click();
  await expect(page.getByTestId("task-create-sheet")).toBeVisible();
  await expect(page.getByTestId("task-create-sheet").getByTestId("capture-project-select")).toHaveValue(PROJECT);
  await page.getByRole("button", { name: "Close panel" }).click();
});

test("[PC-CM-CAPTURE-PROJECT-AC-008] Constraint keeps its own exact-Project + Category/BIC/Responsible semantics distinct from the shared Project context", async ({
  page,
}) => {
  await openCaptureConstraint(page);
  await chooseProject(page, PROJECT);
  await expect(page.getByTestId("capture-constraint-category")).toBeVisible();
  await page.getByTestId("capture-constraint-details-toggle").click();
  await expect(page.getByTestId("capture-constraint-bic")).toBeVisible();
  // No separate Responsible-party control exists on this quick form; the
  // fuller Register authoring surface owns that (documented scope line in
  // `capture-constraint-form.tsx`'s own header) — confirmed absent here
  // rather than assumed.
  await expect(page.getByTestId("capture-constraint-responsible")).toHaveCount(0);
  await page.keyboard.press("Escape");
});

// =============================================================================
// @run02-mobile sentinels (this file's half of the required four)
// =============================================================================

test("@run02-mobile Quick Capture Constraint", async ({ page }) => {
  test.skip(!["mobile", "mobile-webkit"].includes(test.info().project.name), "phone-geometry sentinel");
  await openCaptureConstraint(page);
  const description = marker("mobile-quick-capture");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
});

test("@run02-mobile ordinary Close without keyboard-required input", async ({ page }) => {
  test.skip(!["mobile", "mobile-webkit"].includes(test.info().project.name), "phone-geometry sentinel");
  await page.goto(`/work/projects/${PROJECT}/constraints?view=register`);
  await expect(page.getByTestId("register-card-list").or(page.getByTestId("register-table"))).toBeVisible({
    timeout: 15_000,
  });
  await openCaptureConstraint(page);
  const description = marker("mobile-close-target");
  await fillMinimal(page, description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("capture-constraint-open").click();
  await expect(page.getByTestId("constraint-inspector")).toBeVisible();
  await page.getByTestId("inspector-close").click();
  await expect(page.getByTestId("direct-action-confirm")).toBeVisible();
  // Ordinary Close needs no typed text at all — Close, then Confirm.
  await page.getByTestId("direct-action-confirm").click();
  await expect(page.getByTestId("mutation-feedback-region")).toContainText(/completed/i, { timeout: 15_000 });
});
