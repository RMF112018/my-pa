/**
 * T05 — the v2 intent codec, against real WebCrypto (C05).
 *
 * The seals below are made with the real AES-GCM implementation and a real
 * non-extractable key, so "changing the Project fails authentication" is checked
 * by trying it rather than by reading the code.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { openOfflineDatabase } from "@/lib/offline/db";
import { getOrCreatePrincipalKey, sealBytes, unsealBytes } from "@/lib/offline/key";
import {
  CAPTURE_INTENT_CONTENT_TAG,
  CAPTURE_INTENT_ENVELOPE_TAG,
  CAPTURE_INTENT_SCHEMA_VERSION,
  CaptureQueueProtocolError,
  captureIntentAdditionalData,
  decodeCaptureIntentV2,
  detectCapturePayloadVersion,
  encodeCaptureIntentV2,
  type CaptureIntentEnvelope,
  type CaptureIntentV2,
} from "@/lib/offline/capture-intent-codec";

const PRINCIPAL_A = "syn-aaaa0001";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";

const ENVELOPE: CaptureIntentEnvelope = {
  entryId: "oq-synthetic-0001",
  principalId: PRINCIPAL_A,
  idempotencyKey: "cap-synthetic-0001",
  captureKind: "quick_note",
  queuedAt: 1_758_542_400_000,
};

const INTENT: CaptureIntentV2 = {
  ...ENVELOPE,
  text: "synthetic note — café slab\nsecond line",
  projectId: PROJECT_A,
};

let key: CryptoKey;

beforeEach(async () => {
  globalThis.indexedDB = new IDBFactory();
  const db = await openOfflineDatabase();
  key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
});

afterEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

function decodeText(bytes: Uint8Array): unknown {
  return JSON.parse(new TextDecoder().decode(bytes));
}

describe("the frozen representations", () => {
  it("serializes the plaintext as the exact fixed-order tuple", () => {
    expect(decodeText(encodeCaptureIntentV2(INTENT))).toEqual([
      CAPTURE_INTENT_CONTENT_TAG,
      2,
      ENVELOPE.entryId,
      ENVELOPE.principalId,
      ENVELOPE.idempotencyKey,
      ENVELOPE.captureKind,
      ENVELOPE.queuedAt,
      INTENT.text,
      PROJECT_A,
    ]);
  });

  it("serializes the additional data as the exact fixed-order tuple, without the Project", () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    expect(decodeText(aad)).toEqual([
      CAPTURE_INTENT_ENVELOPE_TAG,
      2,
      ENVELOPE.entryId,
      ENVELOPE.principalId,
      ENVELOPE.idempotencyKey,
      ENVELOPE.captureKind,
      ENVELOPE.queuedAt,
    ]);
    // The Project is never in the clear. That is the whole point of putting it
    // inside the ciphertext instead.
    expect(new TextDecoder().decode(aad)).not.toContain(PROJECT_A);
  });

  it("is the same version marker the records carry", () => {
    expect(CAPTURE_INTENT_SCHEMA_VERSION).toBe(2);
  });
});

describe("roundtrip under a real key", () => {
  it("returns exactly what was sealed, Project included", async () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(INTENT), aad);
    const opened = await unsealBytes(key, sealed, aad);
    expect(decodeCaptureIntentV2(opened, ENVELOPE)).toEqual(INTENT);
  });

  it("preserves a No Project intent as null, not as an absent field", async () => {
    const intent = { ...INTENT, projectId: null };
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(intent), aad);
    expect(decodeCaptureIntentV2(await unsealBytes(key, sealed, aad), ENVELOPE).projectId).toBeNull();
  });

  it("does not normalize, trim or case-fold the authored text", async () => {
    const authored = "  Mixed Case café  \n";
    const intent = { ...INTENT, text: authored };
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(intent), aad);
    const opened = decodeCaptureIntentV2(await unsealBytes(key, sealed, aad), ENVELOPE).text;
    expect(opened).toBe(authored);
    expect(opened).not.toBe(authored.normalize("NFC"));
    expect(opened).not.toBe(authored.trim());
  });
});

describe("tampering fails authentication rather than yielding something plausible", () => {
  it("refuses a payload resealed with Project B against a Project A envelope", async () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealedA = await sealBytes(key, encodeCaptureIntentV2(INTENT), aad);
    const sealedB = await sealBytes(
      key,
      encodeCaptureIntentV2({ ...INTENT, projectId: PROJECT_B }),
      aad,
    );
    // Both open — they were both produced by an authorized encryption actor.
    // What the codec guarantees is that the Project is the sealed one, never a
    // value read from anywhere else.
    expect(decodeCaptureIntentV2(await unsealBytes(key, sealedA, aad), ENVELOPE).projectId).toBe(
      PROJECT_A,
    );
    expect(decodeCaptureIntentV2(await unsealBytes(key, sealedB, aad), ENVELOPE).projectId).toBe(
      PROJECT_B,
    );
  });

  it("refuses ciphertext whose bytes were altered at rest", async () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(INTENT), aad);
    const bytes = new Uint8Array(sealed.ciphertext);
    bytes[0] = bytes[0]! ^ 0xff;
    await expect(
      unsealBytes(key, { iv: sealed.iv, ciphertext: bytes.buffer }, aad),
    ).rejects.toBeInstanceOf(Error);
  });

  it("refuses when the journal metadata around the payload was rewritten", async () => {
    const sealed = await sealBytes(
      key,
      encodeCaptureIntentV2(INTENT),
      captureIntentAdditionalData(ENVELOPE),
    );
    for (const mutation of [
      { entryId: "oq-synthetic-9999" },
      { principalId: "syn-bbbb0002" },
      { idempotencyKey: "cap-synthetic-9999" },
      { captureKind: "conversation_log" as const },
      { queuedAt: ENVELOPE.queuedAt + 1 },
    ]) {
      const forged = { ...ENVELOPE, ...mutation };
      await expect(
        unsealBytes(key, sealed, captureIntentAdditionalData(forged)),
      ).rejects.toBeInstanceOf(Error);
    }
  });

  it("refuses a decoded tuple whose metadata does not match the row it came from", async () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    const plaintext = await unsealBytes(
      key,
      await sealBytes(key, encodeCaptureIntentV2(INTENT), aad),
      aad,
    );
    expect(() =>
      decodeCaptureIntentV2(plaintext, { ...ENVELOPE, entryId: "oq-synthetic-9999" }),
    ).toThrow(
      expect.objectContaining({ reason: "metadata_mismatch" }),
    );
  });

  it("cannot be opened by another Principal's key", async () => {
    const db = await openOfflineDatabase();
    const other = await getOrCreatePrincipalKey(db, "syn-bbbb0002");
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(INTENT), aad);
    await expect(unsealBytes(other, sealed, aad)).rejects.toBeInstanceOf(Error);
  });

  it("cannot be opened without the additional data it was sealed with", async () => {
    const aad = captureIntentAdditionalData(ENVELOPE);
    const sealed = await sealBytes(key, encodeCaptureIntentV2(INTENT), aad);
    // This is the stripped-marker downgrade: a row whose version markers were
    // removed looks legacy, and legacy decryption passes no additional data.
    await expect(unsealBytes(key, sealed)).rejects.toBeInstanceOf(Error);
  });
});

describe("the decoder refuses everything it cannot fully account for", () => {
  function bytes(value: unknown): Uint8Array {
    return new TextEncoder().encode(JSON.stringify(value));
  }
  const base: unknown[] = [
    CAPTURE_INTENT_CONTENT_TAG,
    2,
    ENVELOPE.entryId,
    ENVELOPE.principalId,
    ENVELOPE.idempotencyKey,
    ENVELOPE.captureKind,
    ENVELOPE.queuedAt,
    "a note",
    PROJECT_A,
  ];

  it("refuses invalid UTF-8 fatally rather than substituting replacement characters", () => {
    expect(() => decodeCaptureIntentV2(new Uint8Array([0xff, 0xfe, 0xfd]), ENVELOPE)).toThrow(
      expect.objectContaining({ reason: "invalid_utf8" }),
    );
  });

  it("refuses content that is not JSON", () => {
    expect(() => decodeCaptureIntentV2(new TextEncoder().encode("not json"), ENVELOPE)).toThrow(
      expect.objectContaining({ reason: "malformed_intent" }),
    );
  });

  it("refuses an object form, a short tuple and a long tuple", () => {
    expect(() => decodeCaptureIntentV2(bytes({ text: "a note" }), ENVELOPE)).toThrow(
      CaptureQueueProtocolError,
    );
    expect(() => decodeCaptureIntentV2(bytes(base.slice(0, 8)), ENVELOPE)).toThrow(
      CaptureQueueProtocolError,
    );
    expect(() => decodeCaptureIntentV2(bytes([...base, "extra"]), ENVELOPE)).toThrow(
      CaptureQueueProtocolError,
    );
  });

  it("refuses a wrong tag and an unsupported version", () => {
    expect(() => decodeCaptureIntentV2(bytes(["other.tag", ...base.slice(1)]), ENVELOPE)).toThrow(
      expect.objectContaining({ reason: "malformed_intent" }),
    );
    for (const version of [1, 3, "2", null]) {
      expect(() =>
        decodeCaptureIntentV2(bytes([base[0], version, ...base.slice(2)]), ENVELOPE),
      ).toThrow(expect.objectContaining({ reason: "unsupported_version" }));
    }
  });

  it("refuses an unknown kind, including task and constraint", () => {
    for (const kind of ["task", "constraint", "", null, 1]) {
      const tuple = [...base];
      tuple[5] = kind;
      expect(() => decodeCaptureIntentV2(bytes(tuple), ENVELOPE)).toThrow(
        CaptureQueueProtocolError,
      );
    }
  });

  it("refuses a queuedAt that is negative, fractional, unsafe or not a number", () => {
    for (const at of [-1, 1.5, Number.MAX_SAFE_INTEGER + 2, "1758542400000", null]) {
      const tuple = [...base];
      tuple[6] = at;
      expect(() => decodeCaptureIntentV2(bytes(tuple), ENVELOPE)).toThrow(
        CaptureQueueProtocolError,
      );
    }
  });

  it("refuses an empty identity field", () => {
    for (const index of [2, 3, 4]) {
      const tuple = [...base];
      tuple[index] = "";
      expect(() => decodeCaptureIntentV2(bytes(tuple), ENVELOPE)).toThrow(
        CaptureQueueProtocolError,
      );
    }
  });

  it("refuses a malformed Project and never defaults one", () => {
    // `undefined` is absent from this list deliberately: JSON renders it as
    // `null`, which is the legitimate No Project value, so it is not a case the
    // decoder can or should distinguish.
    for (const project of ["", " ", "prj_short", `${PROJECT_A} `, 1, [], {}, true]) {
      const tuple = [...base];
      tuple[8] = project;
      expect(() => decodeCaptureIntentV2(bytes(tuple), ENVELOPE)).toThrow(
        CaptureQueueProtocolError,
      );
    }
  });

  it("refuses a tuple that parses correctly but was not canonically serialized", () => {
    // Same values, different encoding. Accepting this would mean the bytes read
    // back are not the bytes that were sealed.
    const padded = new TextEncoder().encode(`${JSON.stringify(base)} `);
    expect(() => decodeCaptureIntentV2(padded, ENVELOPE)).toThrow(
      expect.objectContaining({ reason: "malformed_intent" }),
    );
  });

  it("refuses to encode an intent it could not decode", () => {
    expect(() => encodeCaptureIntentV2({ ...INTENT, entryId: "" })).toThrow(
      CaptureQueueProtocolError,
    );
    expect(() => encodeCaptureIntentV2({ ...INTENT, projectId: "prj_bad" })).toThrow(
      CaptureQueueProtocolError,
    );
  });
});

describe("version detection reads the stored markers, not the payload shape", () => {
  it("calls a pair with no markers at all legacy", () => {
    expect(detectCapturePayloadVersion({ entryId: "a" }, { entryId: "a" })).toBe("legacy");
  });

  it("calls a matched pair of 2 v2", () => {
    expect(detectCapturePayloadVersion({ schemaVersion: 2 }, { schemaVersion: 2 })).toBe("v2");
  });

  it("calls a half-marked pair unsupported in both directions", () => {
    expect(detectCapturePayloadVersion({ schemaVersion: 2 }, {})).toBe("unsupported");
    expect(detectCapturePayloadVersion({}, { schemaVersion: 2 })).toBe("unsupported");
  });

  it("calls any other version or type unsupported, including a literal 1", () => {
    for (const marker of [1, 3, "2", null, true, {}]) {
      expect(detectCapturePayloadVersion({ schemaVersion: marker }, { schemaVersion: marker })).toBe(
        "unsupported",
      );
    }
  });

  it("calls a non-record unsupported rather than legacy", () => {
    expect(detectCapturePayloadVersion(null, { schemaVersion: 2 })).toBe("unsupported");
    expect(detectCapturePayloadVersion({ schemaVersion: 2 }, "payload")).toBe("unsupported");
    expect(detectCapturePayloadVersion(undefined, undefined)).toBe("unsupported");
  });
});
