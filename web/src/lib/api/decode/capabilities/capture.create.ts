import type { Decoder } from "../types";
import {
  fail,
  pick,
  requiredBoolean,
  requiredIntGe,
  requiredSha256,
  requiredString,
} from "./_mutation-helpers";

export interface CaptureCreateResult {
  readonly receipt_id: string;
  readonly capture_id: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly idempotency_key: string;
  readonly content_sha256: string;
  readonly issued_at: string;
  readonly created: boolean;
}

const KEYS = [
  "receipt_id",
  "capture_id",
  "version_id",
  "version_number",
  "idempotency_key",
  "content_sha256",
  "issued_at",
  "created",
] as const;

export const decodeCaptureCreate: Decoder<CaptureCreateResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const receiptId = requiredString(known.value.receipt_id);
  if (!receiptId.ok) return receiptId;
  const captureId = requiredString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const versionNumber = requiredIntGe(known.value.version_number, 1);
  if (!versionNumber.ok) return versionNumber;
  const idempotencyKey = requiredString(known.value.idempotency_key);
  if (!idempotencyKey.ok) return idempotencyKey;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const issuedAt = requiredString(known.value.issued_at);
  if (!issuedAt.ok) return issuedAt;
  const created = requiredBoolean(known.value.created);
  if (!created.ok) return created;
  if (receiptId.value.length === 0) {
    return fail("a required field was missing");
  }
  return {
    ok: true,
    value: {
      receipt_id: receiptId.value,
      capture_id: captureId.value,
      version_id: versionId.value,
      version_number: versionNumber.value,
      idempotency_key: idempotencyKey.value,
      content_sha256: digest.value,
      issued_at: issuedAt.value,
      created: created.value,
    },
  };
};
