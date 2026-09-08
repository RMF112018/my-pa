/**
 * The offline queue, exercised in a real browser for the first time.
 *
 * WP-08 built the encrypted device queue, the replay, and the service worker,
 * and every claim about them so far has been a unit or integration claim: a fake
 * IndexedDB, a stubbed `fetch`, a service worker driven as a module rather than
 * installed by a browser. §31 has owed a real exercise of this path since, and
 * this file is it — Chromium's own IndexedDB, Chromium's own Web Crypto,
 * Chromium's own offline switch, and Chromium's own `online` event.
 *
 * The sequence is the one that matters:
 *
 * 1. go offline for real (`context.setOffline(true)`, which fails the request at
 *    the network layer exactly as a lost connection does);
 * 2. capture a note — the dialog must say **held on this device only**, and must
 *    not say saved, because nothing on the server knows the note exists;
 * 3. come back online and reload, which is the mount-driven drain;
 * 4. the queue empties, and the note is readable back from the Library, which is
 *    the only proof that replay reached durable storage rather than merely
 *    deleting the local copy.
 *
 * Step 4 is what distinguishes a replay from a data loss, and it is why this
 * spec runs against the live gateway rather than a stub.
 *
 * **Two things this file deliberately does not do, both because the product does
 * not do them.**
 *
 * *It does not reload while offline.* The service worker caches static assets
 * and never documents, so a cold navigation with no network fails — which is
 * what `public/sw.js` says in its own docstring ("this does not make the app
 * start offline, and it does not claim to"). A test that reloaded offline would
 * be testing a promise nobody made; Chromium answers `ERR_INTERNET_DISCONNECTED`
 * and it is right to.
 *
 * *It does not assert the held-count badge appears the instant a note is
 * queued.* `OfflineQueueStatus` recomputes its counts on mount and on `online`,
 * and the capture dialog does not notify it, so a note queued into an
 * already-mounted page leaves the badge showing its previous (empty) state until
 * the next drain. That is a gap in the *secondary* indicator and it is recorded
 * as one rather than asserted away — the *primary* statement, in the dialog the
 * person is looking at, is correct and is asserted below.
 */
import { test, expect } from "@playwright/test";
import { signIn, syntheticNote } from "./fixtures";

test.describe("offline capture and reconnect", () => {
  test("a note captured offline is held, then replayed, then durable", async ({
    page,
    context,
  }) => {
    await signIn(page);

    // **Counted before, counted after.** "The Library shows a capture" would
    // pass on a capture some earlier test made, which would let a replay that
    // silently dropped the note look identical to one that stored it. The
    // increment is the proof; the presence of a row is not.
    await page.goto("/library");
    await expect(page.getByTestId("library-listing").or(page.getByTestId("library-empty"))).toBeVisible();
    const before = await page.getByTestId("library-capture").count();

    const marker = `offline-${Date.now()}`;
    await page.goto("/today");
    await context.setOffline(true);

    await page.getByTestId("capture-button").click();
    await page.getByTestId("capture-field").fill(syntheticNote(marker));
    await page.getByRole("button", { name: "Save" }).click();

    // **Held, and never called saved.** The device holds the only copy.
    const queued = page.getByTestId("capture-queued");
    await expect(queued).toBeVisible({ timeout: 30_000 });
    await expect(queued).toContainText(/Held on this device only/i);
    await expect(queued).toContainText(/not saved on the server/i);
    await expect(page.getByTestId("capture-durable")).toHaveCount(0);
    await expect(page.getByTestId("capture-acknowledged")).toHaveCount(0);

    // The note really is on this device: it is in IndexedDB, not in component
    // state, and it is stored encrypted rather than in the clear.
    const stored = await page.evaluate(async (plaintext) => {
      const names = await indexedDB.databases();
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const open = indexedDB.open("mypa-offline", 1);
        open.onsuccess = () => resolve(open.result);
        open.onerror = () => reject(open.error ?? new Error("offline db missing"));
      });
      const events = await new Promise<unknown[]>((resolve, reject) => {
        const req = db.transaction("events", "readonly").objectStore("events").getAll();
        req.onsuccess = () => resolve(req.result as unknown[]);
        req.onerror = () => reject(req.error ?? new Error("events unread"));
      });
      const payloads = await new Promise<Array<{ ciphertext?: ArrayBuffer }>>((resolve, reject) => {
        const req = db.transaction("payloads", "readonly").objectStore("payloads").getAll();
        req.onsuccess = () => resolve(req.result as Array<{ ciphertext?: ArrayBuffer }>);
        req.onerror = () => reject(req.error ?? new Error("payloads unread"));
      });
      db.close();
      const ciphertexts = payloads.map((record) =>
        record.ciphertext ? new TextDecoder().decode(new Uint8Array(record.ciphertext)) : "",
      );
      return {
        names: names.map((entry) => entry.name ?? ""),
        eventContainsNote: JSON.stringify(events).includes(plaintext),
        payloadCount: payloads.length,
        ciphertextContainsNote: ciphertexts.some((text) => text.includes(plaintext)),
      };
    }, syntheticNote(marker));
    expect(stored.names.some((name) => name.includes("mypa"))).toBe(true);
    expect(stored.payloadCount, "the held note must occupy the payload store").toBeGreaterThan(0);
    expect(stored.eventContainsNote, "the append-only log must not hold plaintext").toBe(false);
    expect(stored.ciphertextContainsNote, "payload bytes must be ciphertext").toBe(false);

    // Reconnect, then reload: replay runs on mount as well as on `online`, and a
    // reload exercises the path a person actually takes after a dropout.
    await context.setOffline(false);
    await page.reload();

    // The queue empties only once the server's own receipt has been checked —
    // `lib/offline/replay.ts` deletes the local copy after, never before.
    await expect(page.getByTestId("offline-queue-status")).toHaveCount(0, { timeout: 40_000 });

    // And the note is now readable back through a different capability, as one
    // more row than there was. This is the assertion that separates a replay
    // from a discard: the local copy is gone either way, and only the count says
    // where it went.
    await expect(async () => {
      await page.goto("/library");
      await expect(page.getByTestId("library-listing")).toBeVisible({ timeout: 20_000 });
      expect(await page.getByTestId("library-capture").count()).toBe(before + 1);
    }).toPass({ timeout: 40_000 });
  });

  test("a held note is announced as held and not as a count of filed notes", async ({
    page,
    context,
  }) => {
    await signIn(page);
    await context.setOffline(true);

    await page.getByTestId("capture-button").click();
    await page.getByTestId("capture-field").fill(syntheticNote(`wording-${Date.now()}`));
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-queued")).toBeVisible({ timeout: 30_000 });

    // The whole hazard of an offline queue is a person reading "held" as
    // "filed". Every sentence on the held path is checked for the opposite
    // claim, and the outcome is announced rather than merely drawn.
    const text = (await page.getByTestId("capture-queued").textContent()) ?? "";
    expect(text).not.toMatch(/\bsaved\b(?!\s+on the server)/i);
    expect(text).toMatch(/only copy/i);
    await expect(page.getByTestId("capture-queued")).toHaveAttribute("role", "status");

    // Coming back online must not leave the note stranded.
    await context.setOffline(false);
    await page.reload();
    await expect(page.getByTestId("offline-queue-status")).toHaveCount(0, { timeout: 40_000 });
  });

  test("System reports held-queue counts as this-browser observations", async ({ page }) => {
    await signIn(page);
    await page.goto("/system");
    await expect(page.getByTestId("system-pwa-this-browser")).toBeVisible();
    await expect(page.getByTestId("system-pwa-queue")).toBeVisible();
    await expect(page.getByTestId("system-pwa-queue")).toContainText(/this browser/i);
    await expect(page.getByTestId("system-pwa-queue")).toContainText(/not the server/i);
    await expect(page.getByTestId("system-pwa-limits")).toContainText(/cold start/i);
    await expect(page.getByTestId("system-pwa-client-side")).not.toContainText(
      "PWA_FIELDS_PENDING_WP26",
    );
  });

  // Principal switching is not constructible in this e2e stack (`D-15` admits
  // one Principal). The unit negatives live in `lib/offline/replay.test.ts` and
  // `lib/offline/queue.test.ts`; do not add a flaky two-identity browser test.
});
