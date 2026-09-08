/**
 * The queue: append-only, bounded, principal-bound, and encrypted at rest.
 *
 * These run against the real `queue.ts` over a real IndexedDB
 * (`fake-indexeddb`), so the append-only claim is checked by reading the store
 * rather than by reading the code. Every note is obviously synthetic.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { EVENT_STORE, PAYLOAD_STORE, openOfflineDatabase, request, transactionDone } from "@/lib/offline/db";
import { principalContentKey } from "@/lib/offline/key";
import {
  MAX_QUEUED_ENTRIES,
  MAX_QUEUED_BYTES,
  MAX_REPLAY_ATTEMPTS,
  OfflineQueueFullError,
  countStates,
  deleteReplayed,
  deleteHeldByUser,
  enqueueCapture,
  foldEntries,
  markNeedsReauth,
  markReplayFailed,
  quarantineEntry,
  quarantineForeignEntries,
  releaseQuarantined,
  queueSnapshot,
  readPayloadText,
} from "@/lib/offline/queue";

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";

async function fresh() {
  globalThis.indexedDB = new IDBFactory();
  const db = await openOfflineDatabase();
  return { db, key: await principalContentKey(db, PRINCIPAL_A) };
}

async function rawEvents(db: IDBDatabase): Promise<Record<string, unknown>[]> {
  const tx = db.transaction(EVENT_STORE, "readonly");
  const all = (await request(tx.objectStore(EVENT_STORE).getAll())) as Record<string, unknown>[];
  await transactionDone(tx).catch(() => undefined);
  return all;
}

async function rawPayload(db: IDBDatabase, entryId: string): Promise<Record<string, unknown> | undefined> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = (await request(tx.objectStore(PAYLOAD_STORE).get(entryId))) as
    | Record<string, unknown>
    | undefined;
  await transactionDone(tx).catch(() => undefined);
  return record;
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

describe("what is written at rest", () => {
  it("stores ciphertext and never the note text", async () => {
    const { db, key } = await fresh();
    const note = "synthetic note alpha about a synthetic meeting";
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: note,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0001",
    });

    const payload = await rawPayload(db, entry.entryId);
    expect(payload).toBeDefined();
    const bytes = new Uint8Array(payload!.ciphertext as ArrayBuffer);
    const asText = new TextDecoder().decode(bytes);
    expect(asText).not.toContain("synthetic note alpha");
    expect(JSON.stringify(await rawEvents(db))).not.toContain("synthetic note alpha");

    await expect(readPayloadText(db, key, entry.entryId)).resolves.toBe(note);
  });

  it("binds the entry to the principal that queued it, in the enqueued event", async () => {
    const { db, key } = await fresh();
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note beta",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0002",
    });
    const events = await rawEvents(db);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "enqueued",
      entryId: entry.entryId,
      principalId: PRINCIPAL_A,
      idempotencyKey: "cap-synthetic-0002",
    });
  });
});

describe("the log is append-only and no entry is rewritten", () => {
  it("leaves the enqueued event byte-identical through every transition", async () => {
    const { db, key } = await fresh();
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note gamma",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0003",
    });
    const before = JSON.stringify((await rawEvents(db))[0]);

    await markReplayFailed(db, entry.entryId, "http_503");
    await markNeedsReauth(db, entry.entryId, "session refused with 401");
    await quarantineEntry(db, entry.entryId, "a different principal is signed in");

    const events = await rawEvents(db);
    expect(events).toHaveLength(4);
    const enqueued = events.find((event) => event.type === "enqueued");
    expect(JSON.stringify(enqueued)).toBe(before);

    const folded = (await queueSnapshot(db))[0];
    expect(folded.principalId).toBe(PRINCIPAL_A);
    expect(folded.idempotencyKey).toBe("cap-synthetic-0003");
    expect(folded.state).toBe("quarantined");
  });

  it("keeps the payload until a receipt-verified deletion names a receipt", async () => {
    const { db, key } = await fresh();
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note delta",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0004",
    });
    await markReplayFailed(db, entry.entryId, "http_500");
    expect(await rawPayload(db, entry.entryId)).toBeDefined();

    await deleteReplayed(db, entry.entryId, "rcpt-synthetic-0001");
    expect(await rawPayload(db, entry.entryId)).toBeUndefined();
    const events = await rawEvents(db);
    expect(events.at(-1)).toMatchObject({
      type: "payload_deleted",
      receiptId: "rcpt-synthetic-0001",
    });
    expect((await queueSnapshot(db))[0].state).toBe("replayed");
  });
});

describe("the fold", () => {
  it("stalls an entry after the bounded number of attempts rather than retrying forever", async () => {
    const { db, key } = await fresh();
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note epsilon",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0005",
    });
    for (let attempt = 0; attempt < MAX_REPLAY_ATTEMPTS - 1; attempt += 1) {
      await markReplayFailed(db, entry.entryId, "http_500");
    }
    expect((await queueSnapshot(db))[0].state).toBe("pending");
    await markReplayFailed(db, entry.entryId, "http_500");
    const stalled = (await queueSnapshot(db))[0];
    expect(stalled.state).toBe("stalled");
    expect(stalled.attemptCount).toBe(MAX_REPLAY_ATTEMPTS);
  });

  it("treats a payload deletion as terminal", () => {
    const folded = foldEntries([
      {
        seq: 1,
        entryId: "oq-1",
        type: "enqueued",
        at: 1,
        principalId: PRINCIPAL_A,
        idempotencyKey: "cap-synthetic-0006",
        captureKind: "quick_note",
        byteLength: 10,
      },
      { seq: 2, entryId: "oq-1", type: "payload_deleted", at: 2, receiptId: "rcpt-synthetic-0002" },
      { seq: 3, entryId: "oq-1", type: "replay_failed", at: 3, reason: "http_500" },
    ]);
    expect(folded[0].state).toBe("replayed");
  });
});

describe("the bound refuses; it never evicts", () => {
  it("refuses the enqueue at the entry limit and keeps every held note", async () => {
    const { db, key } = await fresh();
    for (let index = 0; index < MAX_QUEUED_ENTRIES; index += 1) {
      await enqueueCapture(db, key, {
        principalId: PRINCIPAL_A,
        text: `synthetic note ${index}`,
        captureKind: "quick_note",
        idempotencyKey: `cap-synthetic-bound-${index}`,
      });
    }
    const before = await queueSnapshot(db);
    expect(before).toHaveLength(MAX_QUEUED_ENTRIES);

    await expect(
      enqueueCapture(db, key, {
        principalId: PRINCIPAL_A,
        text: "synthetic note over the bound",
        captureKind: "quick_note",
        idempotencyKey: "cap-synthetic-bound-over",
      }),
    ).rejects.toBeInstanceOf(OfflineQueueFullError);

    const after = await queueSnapshot(db);
    expect(after).toHaveLength(MAX_QUEUED_ENTRIES);
    // The oldest is still the oldest: nothing was evicted to make room.
    expect(after[0].entryId).toBe(before[0].entryId);
    expect(after.map((entry) => entry.idempotencyKey)).toEqual(
      before.map((entry) => entry.idempotencyKey),
    );
  });

  it("refuses the enqueue at the byte limit", async () => {
    const { db, key } = await fresh();
    // Two notes just over half the byte bound each: the second is refused.
    const half = "s".repeat(Math.floor(MAX_QUEUED_BYTES / 2) + 1);
    await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: half,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-bytes-1",
    });
    await expect(
      enqueueCapture(db, key, {
        principalId: PRINCIPAL_A,
        text: half,
        captureKind: "quick_note",
        idempotencyKey: "cap-synthetic-bytes-2",
      }),
    ).rejects.toMatchObject({ name: "OfflineQueueFullError", bound: "bytes" });
    expect(await queueSnapshot(db)).toHaveLength(1);
  });
});

describe("an account switch quarantines rather than replays, deletes, or rebinds", () => {
  it("quarantines the other principal's entries and touches nothing of the caller's", async () => {
    const { db, key } = await fresh();
    const keyB = await principalContentKey(db, PRINCIPAL_B);
    const mine = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note owned by a",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-a",
    });
    const theirs = await enqueueCapture(db, keyB, {
      principalId: PRINCIPAL_B,
      text: "synthetic note owned by b",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-b",
    });

    const quarantined = await quarantineForeignEntries(db, PRINCIPAL_A);
    expect(quarantined).toBe(1);

    const entries = await queueSnapshot(db);
    const a = entries.find((entry) => entry.entryId === mine.entryId)!;
    const b = entries.find((entry) => entry.entryId === theirs.entryId)!;
    expect(a.state).toBe("pending");
    expect(b.state).toBe("quarantined");
    // Never rebound, never deleted.
    expect(b.principalId).toBe(PRINCIPAL_B);
    expect(await rawPayload(db, theirs.entryId)).toBeDefined();
    expect(countStates(entries)).toMatchObject({ pending: 1, quarantined: 1 });
  });

  it("is idempotent — a second pass quarantines nothing further", async () => {
    const { db } = await fresh();
    const keyB = await principalContentKey(db, PRINCIPAL_B);
    await enqueueCapture(db, keyB, {
      principalId: PRINCIPAL_B,
      text: "synthetic note owned by b",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-b2",
    });
    expect(await quarantineForeignEntries(db, PRINCIPAL_A)).toBe(1);
    expect(await quarantineForeignEntries(db, PRINCIPAL_A)).toBe(0);
  });

  it("lets only the owning principal explicitly release the retained note", async () => {
    const { db } = await fresh();
    const keyB = await principalContentKey(db, PRINCIPAL_B);
    const entry = await enqueueCapture(db, keyB, {
      principalId: PRINCIPAL_B,
      text: "synthetic note released by b",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-b3",
    });
    await quarantineForeignEntries(db, PRINCIPAL_A);
    await expect(releaseQuarantined(db, entry.entryId, PRINCIPAL_A)).rejects.toThrow(
      /owning principal/,
    );
    await releaseQuarantined(db, entry.entryId, PRINCIPAL_B);
    expect((await queueSnapshot(db))[0]).toMatchObject({
      principalId: PRINCIPAL_B,
      state: "pending",
    });
    expect(await rawPayload(db, entry.entryId)).toBeDefined();
  });

  it("lets only the owning principal explicitly delete the local ciphertext", async () => {
    const { db, key } = await fresh();
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note deleted by a",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-a-delete",
    });
    await expect(deleteHeldByUser(db, entry.entryId, PRINCIPAL_B)).rejects.toThrow(
      /owning principal/,
    );
    expect(await rawPayload(db, entry.entryId)).toBeDefined();
    await deleteHeldByUser(db, entry.entryId, PRINCIPAL_A);
    expect(await rawPayload(db, entry.entryId)).toBeUndefined();
    expect((await queueSnapshot(db))[0].state).toBe("deleted");
    expect((await rawEvents(db)).at(-1)).toMatchObject({
      type: "user_deleted",
      principalId: PRINCIPAL_A,
    });
  });
});

describe("durability across a database reopen", () => {
  it("keeps ciphertext and the principal binding after close and reopen", async () => {
    const { db, key } = await fresh();
    const note = "synthetic note that must survive a reload";
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: note,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-reload",
    });
    db.close();

    const reopened = await openOfflineDatabase();
    const sameKey = await principalContentKey(reopened, PRINCIPAL_A);
    await expect(readPayloadText(reopened, sameKey, entry.entryId)).resolves.toBe(note);

    const payload = await rawPayload(reopened, entry.entryId);
    expect(payload).toBeDefined();
    const asText = new TextDecoder().decode(new Uint8Array(payload!.ciphertext as ArrayBuffer));
    expect(asText).not.toContain(note);
    expect(JSON.stringify(await rawEvents(reopened))).not.toContain(note);

    const folded = (await queueSnapshot(reopened))[0];
    expect(folded.principalId).toBe(PRINCIPAL_A);
    expect(folded.state).toBe("pending");
  });
});
