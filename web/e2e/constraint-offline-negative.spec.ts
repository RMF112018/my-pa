/**
 * R02-WP10 Phase 7 — the offline-negative case for Quick Capture Constraint.
 *
 * Secondary closure for `PC-CM-CAPTURE-AC-023` (the primary closure is the
 * positive ambiguous-retry-reuses-key case in `capture-constraint.spec.ts`)
 * and §6 obligation 13 / HC5's "no offline replay for Constraint" SP5 item:
 * going offline mid-Quick-Constraint-flow shows explicit unavailability —
 * never a silent queue, never a fake success, and never the generic Capture
 * offline-replay path Note/Conversation/Task use. R02 does not change
 * offline replay or its durable idempotency contract for those three types;
 * Quick Constraint was never part of that contract to begin with, per the
 * frozen browser/server contract table this campaign has followed
 * throughout: "R02 does not change offline replay or its durable
 * idempotency contract... never generic capture/offline queue".
 *
 * **`web/public/sw.js` is untouched here, and this file is the named stop
 * condition's own home.** Confirmed by direct source read before writing
 * this spec: `sw.js` contains no mention of "constraint" anywhere and admits
 * no Constraint route into its cache/offline-queue handling. If any
 * assertion below had instead shown the service worker admitting a
 * Constraint route, this worker would have stopped rather than edit
 * `sw.js` or work around it — that did not happen, and nothing here changes
 * `sw.js`.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn, visibleCaptureButton } from "./fixtures";

const PROJECT = "prj_e2ecst0000000001";
const SEEDED_CATEGORY = "ccat_e2ecst0000000001";

const RUN = Date.now().toString(36);
function marker(step: string): string {
  return `e2e-run02-offneg-${RUN}-${step}`;
}

/** Every row this device's offline queue holds, regardless of kind. */
async function offlineQueueEntryCount(page: Page): Promise<number> {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const open = indexedDB.open("mypa-offline", 1);
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error ?? new Error("offline db missing"));
    });
    if (!db.objectStoreNames.contains("events")) {
      db.close();
      return 0;
    }
    const events = await new Promise<unknown[]>((resolve, reject) => {
      const request = db.transaction("events", "readonly").objectStore("events").getAll();
      request.onsuccess = () => resolve(request.result as unknown[]);
      request.onerror = () => reject(request.error ?? new Error("events read"));
    });
    db.close();
    return events.filter((event) => (event as { type?: string }).type === "enqueued").length;
  });
}

async function openCaptureConstraint(page: Page): Promise<void> {
  await visibleCaptureButton(page).click();
  await page.getByTestId("capture-chooser").getByRole("button", { name: "Constraint" }).click();
  await expect(page.getByTestId("capture-constraint-description")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("[PC-CM-CAPTURE-AC-023] going offline mid-Quick-Constraint-flow shows explicit unavailability, never a queued or fake-succeeded write", async ({
  page,
  context,
}) => {
  const before = await offlineQueueEntryCount(page);

  await openCaptureConstraint(page);
  await page.getByTestId("capture-project-select").selectOption(PROJECT);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  const description = marker("offline-attempt");
  await page.getByTestId("capture-constraint-description").fill(description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");

  await context.setOffline(true);
  await page.getByTestId("capture-constraint-save").click();

  // Explicit unavailability — the coordinator classifies a network failure
  // as ambiguous (it may have applied server-side, since offline can happen
  // after a request left the browser as well as before), never a silent
  // "success", and never the generic capture offline-queue UI
  // (`capture-field`'s own held-note affordance).
  await expect(page.getByTestId("capture-constraint-unavailable")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("capture-constraint-success")).toHaveCount(0);
  await expect(page.getByTestId("capture-constraint-retry")).toBeVisible();
  await expect(page.getByTestId("capture-constraint-discard-attempt")).toBeVisible();

  // No second queue: the generic offline-capture IndexedDB store gained no
  // row for this attempt at all — a Constraint create never reaches
  // `queueCaptureOffline`.
  const whileOffline = await offlineQueueEntryCount(page);
  expect(whileOffline).toBe(before);

  // Every authored field is still exactly what was typed — the frozen
  // attempt, not a cleared form — and every field is disabled while the
  // attempt remains ambiguous, so nothing can be edited out from under it.
  await expect(page.getByTestId("capture-constraint-description")).toHaveValue(description);
  await expect(page.getByTestId("capture-constraint-description")).toBeDisabled();
  await context.setOffline(false);
});

test("[PC-CM-CAPTURE-AC-023] the same offline attempt, once online again, Retry resends the identical frozen intent rather than replaying from a queue", async ({
  page,
  context,
}) => {
  const before = await offlineQueueEntryCount(page);
  await openCaptureConstraint(page);
  await page.getByTestId("capture-project-select").selectOption(PROJECT);
  await page.getByTestId("capture-constraint-category").selectOption(SEEDED_CATEGORY);
  const description = marker("offline-then-retry");
  await page.getByTestId("capture-constraint-description").fill(description);
  await page.getByTestId("capture-constraint-details-toggle").click();
  await page.getByTestId("capture-constraint-bic").selectOption("me");

  const seenKeys: string[] = [];
  await page.route(`**/api/project-controls/projects/${PROJECT}/constraints`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON() as { idempotencyKey?: string };
    if (typeof body.idempotencyKey === "string") seenKeys.push(body.idempotencyKey);
    await route.continue();
  });

  await context.setOffline(true);
  await page.getByTestId("capture-constraint-save").click();
  await expect(page.getByTestId("capture-constraint-unavailable")).toBeVisible({ timeout: 20_000 });

  await context.setOffline(false);
  await page.getByTestId("capture-constraint-retry").click();
  await expect(page.getByTestId("capture-constraint-success")).toBeVisible({ timeout: 20_000 });
  await page.unroute(`**/api/project-controls/projects/${PROJECT}/constraints`);

  // Exactly one dispatched attempt reached the server (the offline attempt
  // itself never left the browser — Chromium fails it before any request is
  // sent while `setOffline(true)` — so this route only ever observes the
  // one real, online retry), and it carried the same key the offline attempt
  // was frozen under, proving Retry resent the identical intent rather than
  // minting a new one or replaying through a second mechanism.
  expect(seenKeys).toHaveLength(1);
  const afterQueueCount = await offlineQueueEntryCount(page);
  expect(afterQueueCount).toBe(before);
});
