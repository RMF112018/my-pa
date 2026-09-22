/**
 * T06 — the versioned queue: legacy rows, v2 rows, dedup and the bounds (C05/C06).
 *
 * The legacy fixtures below are written **directly into the stores** with the
 * historical shape — no version markers, raw sealed text, no additional data —
 * rather than through the new serializer. A fixture built by the code under test
 * would prove only that the code agrees with itself, and the claim being made
 * here is about bytes this codebase wrote in an earlier release.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import {
  EVENT_STORE,
  PAYLOAD_STORE,
  openOfflineDatabase,
  request,
  transactionDone,
} from "@/lib/offline/db";
import { getOrCreatePrincipalKey, seal } from "@/lib/offline/key";
import { CaptureQueueProtocolError } from "@/lib/offline/capture-intent-codec";
import {
  MAX_QUEUED_ENTRIES,
  OfflineQueueFullError,
  enqueueCapture,
  queueSnapshot,
  readCaptureIntent,
  readPayloadRecord,
  type OfflineEntry,
  type PayloadRecord,
} from "@/lib/offline/queue";

const PRINCIPAL_A = "syn-aaaa0001";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";
const NOTE = "synthetic note alpha";

let db: IDBDatabase;
let key: CryptoKey;

beforeEach(async () => {
  globalThis.indexedDB = new IDBFactory();
  db = await openOfflineDatabase();
  key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
});

/** Write a historical, unversioned entry exactly as the previous release did. */
async function seedLegacyEntry(
  entryId: string,
  text: string,
  idempotencyKey: string,
): Promise<void> {
  const sealed = await seal(key, text);
  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  tx.objectStore(EVENT_STORE).add({
    entryId,
    type: "enqueued",
    at: 1_700_000_000_000,
    principalId: PRINCIPAL_A,
    idempotencyKey,
    captureKind: "quick_note",
    byteLength: sealed.ciphertext.byteLength,
    // No `schemaVersion`. That absence is the marker.
  });
  tx.objectStore(PAYLOAD_STORE).add({
    entryId,
    iv: sealed.iv,
    ciphertext: sealed.ciphertext,
  });
  await transactionDone(tx);
}

async function rawPayload(entryId: string): Promise<PayloadRecord | undefined> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = (await request(tx.objectStore(PAYLOAD_STORE).get(entryId))) as
    | PayloadRecord
    | undefined;
  await transactionDone(tx).catch(() => undefined);
  return record;
}

async function rawEvents(): Promise<readonly Record<string, unknown>[]> {
  const tx = db.transaction(EVENT_STORE, "readonly");
  const events = (await request(tx.objectStore(EVENT_STORE).getAll())) as Record<string, unknown>[];
  await transactionDone(tx).catch(() => undefined);
  return events;
}

function bytesOf(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function entryOf(entries: readonly OfflineEntry[], entryId: string): OfflineEntry {
  const found = entries.find((entry) => entry.entryId === entryId);
  if (!found) throw new Error(`no entry ${entryId}`);
  return found;
}

describe("a v2 row carries its Project inside the ciphertext", () => {
  it("marks both records and reads the Project back after a reopen", async () => {
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: NOTE,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-v2",
      projectId: PROJECT_A,
    });
    expect(entry.schemaVersion).toBe(2);

    const events = await rawEvents();
    expect(events[0]).toMatchObject({ type: "enqueued", schemaVersion: 2 });
    const record = await rawPayload(entry.entryId);
    expect(record).toMatchObject({ schemaVersion: 2 });

    // The Project is not in the clear anywhere: not in the journal row, not
    // beside the ciphertext.
    expect(JSON.stringify(events)).not.toContain(PROJECT_A);
    expect(bytesOf(record!.ciphertext)).not.toContain(
      bytesOf(new TextEncoder().encode(PROJECT_A).buffer as ArrayBuffer),
    );

    const reopened = await openOfflineDatabase();
    const sameKey = await getOrCreatePrincipalKey(reopened, PRINCIPAL_A);
    const persisted = entryOf(await queueSnapshot(reopened), entry.entryId);
    const intent = await readCaptureIntent(
      reopened,
      sameKey,
      persisted,
      (await readPayloadRecord(reopened, entry.entryId))!,
    );
    expect(intent).toEqual({ version: "v2", text: NOTE, projectId: PROJECT_A });
  });

  it("stores an explicit No Project as null", async () => {
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: NOTE,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-none",
      projectId: null,
    });
    const intent = await readCaptureIntent(
      db,
      key,
      entryOf(await queueSnapshot(db), entry.entryId),
      (await readPayloadRecord(db, entry.entryId))!,
    );
    expect(intent.projectId).toBeNull();
  });
});

describe("historical rows stay historical", () => {
  it("reads a legacy row as No Project without rewriting its bytes", async () => {
    await seedLegacyEntry("oq-legacy-0001", "synthetic historical note", "cap-legacy-0001");
    const before = await rawPayload("oq-legacy-0001");
    const beforeBytes = bytesOf(before!.ciphertext);

    const entry = entryOf(await queueSnapshot(db), "oq-legacy-0001");
    expect(entry.schemaVersion).toBeUndefined();

    const intent = await readCaptureIntent(db, key, entry, before!);
    expect(intent).toEqual({
      version: "legacy",
      text: "synthetic historical note",
      projectId: null,
    });

    // Reading did not migrate, re-encrypt, or re-mark anything.
    const after = await rawPayload("oq-legacy-0001");
    expect(bytesOf(after!.ciphertext)).toBe(beforeBytes);
    expect(after).not.toHaveProperty("schemaVersion");
    expect((await rawEvents())[0]).not.toHaveProperty("schemaVersion");
  });

  it("does not infer a Project from a legacy payload that happens to contain one", async () => {
    // A historical row whose *text* mentions a Project identifier is still a
    // no-Project row. Plaintext is not authority.
    await seedLegacyEntry("oq-legacy-0002", `filed under ${PROJECT_A}`, "cap-legacy-0002");
    const entry = entryOf(await queueSnapshot(db), "oq-legacy-0002");
    const intent = await readCaptureIntent(db, key, entry, (await rawPayload("oq-legacy-0002"))!);
    expect(intent.projectId).toBeNull();
  });

  it("refuses a half-marked row rather than guessing which protocol it is", async () => {
    await seedLegacyEntry("oq-legacy-0003", "synthetic historical note", "cap-legacy-0003");
    // Strip nothing; add a marker to the payload only, as a partial write would.
    const record = await rawPayload("oq-legacy-0003");
    const tx = db.transaction(PAYLOAD_STORE, "readwrite");
    tx.objectStore(PAYLOAD_STORE).put({ ...record!, schemaVersion: 2 });
    await transactionDone(tx);

    const entry = entryOf(await queueSnapshot(db), "oq-legacy-0003");
    await expect(
      readCaptureIntent(db, key, entry, (await rawPayload("oq-legacy-0003"))!),
    ).rejects.toMatchObject({ reason: "unsupported_version" });
    // The bytes are still there.
    expect(await rawPayload("oq-legacy-0003")).toBeDefined();
  });

  it("refuses a v2 row whose markers were stripped to look legacy", async () => {
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: NOTE,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-downgrade",
      projectId: PROJECT_A,
    });
    const record = await rawPayload(entry.entryId);
    const tx = db.transaction(PAYLOAD_STORE, "readwrite");
    tx.objectStore(PAYLOAD_STORE).put({
      entryId: record!.entryId,
      iv: record!.iv,
      ciphertext: record!.ciphertext,
    });
    await transactionDone(tx);

    // The entry still says 2 and the payload no longer does: unsupported. And
    // even if both had been stripped, legacy decryption passes no additional
    // data and AES-GCM would refuse.
    const folded = entryOf(await queueSnapshot(db), entry.entryId);
    await expect(
      readCaptureIntent(db, key, folded, (await rawPayload(entry.entryId))!),
    ).rejects.toBeInstanceOf(CaptureQueueProtocolError);
    expect(await rawPayload(entry.entryId)).toBeDefined();
  });
});

describe("one idempotency key names one intent", () => {
  const base = {
    principalId: PRINCIPAL_A,
    text: NOTE,
    captureKind: "quick_note" as const,
    idempotencyKey: "cap-synthetic-dedup",
    projectId: PROJECT_A,
  };

  it("returns the existing entry for an identical intent without queuing a second row", async () => {
    const first = await enqueueCapture(db, key, base);
    const second = await enqueueCapture(db, key, { ...base });
    expect(second.entryId).toBe(first.entryId);
    expect((await queueSnapshot(db)).length).toBe(1);
    expect((await rawEvents()).filter((event) => event.type === "enqueued").length).toBe(1);
  });

  it("refuses a different Project under the same key, keeping the original", async () => {
    const first = await enqueueCapture(db, key, base);
    await expect(enqueueCapture(db, key, { ...base, projectId: PROJECT_B })).rejects.toMatchObject({
      reason: "intent_conflict",
    });
    const intent = await readCaptureIntent(
      db,
      key,
      entryOf(await queueSnapshot(db), first.entryId),
      (await rawPayload(first.entryId))!,
    );
    expect(intent.projectId).toBe(PROJECT_A);
    expect((await queueSnapshot(db)).length).toBe(1);
  });

  it("refuses different text and a different kind under the same key", async () => {
    await enqueueCapture(db, key, base);
    await expect(
      enqueueCapture(db, key, { ...base, text: "a different note" }),
    ).rejects.toMatchObject({ reason: "intent_conflict" });
    await expect(
      enqueueCapture(db, key, { ...base, captureKind: "conversation_log" }),
    ).rejects.toMatchObject({ reason: "intent_conflict" });
    expect((await queueSnapshot(db)).length).toBe(1);
  });

  it("refuses rather than assuming equality when the existing entry cannot be opened", async () => {
    // A historical row under the same key: its Project was never authenticated,
    // so equality cannot be established and a second row is not written.
    await seedLegacyEntry("oq-legacy-dedup", NOTE, base.idempotencyKey);
    await expect(enqueueCapture(db, key, base)).rejects.toMatchObject({
      reason: "intent_conflict",
    });
    expect((await queueSnapshot(db)).length).toBe(1);
    expect(await rawPayload("oq-legacy-dedup")).toBeDefined();
  });
});

describe("the bounds refuse and never evict", () => {
  it("refuses at the entry limit with every held payload still present", async () => {
    const ids: string[] = [];
    for (let index = 0; index < MAX_QUEUED_ENTRIES; index += 1) {
      const entry = await enqueueCapture(db, key, {
        principalId: PRINCIPAL_A,
        text: `synthetic note ${index}`,
        captureKind: "quick_note",
        idempotencyKey: `cap-synthetic-${index}`,
        projectId: PROJECT_A,
      });
      ids.push(entry.entryId);
    }
    const before = await Promise.all(ids.map(async (id) => bytesOf((await rawPayload(id))!.ciphertext)));

    await expect(
      enqueueCapture(db, key, {
        principalId: PRINCIPAL_A,
        text: "one note too many",
        captureKind: "quick_note",
        idempotencyKey: "cap-synthetic-overflow",
        projectId: PROJECT_A,
      }),
    ).rejects.toBeInstanceOf(OfflineQueueFullError);

    const after = await Promise.all(ids.map(async (id) => bytesOf((await rawPayload(id))!.ciphertext)));
    expect(after).toEqual(before);
    expect((await queueSnapshot(db)).length).toBe(MAX_QUEUED_ENTRIES);
  });

  it("writes nothing at all when the transaction aborts", async () => {
    const entry = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: NOTE,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-abort-a",
      projectId: PROJECT_A,
    });
    const eventsBefore = (await rawEvents()).length;

    // A duplicate payload key aborts the whole transaction, which must take the
    // journal append with it: a queue with an event and no bytes would report a
    // held note that does not exist.
    const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
    tx.objectStore(EVENT_STORE).add({
      entryId: entry.entryId,
      type: "quarantined",
      at: Date.now(),
      reason: "synthetic",
    });
    tx.objectStore(PAYLOAD_STORE).add({ entryId: entry.entryId, iv: new Uint8Array(12), ciphertext: new ArrayBuffer(4) });
    await expect(transactionDone(tx)).rejects.toBeInstanceOf(Error);

    expect((await rawEvents()).length).toBe(eventsBefore);
    expect(await rawPayload(entry.entryId)).toBeDefined();
  });
});
