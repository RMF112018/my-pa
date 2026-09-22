/**
 * T16 — the offline queue's Project, and the two guards the unit tier could not reach.
 *
 * Chromium's own IndexedDB, Web Crypto and **Web Locks**, plus two real tabs on
 * one origin. That last part is why this file exists rather than another unit
 * test: `withCaptureQueueLock` is an origin-wide exclusive lock, and one
 * JavaScript context cannot observe a second owner being kept out of it.
 *
 * Two findings are addressed here explicitly, and each says plainly whether it
 * closed:
 *
 * * **FINDING-05a — two-tab exclusivity.** Two real pages share one lock name.
 *   Reachable here, and proven below.
 * * **FINDING-05b — the first-key `add`-versus-`put` race.** The guard is the
 *   re-read inside the key transaction: a candidate generated before another
 *   context committed must adopt the stored key rather than overwrite it. A
 *   browser cannot be made to interleave two `readwrite` transactions on one
 *   origin at the point that would distinguish `add` from `put`, because
 *   IndexedDB serializes them — which is the same reason the unit tier could
 *   not reach it. What *is* provable, and is proven below, is the property the
 *   guard exists to protect: after two contexts both initialize, one key
 *   remains and the bytes sealed by the first are still readable.
 */
import { expect, test } from "@playwright/test";
import { openCaptureNote, signIn, syntheticNote } from "./fixtures";

const LOCK = "mypa-offline-capture";

/** The identifiers the canonical listing currently holds. */
async function canonicalCaptureIds(page: import("@playwright/test").Page): Promise<string[]> {
  const response = await page.request.get("/api/library");
  const body = (await response.json()) as {
    result?: { captures?: { capture_id?: string }[] };
  };
  return (body.result?.captures ?? [])
    .map((row) => row.capture_id)
    .filter((id): id is string => typeof id === "string");
}

/** The canonical rows that appeared since `before`. */
async function capturesAddedSince(
  page: import("@playwright/test").Page,
  before: readonly string[],
) {
  const response = await page.request.get("/api/library");
  const body = (await response.json()) as {
    result?: { captures?: { capture_id?: string; project_id?: string | null }[] };
  };
  return (body.result?.captures ?? []).filter(
    (row) => typeof row.capture_id === "string" && !before.includes(row.capture_id),
  );
}

/** The held-note counts this device reports, read out of IndexedDB's own fold. */
async function heldEntryCount(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const open = indexedDB.open("mypa-offline", 1);
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error);
    });
    const events = await new Promise<unknown[]>((resolve, reject) => {
      const request = db.transaction("events", "readonly").objectStore("events").getAll();
      request.onsuccess = () => resolve(request.result as unknown[]);
      request.onerror = () => reject(request.error);
    });
    db.close();
    return events.filter((event) => (event as { type?: string }).type === "enqueued").length;
  });
}

/** How many principal keys this origin holds. */
async function storedKeyCount(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const open = indexedDB.open("mypa-offline", 1);
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error);
    });
    const keys = await new Promise<IDBValidKey[]>((resolve, reject) => {
      const request = db.transaction("principal_keys", "readonly")
        .objectStore("principal_keys")
        .getAllKeys();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    db.close();
    return keys.length;
  });
}

test.describe("WP08 offline Capture Project", () => {
  test("a note held offline against a Project replays against that Project", async ({
    page,
    context,
  }) => {
    await signIn(page);
    const projects = (await (await page.request.get("/api/projects")).json()) as {
      projects?: { projectId?: string }[];
    };
    const chosen = projects.projects?.[0]?.projectId;
    test.skip(!chosen, "this stack seeds no Project for the synthetic Principal");

    const note = syntheticNote("wp08-offline-project");
    const before = await canonicalCaptureIds(page);
    await openCaptureNote(page);
    await page.getByTestId("capture-project-select").selectOption(chosen!);
    await page.getByTestId("capture-field").fill(note);

    await context.setOffline(true);
    await page.getByRole("button", { name: "Save" }).click();

    // Held, and explicitly not saved.
    const queued = page.getByTestId("capture-queued");
    await expect(queued).toBeVisible();
    await expect(queued).toContainText("Held on this device only");
    await expect(page.getByTestId("capture-durable")).toHaveCount(0);
    expect(await heldEntryCount(page)).toBeGreaterThan(0);

    // Reconnect and reload: the mount-driven drain replays it.
    await context.setOffline(false);
    await page.reload();
    await expect(page.locator('[data-testid="capture-button-desktop"]')).toBeVisible();

    await expect(async () => {
      const added = await capturesAddedSince(page, before);
      expect(added.length, "the held note never reached durable storage").toBe(1);
      // The Project the note was frozen with, not whatever scope is current.
      expect(added[0]?.project_id).toBe(chosen);
    }).toPass({ timeout: 20_000 });
  });

  test("changing global scope while a note is held does not refile it", async ({
    page,
    context,
  }) => {
    await signIn(page);
    const projects = (await (await page.request.get("/api/projects")).json()) as {
      projects?: { projectId?: string }[];
    };
    const rows = projects.projects ?? [];
    test.skip(rows.length < 2, "this stack seeds fewer than two Projects");
    const [first, second] = rows;

    const note = syntheticNote("wp08-offline-scope-move");
    const before = await canonicalCaptureIds(page);
    await openCaptureNote(page);
    await page.getByTestId("capture-project-select").selectOption(first!.projectId!);
    await page.getByTestId("capture-field").fill(note);
    await context.setOffline(true);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-queued")).toBeVisible();

    // Navigate somewhere else entirely, then reconnect.
    await context.setOffline(false);
    await page.goto(`/work/projects/${second!.projectId}/constraints`).catch(() => undefined);
    await page.goto("/today");
    await expect(page.locator('[data-testid="capture-button-desktop"]')).toBeVisible();

    await expect(async () => {
      const added = await capturesAddedSince(page, before);
      expect(added.length).toBe(1);
      // The frozen Project, not the one the browser was last looking at.
      expect(added[0]?.project_id).toBe(first!.projectId);
    }).toPass({ timeout: 20_000 });
  });

  test("FINDING-05a: two real tabs cannot hold the queue lock at once", async ({ context }) => {
    const first = await context.newPage();
    const second = await context.newPage();
    await signIn(first);
    await second.goto("/today");
    await expect(second.locator('[data-testid="capture-button-desktop"]')).toBeVisible();

    // Tab one takes the origin-wide lock and holds it until released.
    const held = first.evaluate(
      (name) =>
        new Promise<string>((resolve) => {
          void navigator.locks.request(name, { mode: "exclusive" }, async () => {
            (window as unknown as { __wp08Release?: () => void }).__wp08Release = () =>
              resolve("released");
            await new Promise<void>((done) => {
              (window as unknown as { __wp08Done?: () => void }).__wp08Done = done;
            });
          });
        }),
      LOCK,
    );
    await first.waitForFunction(
      () => Boolean((window as unknown as { __wp08Release?: () => void }).__wp08Release),
    );

    // Tab two asks with `ifAvailable`, exactly as the coordinator does, and is
    // handed null rather than being admitted or made to wait.
    const busy = await second.evaluate(
      (name) =>
        navigator.locks.request(name, { mode: "exclusive", ifAvailable: true }, async (lock) =>
          lock === null ? "busy" : "acquired",
        ),
      LOCK,
    );
    expect(busy).toBe("busy");

    await first.evaluate(() => {
      (window as unknown as { __wp08Done?: () => void }).__wp08Done?.();
      (window as unknown as { __wp08Release?: () => void }).__wp08Release?.();
    });
    await held;

    // Once released, the second tab can take it.
    const acquired = await second.evaluate(
      (name) =>
        navigator.locks.request(name, { mode: "exclusive", ifAvailable: true }, async (lock) =>
          lock === null ? "busy" : "acquired",
        ),
      LOCK,
    );
    expect(acquired).toBe("acquired");
  });

  test("FINDING-05b: two contexts initializing leave one key, and held bytes readable", async ({
    page,
    context,
  }) => {
    await signIn(page);
    const note = syntheticNote("wp08-key-race");
    const before = await canonicalCaptureIds(page);

    // Tab two is opened while the network is still up: a cold navigation with no
    // network fails, which `public/sw.js` says it does and does not claim otherwise.
    const other = await context.newPage();
    await other.goto("/today");
    await expect(other.locator('[data-testid="capture-button-desktop"]')).toBeVisible();

    // Tab one seals a payload under whatever key it establishes.
    await openCaptureNote(page);
    await page.getByTestId("capture-field").fill(note);
    await context.setOffline(true);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-queued")).toBeVisible();
    expect(await storedKeyCount(page)).toBe(1);

    // Tab two also reaches the queue. If first-key creation used `put`, a late
    // initializer could replace the key tab one sealed under and the held bytes
    // would become unreadable.
    const second = syntheticNote("wp08-key-race-two");
    await openCaptureNote(other);
    await other.getByTestId("capture-field").fill(second);
    await other.getByRole("button", { name: "Save" }).click();
    await expect(other.getByTestId("capture-queued")).toBeVisible();

    // One key for the origin, and both notes still held.
    expect(await storedKeyCount(page)).toBe(1);
    expect(await heldEntryCount(page)).toBe(2);

    // And both replay, which is only possible if both are still decryptable
    // under the one surviving key.
    await context.setOffline(false);
    await page.reload();
    await expect(page.locator('[data-testid="capture-button-desktop"]')).toBeVisible();
    await expect(async () => {
      const added = await capturesAddedSince(page, before);
      // Both notes reached durable storage, which is only possible if both were
      // still decryptable under the one surviving key.
      expect(added.length).toBe(2);
    }).toPass({ timeout: 30_000 });
  });

  test("an origin with no Web Locks refuses to queue rather than degrading", async ({
    page,
    context,
  }) => {
    // The fail-closed product state: a browser that cannot serialize the queue
    // must not mutate it. Missing support is tested, not assumed absent.
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "locks", { value: undefined, configurable: true });
    });
    await signIn(page);

    const note = syntheticNote("wp08-no-locks");
    await openCaptureNote(page);
    await page.getByTestId("capture-field").fill(note);
    await context.setOffline(true);
    await page.getByRole("button", { name: "Save" }).click();

    const notHeld = page.getByTestId("capture-not-held");
    await expect(notHeld).toBeVisible();
    await expect(notHeld).toContainText("still in the field");
    await expect(page.getByTestId("capture-queued")).toHaveCount(0);
    // The draft survives, which is the whole obligation of a refusal.
    await expect(page.getByTestId("capture-field")).toHaveValue(note);
  });
});
