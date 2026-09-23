/**
 * T07 — key loading versus key creation (C06).
 *
 * The defect being ruled out is specific and irreversible: a read path that
 * mints a key when the key store has been cleared but the payloads have not.
 * The new key cannot decrypt the retained ciphertext, and writing it makes the
 * loss silent. Real WebCrypto and real IndexedDB throughout.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import {
  KEY_STORE,
  openOfflineDatabase,
  request,
  transactionDone,
} from "@/lib/offline/db";
import {
  CaptureKeyUnavailableError,
  OfflineKeyUnavailableError,
  getOrCreatePrincipalKey,
  loadPrincipalKey,
} from "@/lib/offline/key";
import {
  enqueueCapture,
  queueSnapshot,
  readCaptureIntent,
  readPayloadRecord,
} from "@/lib/offline/queue";
import { seal, unseal } from "@/lib/offline/key";

/**
 * Whether two handles are the same key.
 *
 * Reference equality is the wrong question: a structured clone out of IndexedDB
 * is a new `CryptoKey` object every read. What matters is whether one can open
 * what the other sealed, which is also the property the queue actually depends
 * on.
 */
async function sameKeyMaterial(left: CryptoKey, right: CryptoKey): Promise<boolean> {
  const sealed = await seal(left, "synthetic probe");
  try {
    return (await unseal(right, sealed)) === "synthetic probe";
  } catch {
    return false;
  }
}

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";
const PROJECT_A = "prj_aaaaaaaa11111111";

let db: IDBDatabase;

beforeEach(async () => {
  globalThis.indexedDB = new IDBFactory();
  vi.restoreAllMocks();
  db = await openOfflineDatabase();
});

async function clearKeyStore(): Promise<void> {
  const tx = db.transaction(KEY_STORE, "readwrite");
  tx.objectStore(KEY_STORE).clear();
  await transactionDone(tx);
}

async function storedKeyCount(): Promise<number> {
  const tx = db.transaction(KEY_STORE, "readonly");
  const keys = (await request(tx.objectStore(KEY_STORE).getAllKeys())) as readonly IDBValidKey[];
  await transactionDone(tx).catch(() => undefined);
  return keys.length;
}

async function queueOne(idempotencyKey: string): Promise<string> {
  const key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
  const entry = await enqueueCapture(db, key, {
    principalId: PRINCIPAL_A,
    text: "synthetic note alpha",
    captureKind: "quick_note",
    idempotencyKey,
    projectId: PROJECT_A,
  });
  return entry.entryId;
}

describe("loading is read-only", () => {
  it("returns null for a Principal with no key and writes nothing", async () => {
    const generate = vi.spyOn(crypto.subtle, "generateKey");
    await expect(loadPrincipalKey(db, PRINCIPAL_A)).resolves.toBeNull();
    expect(generate).not.toHaveBeenCalled();
    expect(await storedKeyCount()).toBe(0);
  });

  it("returns the stored key without generating when one exists", async () => {
    const created = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
    const generate = vi.spyOn(crypto.subtle, "generateKey");
    const loaded = await loadPrincipalKey(db, PRINCIPAL_A);
    expect(loaded).not.toBeNull();
    expect(await sameKeyMaterial(created, loaded!)).toBe(true);
    expect(generate).not.toHaveBeenCalled();
  });

  it("refuses a stored key that is not the one this module writes", async () => {
    const extractable = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
      "encrypt",
      "decrypt",
    ]);
    const tx = db.transaction(KEY_STORE, "readwrite");
    tx.objectStore(KEY_STORE).put({ principalId: PRINCIPAL_A, key: extractable, createdAt: 0 });
    await transactionDone(tx);

    await expect(loadPrincipalKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      CaptureKeyUnavailableError,
    );
    // Held, not repaired: the bad record is still there and no replacement was
    // generated over it.
    expect(await storedKeyCount()).toBe(1);
  });

  it("reports the unusable key with the fixed protocol reason", async () => {
    const tx = db.transaction(KEY_STORE, "readwrite");
    tx.objectStore(KEY_STORE).put({ principalId: PRINCIPAL_A, key: { notAKey: true }, createdAt: 0 });
    await transactionDone(tx);
    await expect(loadPrincipalKey(db, PRINCIPAL_A)).rejects.toMatchObject({
      reason: "key_unavailable",
    });
  });

  it("is still an OfflineKeyUnavailableError, so existing fail-closed callers refuse", async () => {
    const tx = db.transaction(KEY_STORE, "readwrite");
    tx.objectStore(KEY_STORE).put({ principalId: PRINCIPAL_A, key: null, createdAt: 0 });
    await transactionDone(tx);
    await expect(loadPrincipalKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
  });
});

describe("a missing key is never regenerated over retained ciphertext", () => {
  it("refuses to create a first key while payloads are still held", async () => {
    const entryId = await queueOne("cap-synthetic-retained");
    await clearKeyStore();

    const generate = vi.spyOn(crypto.subtle, "generateKey");
    await expect(getOrCreatePrincipalKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
    expect(generate).not.toHaveBeenCalled();
    expect(await storedKeyCount()).toBe(0);

    // The bytes are preserved exactly as they were. They are unreadable, and
    // saying so is the honest answer; overwriting them would not be.
    expect(await readPayloadRecord(db, entryId)).not.toBeNull();
    expect((await queueSnapshot(db))[0]!.state).toBe("pending");
  });

  it("still creates a first key for a different Principal with nothing held", async () => {
    await queueOne("cap-synthetic-a");
    const key = await getOrCreatePrincipalKey(db, PRINCIPAL_B);
    expect(key.extractable).toBe(false);
    expect(await storedKeyCount()).toBe(2);
  });

  it("creates a first key when the queue is genuinely empty", async () => {
    const key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
    expect(key.algorithm).toMatchObject({ name: "AES-GCM", length: 256 });
    expect(key.extractable).toBe(false);
    expect([...key.usages].sort()).toEqual(["decrypt", "encrypt"]);
  });

  it("creates a first key again once the held payload is gone", async () => {
    const entryId = await queueOne("cap-synthetic-gone");
    const tx = db.transaction("payloads", "readwrite");
    tx.objectStore("payloads").delete(entryId);
    await transactionDone(tx);
    await clearKeyStore();

    await expect(getOrCreatePrincipalKey(db, PRINCIPAL_A)).resolves.toBeDefined();
  });
});

describe("two initializers racing for a first key", () => {
  it("both end up with the one stored key rather than overwriting each other", async () => {
    const [first, second] = await Promise.all([
      getOrCreatePrincipalKey(db, PRINCIPAL_A),
      getOrCreatePrincipalKey(db, PRINCIPAL_A),
    ]);
    expect(await storedKeyCount()).toBe(1);
    const stored = await loadPrincipalKey(db, PRINCIPAL_A);
    expect(await sameKeyMaterial(first!, stored!)).toBe(true);
    expect(await sameKeyMaterial(second!, stored!)).toBe(true);
    expect(await sameKeyMaterial(first!, second!)).toBe(true);
  });

  it("never overwrites a committed key that a payload was already sealed under", async () => {
    // The hazard the `add`-after-re-read exists for: tab A commits a key and
    // seals a note under it; tab B, which had already generated its own
    // candidate before A committed, must adopt A's key rather than storing its
    // own over it — otherwise A's ciphertext becomes permanently unreadable.
    const committed = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
    const entryId = await queueOne("cap-synthetic-sealed-first");

    const losingCandidate = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, [
      "encrypt",
      "decrypt",
    ]);
    vi.spyOn(crypto.subtle, "generateKey").mockResolvedValue(losingCandidate);
    // Force the creation path to run again as a late initializer would.
    const adopted = await getOrCreatePrincipalKey(db, PRINCIPAL_A);

    expect(await storedKeyCount()).toBe(1);
    expect(await sameKeyMaterial(committed, adopted)).toBe(true);
    expect(await sameKeyMaterial(losingCandidate, adopted)).toBe(false);
    // And the note sealed before the race is still readable.
    const stored = await loadPrincipalKey(db, PRINCIPAL_A);
    const record = await readPayloadRecord(db, entryId);
    expect(record).not.toBeNull();
    const entry = (await queueSnapshot(db)).find((item) => item.entryId === entryId)!;
    await expect(readCaptureIntent(db, stored!, entry, record!)).resolves.toMatchObject({
      projectId: PROJECT_A,
    });
  });

  it("never replaces a key that a competing initializer already committed", async () => {
    // The loser's commit must be an `add` that loses, not a `put` that wins: a
    // `put` would replace a key another tab had already sealed a payload under.
    const winner = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
    const entryId = await queueOne("cap-synthetic-race");

    const again = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
    expect(await sameKeyMaterial(winner, again)).toBe(true);
    expect(await storedKeyCount()).toBe(1);
    expect(await readPayloadRecord(db, entryId)).not.toBeNull();
  });
});
