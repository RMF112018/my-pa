// @vitest-environment node
/**
 * T02 — whole-receipt verification (C02/C07).
 *
 * Every negative here mutates exactly one field of an otherwise complete
 * acknowledgement. That is the point: a verifier that passes when one field is
 * wrong is a verifier that will release encrypted queue bytes for a note the
 * backend filed somewhere else.
 */
import { describe, expect, it } from "vitest";
import {
  contentSha256,
  decodePersistedCaptureAck,
  verifyCaptureReceipt,
  type CaptureReceiptFailure,
} from "./receipt";
import type { FrozenCaptureIntent } from "./contract";

const PRINCIPAL = "aaaa0001-0000-0000-0000-000000000001";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";

/** Frozen Unicode and newline content: the digest must be of these exact bytes. */
const TEXT = "site walk — café slab\nsecond line";

const INTENT: FrozenCaptureIntent = {
  principalId: PRINCIPAL,
  sessionEpoch: 3,
  captureKind: "quick_note",
  text: TEXT,
  idempotencyKey: "idem-0001",
  projectId: PROJECT_A,
};

async function ack(overrides: Record<string, unknown> = {}, receiptOverrides: Record<string, unknown> = {}) {
  return {
    shape: "backend",
    status: "persisted",
    captureKind: "quick_note",
    created: true,
    receipt: {
      receiptId: "rcpt_aaaaaaaa11111111",
      captureId: "cap_aaaaaaaa11111111",
      versionId: "capver_aaaaaaaa11111111",
      versionNumber: 1,
      idempotencyKey: "idem-0001",
      contentSha256: await contentSha256(TEXT),
      principalId: PRINCIPAL,
      issuedAt: "2026-09-22T12:00:00Z",
      projectId: PROJECT_A,
      ...receiptOverrides,
    },
    ...overrides,
  };
}

describe("contentSha256", () => {
  it("is the lowercase hex SHA-256 of the exact UTF-8 bytes", async () => {
    expect(await contentSha256("a note")).toBe(
      "f63e34a034f19a24438f2d74b242bc96682abd843ecc4ea63fefed4006d860a3",
    );
    expect(await contentSha256("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });

  it("does not normalize: composed and decomposed text digest differently", async () => {
    expect(await contentSha256("café")).not.toBe(await contentSha256("café"));
  });

  it("does not trim or case-fold", async () => {
    expect(await contentSha256(" a note ")).not.toBe(await contentSha256("a note"));
    expect(await contentSha256("A Note")).not.toBe(await contentSha256("a note"));
  });
});

describe("decodePersistedCaptureAck", () => {
  it("accepts a complete canonical acknowledgement", async () => {
    const decoded = decodePersistedCaptureAck(await ack());
    expect(decoded).not.toBeNull();
    expect(decoded!.receipt.projectId).toBe(PROJECT_A);
    expect(decoded!.created).toBe(true);
  });

  it("accepts an explicit null Project", async () => {
    const decoded = decodePersistedCaptureAck(await ack({}, { projectId: null }));
    expect(decoded!.receipt.projectId).toBeNull();
  });

  it("refuses an array, a string, a number and null as the whole document", () => {
    for (const value of [[], "persisted", 7, null, undefined, true]) {
      expect(decodePersistedCaptureAck(value)).toBeNull();
    }
  });

  it("refuses a receipt that is an array rather than a record", async () => {
    expect(decodePersistedCaptureAck(await ack({ receipt: [] }))).toBeNull();
  });

  it("refuses a missing nested projectId key, which is not the same as null", async () => {
    const document = (await ack()) as { receipt: Record<string, unknown> };
    delete document.receipt["projectId"];
    expect(decodePersistedCaptureAck(document)).toBeNull();
  });

  it("refuses a malformed nested Project identifier", async () => {
    for (const value of ["", " ", "prj_short", `${PROJECT_A} `, 1, [], {}, true]) {
      expect(decodePersistedCaptureAck(await ack({}, { projectId: value }))).toBeNull();
    }
  });

  it("refuses each empty or absent required identifier", async () => {
    for (const field of ["receiptId", "captureId", "versionId", "idempotencyKey", "principalId"]) {
      expect(decodePersistedCaptureAck(await ack({}, { [field]: "" }))).toBeNull();
      const document = (await ack()) as { receipt: Record<string, unknown> };
      delete document.receipt[field];
      expect(decodePersistedCaptureAck(document)).toBeNull();
    }
  });

  it("refuses a non-positive, fractional or unsafe version number", async () => {
    for (const value of [0, -1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 2, "1", null]) {
      expect(decodePersistedCaptureAck(await ack({}, { versionNumber: value }))).toBeNull();
    }
  });

  it("refuses a digest that is not lowercase 64-hex", async () => {
    const good = await contentSha256(TEXT);
    for (const value of [good.toUpperCase(), good.slice(0, 63), `${good}0`, "", "zz", 1, null]) {
      expect(decodePersistedCaptureAck(await ack({}, { contentSha256: value }))).toBeNull();
    }
  });

  it("refuses a timestamp that is not a parseable zero-offset UTC instant", async () => {
    for (const value of [
      "2026-09-22T12:00:00+02:00",
      "2026-09-22 12:00:00",
      "not a time",
      "2026-13-45T99:00:00Z",
      "",
      1758542400000,
      null,
    ]) {
      expect(decodePersistedCaptureAck(await ack({}, { issuedAt: value }))).toBeNull();
    }
    expect(decodePersistedCaptureAck(await ack({}, { issuedAt: "2026-09-22T12:00:00+00:00" }))).not.toBeNull();
  });

  it("refuses a non-boolean created", async () => {
    for (const value of ["true", 1, null, undefined]) {
      expect(decodePersistedCaptureAck(await ack({ created: value }))).toBeNull();
    }
  });

  it("refuses a kind outside the closed set, including task and constraint", async () => {
    for (const value of ["task", "constraint", "voice_memo", "", null]) {
      expect(decodePersistedCaptureAck(await ack({ captureKind: value }))).toBeNull();
    }
  });

  it("refuses a synthetic or non-persisted shape", async () => {
    expect(decodePersistedCaptureAck(await ack({ shape: "synthetic" }))).toBeNull();
    expect(decodePersistedCaptureAck(await ack({ status: "acknowledged_not_persisted" }))).toBeNull();
  });
});

describe("verifyCaptureReceipt", () => {
  async function reason(input: unknown, intent = INTENT): Promise<CaptureReceiptFailure | "ok"> {
    const outcome = await verifyCaptureReceipt(input, intent);
    return outcome.ok ? "ok" : outcome.reason;
  }

  it("accepts a complete receipt that answers the frozen intent", async () => {
    const outcome = await verifyCaptureReceipt(await ack(), INTENT);
    expect(outcome.ok).toBe(true);
    if (outcome.ok) expect(outcome.ack.receipt.projectId).toBe(PROJECT_A);
  });

  it("accepts a No Project intent against a null persisted Project", async () => {
    const outcome = await verifyCaptureReceipt(await ack({}, { projectId: null }), {
      ...INTENT,
      projectId: null,
    });
    expect(outcome.ok).toBe(true);
  });

  it("calls a synthetic acknowledgement not persisted, not merely malformed", async () => {
    expect(
      await reason({
        shape: "synthetic",
        receiptId: "rcpt_x",
        created: true,
        captureKind: "quick_note",
        status: "acknowledged_not_persisted",
      }),
    ).toBe("not_persisted");
  });

  it("refuses a receipt persisted against a different Project", async () => {
    expect(await reason(await ack({}, { projectId: PROJECT_B }))).toBe("project_mismatch");
  });

  it("refuses a null persisted Project when the intent named one", async () => {
    expect(await reason(await ack({}, { projectId: null }))).toBe("project_mismatch");
  });

  it("refuses a named persisted Project when the intent was No Project", async () => {
    expect(await reason(await ack(), { ...INTENT, projectId: null })).toBe("project_mismatch");
  });

  it("refuses a different Principal, key, kind and digest, each on its own", async () => {
    expect(await reason(await ack({}, { principalId: "bbbb0002-0000-0000-0000-000000000002" }))).toBe(
      "principal_mismatch",
    );
    expect(await reason(await ack({}, { idempotencyKey: "idem-0002" }))).toBe("key_mismatch");
    expect(await reason(await ack({ captureKind: "conversation_log" }))).toBe("kind_mismatch");
    expect(await reason(await ack({}, { contentSha256: await contentSha256("a different note") }))).toBe(
      "digest_mismatch",
    );
  });

  it("refuses a digest of the same text normalized or trimmed", async () => {
    expect(await reason(await ack({}, { contentSha256: await contentSha256(TEXT.normalize("NFC")) }))).toBe(
      "digest_mismatch",
    );
    expect(await reason(await ack({}, { contentSha256: await contentSha256(TEXT.trim() + " ") }))).toBe(
      "digest_mismatch",
    );
  });

  it("refuses a malformed receipt before it compares anything", async () => {
    const document = (await ack()) as { receipt: Record<string, unknown> };
    delete document.receipt["projectId"];
    expect(await reason(document)).toBe("malformed_receipt");
    expect(await reason(null)).toBe("malformed_receipt");
    expect(await reason([await ack()])).toBe("malformed_receipt");
  });

  it("never carries authored text or a Project name in a failure", async () => {
    const outcome = await verifyCaptureReceipt(await ack({}, { projectId: PROJECT_B }), INTENT);
    expect(outcome.ok).toBe(false);
    const serialized = JSON.stringify(outcome);
    expect(serialized).not.toContain("site walk");
    expect(serialized).not.toContain(PROJECT_B);
    expect(serialized).toBe('{"ok":false,"reason":"project_mismatch"}');
  });
});
