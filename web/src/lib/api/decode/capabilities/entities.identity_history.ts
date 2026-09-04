import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredBoolean,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";
import {
  decodeIdentityHistoryEntry,
  type IdentityHistoryEntry,
} from "./_entity-read-helpers";

export type { IdentityHistoryEntry };

export interface EntitiesIdentityHistoryResult {
  readonly entity_id: string;
  readonly entries: readonly IdentityHistoryEntry[];
  readonly is_truncated: boolean;
  readonly next_cursor: string | null;
  readonly audit_id: string;
}

export const decodeEntitiesIdentityHistory: Decoder<EntitiesIdentityHistoryResult> = (input) => {
  const known = pick(input, ["entity_id", "entries", "is_truncated", "next_cursor", "audit_id"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.entries === undefined) return fail("a required array was omitted");
  const entries = decodeItems(known.value.entries, decodeIdentityHistoryEntry);
  if (!entries.ok) return entries;
  const truncated = requiredBoolean(known.value.is_truncated);
  if (!truncated.ok) return truncated;
  const nextCursor = requiredNullableString(known.value.next_cursor);
  if (!nextCursor.ok) return nextCursor;
  const auditId = requiredString(known.value.audit_id);
  if (!auditId.ok) return auditId;
  return ok({
    entity_id: entityId.value,
    entries: entries.value,
    is_truncated: truncated.value,
    next_cursor: nextCursor.value,
    audit_id: auditId.value,
  });
};
