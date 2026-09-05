/**
 * Shared directed-write receipt for the three relationship mutations.
 *
 * Python answers all three through `ApplicationService._directed_receipt`.
 * The payload is identical, so one decoder is registered under three keys.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  oneOf,
  pick,
  requiredBoolean,
  requiredIntGe,
  requiredNullableString,
  requiredString,
} from "./_mutation-helpers";
import { requiredNullableInt } from "./_read-helpers";

export const DIRECTED_RELATIONSHIP_STATES = ["active", "ended", "superseded"] as const;
export type DirectedRelationshipState = (typeof DIRECTED_RELATIONSHIP_STATES)[number];

export const RELATIONSHIP_RECORD_FAMILY = "relationship" as const;

export interface DirectedRelationshipWriteResult {
  readonly record_id: string;
  readonly record_family: typeof RELATIONSHIP_RECORD_FAMILY;
  readonly prior_version: number | null;
  readonly version: number;
  readonly state: DirectedRelationshipState;
  readonly receipt_id: string;
  readonly audit_id: string;
  readonly idempotency_key: string;
  readonly superseded_id: string | null;
  readonly evidence_refs: readonly string[];
  readonly replayed: boolean;
  readonly issued_at: string;
}

const KEYS = [
  "record_id",
  "record_family",
  "prior_version",
  "version",
  "state",
  "receipt_id",
  "audit_id",
  "idempotency_key",
  "superseded_id",
  "evidence_refs",
  "replayed",
  "issued_at",
] as const;

export const decodeDirectedRelationshipWrite: Decoder<DirectedRelationshipWriteResult> = (
  input,
) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const recordId = requiredString(known.value.record_id);
  if (!recordId.ok) return recordId;
  const recordFamily = oneOf(known.value.record_family, [RELATIONSHIP_RECORD_FAMILY]);
  if (!recordFamily.ok) return recordFamily;
  const priorVersion = requiredNullableInt(known.value.prior_version);
  if (!priorVersion.ok) return priorVersion;
  const version = requiredIntGe(known.value.version, 1);
  if (!version.ok) return version;
  const state = oneOf(known.value.state, DIRECTED_RELATIONSHIP_STATES);
  if (!state.ok) return state;
  const receiptId = requiredString(known.value.receipt_id);
  if (!receiptId.ok) return receiptId;
  const auditId = requiredString(known.value.audit_id);
  if (!auditId.ok) return auditId;
  const idempotencyKey = requiredString(known.value.idempotency_key);
  if (!idempotencyKey.ok) return idempotencyKey;
  const supersededId = requiredNullableString(known.value.superseded_id);
  if (!supersededId.ok) return supersededId;
  const evidenceRefs = decodeItems(known.value.evidence_refs, requiredString);
  if (!evidenceRefs.ok) return evidenceRefs;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  const issuedAt = requiredString(known.value.issued_at);
  if (!issuedAt.ok) return issuedAt;
  return ok({
    record_id: recordId.value,
    record_family: recordFamily.value,
    prior_version: priorVersion.value,
    version: version.value,
    state: state.value,
    receipt_id: receiptId.value,
    audit_id: auditId.value,
    idempotency_key: idempotencyKey.value,
    superseded_id: supersededId.value,
    evidence_refs: evidenceRefs.value,
    replayed: replayed.value,
    issued_at: issuedAt.value,
  });
};
