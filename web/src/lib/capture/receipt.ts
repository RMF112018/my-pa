/**
 * Whole-receipt verification for one frozen Capture intent (C02).
 *
 * `lib/offline/replay.ts` already carried a weaker local check: it compared a
 * couple of fields and then deleted encrypted bytes. That is the wrong order of
 * trust for a queue whose whole purpose is that the note is not stored anywhere
 * else. This module is the single verifier both the online BFF path and replay
 * use, and it validates the **complete** canonical acknowledgement shape before
 * anything is called saved and before any payload is released.
 *
 * **What a failure is allowed to say.** `CaptureReceiptFailure` is a closed
 * union of field classes. It carries no authored text, no decrypted payload, no
 * Project name and no raw upstream body — a diagnostic that renders the content
 * is the leak the offline queue exists to prevent.
 *
 * **What a failure is not.** None of these reasons mean "nothing was stored".
 * A mismatched or unreadable acknowledgement is ambiguous: the backend may well
 * have committed. Callers report ambiguity and retain the intent; they do not
 * announce a refusal and they do not delete.
 */
import {
  isCaptureKind,
  type CaptureKind,
  type FrozenCaptureIntent,
  type PersistedCaptureAck,
} from "./contract";
import { isProjectId } from "@/lib/project-scope/scope";

/** The closed set of reasons a receipt is not accepted. Content-free. */
export type CaptureReceiptFailure =
  | "not_persisted"
  | "malformed_receipt"
  | "principal_mismatch"
  | "kind_mismatch"
  | "key_mismatch"
  | "digest_mismatch"
  | "project_mismatch";

export type CaptureReceiptVerification =
  | { readonly ok: true; readonly ack: PersistedCaptureAck }
  | { readonly ok: false; readonly reason: CaptureReceiptFailure };

const SHA256_HEX = /^[0-9a-f]{64}$/;
const UTC_ISO = /(?:Z|[+-]00:00)$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function positiveSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** Lowercase 64-hex only: an uppercase or truncated digest is not this digest. */
function isSha256Hex(value: unknown): value is string {
  return typeof value === "string" && SHA256_HEX.test(value);
}

/** A UTC instant the canonical receipt issued: parseable and zero-offset. */
function isUtcIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    UTC_ISO.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function toHex(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
}

/**
 * The SHA-256 of the accepted text's exact UTF-8 bytes, lowercase hex.
 *
 * The text handed here has already been normalized once, by the existing
 * `trim()` at the browser/BFF boundary. Nothing in this module normalizes
 * again: a second normalization would hash bytes the backend never accepted.
 */
export async function contentSha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return toHex(new Uint8Array(digest));
}

/**
 * The canonical persisted acknowledgement, or null if the input is not one.
 *
 * Strict on every required field. A synthetic acknowledgement, a partial
 * receipt, an array, an empty identifier or an absent nested `projectId` key all
 * decode to null — the absent key matters, because "the backend did not say"
 * and "the backend said No Project" are different answers.
 */
export function decodePersistedCaptureAck(input: unknown): PersistedCaptureAck | null {
  if (!isRecord(input)) return null;
  if (input["shape"] !== "backend") return null;
  if (input["status"] !== "persisted") return null;
  const captureKind = input["captureKind"];
  if (!isCaptureKind(captureKind)) return null;
  const created = input["created"];
  if (typeof created !== "boolean") return null;

  const receipt = input["receipt"];
  if (!isRecord(receipt)) return null;
  const receiptId = receipt["receiptId"];
  const captureId = receipt["captureId"];
  const versionId = receipt["versionId"];
  const idempotencyKey = receipt["idempotencyKey"];
  const principalId = receipt["principalId"];
  if (!nonEmptyString(receiptId)) return null;
  if (!nonEmptyString(captureId)) return null;
  if (!nonEmptyString(versionId)) return null;
  if (!nonEmptyString(idempotencyKey)) return null;
  if (!nonEmptyString(principalId)) return null;
  const versionNumber = receipt["versionNumber"];
  if (!positiveSafeInteger(versionNumber)) return null;
  const digest = receipt["contentSha256"];
  if (!isSha256Hex(digest)) return null;
  const issuedAt = receipt["issuedAt"];
  if (!isUtcIsoTimestamp(issuedAt)) return null;
  if (!("projectId" in receipt)) return null;
  const projectId = receipt["projectId"];
  if (projectId !== null && !isProjectId(projectId)) return null;

  return {
    shape: "backend",
    status: "persisted",
    captureKind,
    created,
    receipt: {
      receiptId,
      captureId,
      versionId,
      versionNumber,
      idempotencyKey,
      contentSha256: digest,
      principalId,
      issuedAt,
      projectId,
    },
  };
}

/** True when the input is an explicitly non-durable synthetic acknowledgement. */
function claimsNotPersisted(input: unknown): boolean {
  if (!isRecord(input)) return false;
  return input["shape"] === "synthetic" || input["status"] === "acknowledged_not_persisted";
}

/**
 * Verify a whole acknowledgement against the frozen intent it answers.
 *
 * The full canonical shape is validated before any equality is examined, and
 * every equality is exact: Principal, idempotency key, kind, the SHA-256 of the
 * frozen accepted text, and the Project **including null**. A synthetic
 * acknowledgement is `not_persisted` and can never release queued bytes.
 */
export async function verifyCaptureReceipt(
  input: unknown,
  intent: FrozenCaptureIntent,
): Promise<CaptureReceiptVerification> {
  if (claimsNotPersisted(input)) return { ok: false, reason: "not_persisted" };
  const ack = decodePersistedCaptureAck(input);
  if (ack === null) return { ok: false, reason: "malformed_receipt" };

  if (ack.receipt.principalId !== intent.principalId) {
    return { ok: false, reason: "principal_mismatch" };
  }
  if (ack.receipt.idempotencyKey !== intent.idempotencyKey) {
    return { ok: false, reason: "key_mismatch" };
  }
  if (ack.captureKind !== (intent.captureKind as CaptureKind)) {
    return { ok: false, reason: "kind_mismatch" };
  }
  if (ack.receipt.contentSha256 !== (await contentSha256(intent.text))) {
    return { ok: false, reason: "digest_mismatch" };
  }
  if (ack.receipt.projectId !== intent.projectId) {
    return { ok: false, reason: "project_mismatch" };
  }
  return { ok: true, ack };
}
