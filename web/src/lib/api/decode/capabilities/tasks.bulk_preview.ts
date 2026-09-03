import { ok } from "../primitives";
import type { Decoder } from "../types";
import { pick, requiredBoolean, requiredIntGe, requiredString } from "./_mutation-helpers";

export interface TasksBulkPreviewResult {
  readonly bulk_operation_id: string;
  readonly expires_at: string;
  readonly affected: number;
  readonly no_op: number;
  readonly rejected: number;
  readonly replayed: boolean;
}

const KEYS = [
  "bulk_operation_id",
  "expires_at",
  "affected",
  "no_op",
  "rejected",
  "replayed",
] as const;

export const decodeTasksBulkPreview: Decoder<TasksBulkPreviewResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const id = requiredString(known.value.bulk_operation_id);
  if (!id.ok) return id;
  const expiresAt = requiredString(known.value.expires_at);
  if (!expiresAt.ok) return expiresAt;
  const affected = requiredIntGe(known.value.affected, 0);
  if (!affected.ok) return affected;
  const noOp = requiredIntGe(known.value.no_op, 0);
  if (!noOp.ok) return noOp;
  const rejected = requiredIntGe(known.value.rejected, 0);
  if (!rejected.ok) return rejected;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  return ok({
    bulk_operation_id: id.value,
    expires_at: expiresAt.value,
    affected: affected.value,
    no_op: noOp.value,
    rejected: rejected.value,
    replayed: replayed.value,
  });
};
