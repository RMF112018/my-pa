/**
 * What a person sees when this device is still holding notes.
 *
 * Two properties, both surface-level:
 *
 * * held notes are counted and described as held **on this device only**, never
 *   as saved;
 * * an account switch shows a quarantined count rather than silently replaying,
 *   deleting, or hiding the other principal's notes.
 *
 * The queue, the keys, the fold and IndexedDB are real; only the network is
 * faked. Everything is synthetic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { openOfflineDatabase } from "@/lib/offline/db";
import { principalContentKey } from "@/lib/offline/key";
import { enqueueCapture, queueSnapshot } from "@/lib/offline/queue";
import { PAYLOAD_STORE, request, transactionDone } from "@/lib/offline/db";

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function queueFor(principalId: string, text: string, idempotencyKey: string) {
  const db = await openOfflineDatabase();
  const key = await principalContentKey(db, principalId);
  return enqueueCapture(db, key, { principalId, text, captureKind: "quick_note", idempotencyKey });
}

async function payloadPresent(entryId: string): Promise<boolean> {
  const db = await openOfflineDatabase();
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = await request(tx.objectStore(PAYLOAD_STORE).get(entryId));
  await transactionDone(tx).catch(() => undefined);
  return record !== undefined;
}

describe("held notes are counted and never described as saved", () => {
  it("says held on this device only", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note eta", "cap-synthetic-eta");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));

    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);

    const held = await screen.findByTestId("offline-queue-held");
    expect(held).toHaveTextContent("held on this device only");
    expect(held).toHaveTextContent("not saved on the server");
    expect(held.textContent).not.toMatch(/\bSaved\b/);
  });

  it("renders nothing when the queue is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));
    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await waitFor(() => expect(screen.queryByTestId("offline-queue-status")).toBeNull());
  });
});

describe("an account switch quarantines rather than replaying or deleting", () => {
  it("shows the other principal's notes as quarantined and never sends them", async () => {
    const theirs = await queueFor(PRINCIPAL_B, "synthetic note theta", "cap-synthetic-theta");
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);

    const quarantined = await screen.findByTestId("offline-queue-quarantined");
    expect(quarantined).toHaveTextContent("quarantined");
    expect(quarantined).toHaveTextContent("queued by a different account");
    // Never replayed.
    expect(fetchSpy).not.toHaveBeenCalled();
    // Never deleted, never rebound.
    expect(await payloadPresent(theirs.entryId)).toBe(true);
    const db = await openOfflineDatabase();
    const entries = await queueSnapshot(db);
    expect(entries[0]).toMatchObject({ principalId: PRINCIPAL_B, state: "quarantined" });
  });
});

describe("a queue that cannot be read is reported rather than shown as empty", () => {
  it("says so instead of rendering a silent zero", async () => {
    const globals = globalThis as { indexedDB?: IDBFactory };
    const real = globals.indexedDB;
    delete globals.indexedDB;
    try {
      render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
      const alert = await screen.findByTestId("offline-queue-failure");
      expect(alert).toHaveTextContent("could not be read on this device");
    } finally {
      globals.indexedDB = real;
    }
  });
});
