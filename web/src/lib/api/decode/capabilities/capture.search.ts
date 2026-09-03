import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredInt,
  requiredString,
} from "./_read-helpers";

export interface CaptureSearchMatch {
  readonly capture_id: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly character_count: number;
  readonly recorded_at: string;
}

export interface CaptureSearchResult {
  readonly matches: readonly CaptureSearchMatch[];
  readonly searchable_versions: number;
  readonly stored_versions: number;
}

const MATCH_KEYS = [
  "capture_id",
  "version_id",
  "version_number",
  "character_count",
  "recorded_at",
] as const;

function decodeMatch(input: unknown): DecodeResult<CaptureSearchMatch> {
  const known = pick(input, MATCH_KEYS);
  if (!known.ok) return known;
  const captureId = requiredString(known.value.capture_id);
  if (!captureId.ok) return captureId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const versionNumber = requiredInt(known.value.version_number);
  if (!versionNumber.ok) return versionNumber;
  const characterCount = requiredInt(known.value.character_count);
  if (!characterCount.ok) return characterCount;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    capture_id: captureId.value,
    version_id: versionId.value,
    version_number: versionNumber.value,
    character_count: characterCount.value,
    recorded_at: recordedAt.value,
  });
}

export const decodeCaptureSearch: Decoder<CaptureSearchResult> = (input) => {
  const known = pick(input, ["matches", "searchable_versions", "stored_versions"]);
  if (!known.ok) return known;
  if (known.value.matches === undefined) return fail("a required array was omitted");
  const matches = decodeItems(known.value.matches, decodeMatch);
  if (!matches.ok) return matches;
  const searchable = requiredInt(known.value.searchable_versions);
  if (!searchable.ok) return searchable;
  const stored = requiredInt(known.value.stored_versions);
  if (!stored.ok) return stored;
  return ok({
    matches: matches.value,
    searchable_versions: searchable.value,
    stored_versions: stored.value,
  });
};
