import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredInt,
  requiredString,
} from "./_read-helpers";

export interface CaptureListEntry {
  readonly capture_id: string;
  readonly owner_principal_id: string;
  readonly created_at: string;
  readonly version_count: number;
  readonly latest_version_id: string;
  readonly latest_version_number: number;
  readonly latest_recorded_at: string;
}

export interface CaptureListResult {
  readonly captures: readonly CaptureListEntry[];
}

const ENTRY_KEYS = [
  "capture_id",
  "owner_principal_id",
  "created_at",
  "version_count",
  "latest_version_id",
  "latest_version_number",
  "latest_recorded_at",
] as const;

function decodeEntry(input: unknown): DecodeResult<CaptureListEntry> {
  const known = pick(input, ENTRY_KEYS);
  if (!known.ok) return known;
  const captureId = requiredString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const owner = requiredString(known.value.owner_principal_id);
  if (!owner.ok) return owner;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const versionCount = requiredInt(known.value.version_count);
  if (!versionCount.ok) return versionCount;
  const latestVersionId = requiredString(known.value.latest_version_id);
  if (!latestVersionId.ok) return latestVersionId;
  const latestVersionNumber = requiredInt(known.value.latest_version_number);
  if (!latestVersionNumber.ok) return latestVersionNumber;
  const latestRecordedAt = requiredString(known.value.latest_recorded_at);
  if (!latestRecordedAt.ok) return latestRecordedAt;
  return ok({
    capture_id: captureId.value,
    owner_principal_id: owner.value,
    created_at: createdAt.value,
    version_count: versionCount.value,
    latest_version_id: latestVersionId.value,
    latest_version_number: latestVersionNumber.value,
    latest_recorded_at: latestRecordedAt.value,
  });
}

export const decodeCaptureList: Decoder<CaptureListResult> = (input) => {
  const known = pick(input, ["captures"]);
  if (!known.ok) return known;
  if (known.value.captures === undefined) return fail("a required array was omitted");
  const captures = decodeItems(known.value.captures, decodeEntry);
  if (!captures.ok) return captures;
  return ok({ captures: captures.value });
};
