import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  oneOf,
  pick,
  requiredBoolean,
  requiredInt,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export const CAPTURE_CLASSIFICATIONS = [
  "synthetic_test",
  "private_local",
  "restricted_local",
] as const;

export const CAPTURE_PROCESSING_POLICIES = ["local_only"] as const;

export type CaptureClassification = (typeof CAPTURE_CLASSIFICATIONS)[number];
export type CaptureProcessingPolicy = (typeof CAPTURE_PROCESSING_POLICIES)[number];

/** One stored version as `capture.read` publishes it, including canonical `text`. */
export interface CaptureReadResult {
  readonly capture_id: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly supersedes_version_id: string | null;
  readonly is_current: boolean;
  readonly owner_principal_id: string;
  readonly classification: CaptureClassification;
  readonly processing_policy: CaptureProcessingPolicy;
  readonly content_sha256: string;
  readonly character_count: number;
  readonly text: string;
  readonly is_truncated: boolean;
  readonly client_created_at: string | null;
  readonly server_received_at: string;
  readonly occurred_at: string | null;
  readonly accepted_at: string;
  readonly recorded_at: string;
}

const VERSION_KEYS = [
  "capture_id",
  "version_id",
  "version_number",
  "supersedes_version_id",
  "is_current",
  "owner_principal_id",
  "classification",
  "processing_policy",
  "content_sha256",
  "character_count",
  "text",
  "is_truncated",
  "client_created_at",
  "server_received_at",
  "occurred_at",
  "accepted_at",
  "recorded_at",
] as const;

export const decodeCaptureRead: Decoder<CaptureReadResult> = (input) => {
  const known = pick(input, VERSION_KEYS);
  if (!known.ok) return known;
  const captureId = requiredString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const versionNumber = requiredInt(known.value.version_number);
  if (!versionNumber.ok) return versionNumber;
  const supersedes = requiredNullableString(known.value.supersedes_version_id);
  if (!supersedes.ok) return supersedes;
  const isCurrent = requiredBoolean(known.value.is_current);
  if (!isCurrent.ok) return isCurrent;
  const owner = requiredString(known.value.owner_principal_id);
  if (!owner.ok) return owner;
  const classification = oneOf(known.value.classification, CAPTURE_CLASSIFICATIONS);
  if (!classification.ok) return classification;
  const processingPolicy = oneOf(known.value.processing_policy, CAPTURE_PROCESSING_POLICIES);
  if (!processingPolicy.ok) return processingPolicy;
  const digest = requiredString(known.value.content_sha256);
  if (!digest.ok) return digest;
  const characterCount = requiredInt(known.value.character_count);
  if (!characterCount.ok) return characterCount;
  const text = requiredString(known.value.text);
  if (!text.ok) return text;
  const truncated = requiredBoolean(known.value.is_truncated);
  if (!truncated.ok) return truncated;
  const clientCreatedAt = requiredNullableString(known.value.client_created_at);
  if (!clientCreatedAt.ok) return clientCreatedAt;
  const serverReceivedAt = requiredString(known.value.server_received_at);
  if (!serverReceivedAt.ok) return serverReceivedAt;
  const occurredAt = requiredNullableString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const acceptedAt = requiredString(known.value.accepted_at);
  if (!acceptedAt.ok) return acceptedAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    capture_id: captureId.value,
    version_id: versionId.value,
    version_number: versionNumber.value,
    supersedes_version_id: supersedes.value,
    is_current: isCurrent.value,
    owner_principal_id: owner.value,
    classification: classification.value,
    processing_policy: processingPolicy.value,
    content_sha256: digest.value,
    character_count: characterCount.value,
    text: text.value,
    is_truncated: truncated.value,
    client_created_at: clientCreatedAt.value,
    server_received_at: serverReceivedAt.value,
    occurred_at: occurredAt.value,
    accepted_at: acceptedAt.value,
    recorded_at: recordedAt.value,
  });
};
