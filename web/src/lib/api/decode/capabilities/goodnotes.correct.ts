import { ok } from "../primitives";
import type { Decoder } from "../types";
import { fail, oneOf, pick, requiredBoolean, requiredString } from "./_read-helpers";

export const GOODNOTES_CORRECTION_DISPOSITIONS = ["canonical_revision_appended"] as const;

export type GoodNotesCorrectionDisposition = (typeof GOODNOTES_CORRECTION_DISPOSITIONS)[number];

export interface GoodNotesCorrectResult {
  readonly occurrence_id: string;
  readonly revision_id: string;
  readonly prior_revision_id: string;
  readonly replayed: boolean;
  readonly disposition: GoodNotesCorrectionDisposition;
}

const KEYS = [
  "occurrence_id",
  "revision_id",
  "prior_revision_id",
  "replayed",
  "disposition",
] as const;

export const decodeGoodNotesCorrect: Decoder<GoodNotesCorrectResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const occurrenceId = requiredString(known.value.occurrence_id);
  if (!occurrenceId.ok) return occurrenceId;
  const revisionId = requiredString(known.value.revision_id);
  if (!revisionId.ok) return revisionId;
  const priorRevisionId = requiredString(known.value.prior_revision_id);
  if (!priorRevisionId.ok) return priorRevisionId;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  const disposition = oneOf(known.value.disposition, GOODNOTES_CORRECTION_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  if (occurrenceId.value.length === 0) return fail("a required field was missing");
  return ok({
    occurrence_id: occurrenceId.value,
    revision_id: revisionId.value,
    prior_revision_id: priorRevisionId.value,
    replayed: replayed.value,
    disposition: disposition.value,
  });
};
