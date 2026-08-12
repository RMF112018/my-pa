/**
 * The offline content key: non-extractable, per principal, and never downgraded.
 *
 * These run against the **real** `key.ts` over a real IndexedDB implementation
 * (`fake-indexeddb`) and the real Web Crypto in this runtime. Nothing here is a
 * stand-in for the store: a `CryptoKey` is put into IndexedDB, read back out of
 * it, and used to decrypt bytes the first handle sealed, which is precisely the
 * round trip the browser performs.
 *
 * Every string in this file is obviously synthetic.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { openOfflineDatabase, KEY_STORE, transactionDone } from "@/lib/offline/db";
import {
  OfflineKeyUnavailableError,
  principalContentKey,
  seal,
  unseal,
  IV_BYTES,
} from "@/lib/offline/key";

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";
const NOTE = "synthetic note alpha";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  vi.restoreAllMocks();
});

describe("the content key is non-extractable and stays that way", () => {
  it("asks generateKey for a non-extractable AES-GCM 256 key", async () => {
    const spy = vi.spyOn(crypto.subtle, "generateKey");
    const db = await openOfflineDatabase();
    const key = await principalContentKey(db, PRINCIPAL_A);

    expect(spy).toHaveBeenCalledTimes(1);
    const [algorithm, extractable, usages] = spy.mock.calls[0];
    expect(algorithm).toEqual({ name: "AES-GCM", length: 256 });
    expect(extractable).toBe(false);
    expect(usages).toEqual(["encrypt", "decrypt"]);
    expect(key.extractable).toBe(false);
  });

  it("reads back out of IndexedDB still non-extractable, and still decrypts", async () => {
    const db = await openOfflineDatabase();
    const first = await principalContentKey(db, PRINCIPAL_A);
    const sealed = await seal(first, NOTE);

    const second = await principalContentKey(db, PRINCIPAL_A);
    expect(second.extractable).toBe(false);
    await expect(unseal(second, sealed)).resolves.toBe(NOTE);
  });

  it("never exports the key, at generation or at use", async () => {
    const exportKey = vi.spyOn(crypto.subtle, "exportKey");
    const db = await openOfflineDatabase();
    const key = await principalContentKey(db, PRINCIPAL_A);
    const sealed = await seal(key, NOTE);
    await unseal(key, sealed);
    expect(exportKey).not.toHaveBeenCalled();
  });

  it("draws a fresh 96-bit IV for every record", async () => {
    const db = await openOfflineDatabase();
    const key = await principalContentKey(db, PRINCIPAL_A);
    const first = await seal(key, NOTE);
    const second = await seal(key, NOTE);
    expect(first.iv).toHaveLength(IV_BYTES);
    expect(second.iv).toHaveLength(IV_BYTES);
    expect(Array.from(first.iv)).not.toEqual(Array.from(second.iv));
    // Same plaintext, different nonce, therefore different ciphertext.
    expect(Array.from(new Uint8Array(first.ciphertext))).not.toEqual(
      Array.from(new Uint8Array(second.ciphertext)),
    );
  });
});

describe("the key is per principal", () => {
  it("gives two principals two different keys", async () => {
    const db = await openOfflineDatabase();
    const a = await principalContentKey(db, PRINCIPAL_A);
    const b = await principalContentKey(db, PRINCIPAL_B);
    expect(a).not.toBe(b);
  });

  it("refuses to decrypt one principal's payload with the other's key", async () => {
    const db = await openOfflineDatabase();
    const a = await principalContentKey(db, PRINCIPAL_A);
    const b = await principalContentKey(db, PRINCIPAL_B);
    const sealed = await seal(a, NOTE);
    await expect(unseal(b, sealed)).rejects.toThrow();
    // And A's own key still opens it, so the failure is the key and not the bytes.
    await expect(unseal(a, sealed)).resolves.toBe(NOTE);
  });
});

describe("fail closed — there is no downgrade path", () => {
  it("refuses when generateKey hands back an extractable key", async () => {
    const db = await openOfflineDatabase();
    const extractable = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
      "encrypt",
      "decrypt",
    ]);
    vi.spyOn(crypto.subtle, "generateKey").mockResolvedValue(extractable);

    await expect(principalContentKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
    // And nothing was stored: the refusal is not a "store it and warn".
    const tx = db.transaction(KEY_STORE, "readonly");
    const stored = await new Promise((resolve) => {
      const req = tx.objectStore(KEY_STORE).get(PRINCIPAL_A);
      req.onsuccess = () => resolve(req.result);
    });
    await transactionDone(tx).catch(() => undefined);
    expect(stored).toBeUndefined();
  });

  it("refuses a stored key that reads back extractable rather than using it", async () => {
    const db = await openOfflineDatabase();
    const planted = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
      "encrypt",
      "decrypt",
    ]);
    const tx = db.transaction(KEY_STORE, "readwrite");
    tx.objectStore(KEY_STORE).put({ principalId: PRINCIPAL_A, key: planted, createdAt: 0 });
    await transactionDone(tx);

    await expect(principalContentKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
  });

  it("refuses when the key cannot be stored, rather than keeping one in memory", async () => {
    const db = await openOfflineDatabase();
    const real = db.transaction.bind(db);
    vi.spyOn(db, "transaction").mockImplementation((stores, mode) => {
      if (mode === "readwrite") throw new DOMException("storage refused", "InvalidStateError");
      return real(stores as string[], mode);
    });

    await expect(principalContentKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
  });

  it("refuses when generateKey itself refuses", async () => {
    const db = await openOfflineDatabase();
    vi.spyOn(crypto.subtle, "generateKey").mockRejectedValue(
      new DOMException("unsupported", "NotSupportedError"),
    );
    await expect(principalContentKey(db, PRINCIPAL_A)).rejects.toBeInstanceOf(
      OfflineKeyUnavailableError,
    );
  });
});
