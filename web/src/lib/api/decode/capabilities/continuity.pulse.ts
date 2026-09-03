import { optional, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const PULSE_ITEM_TYPES = [
  "commitment",
  "decision",
  "task",
  "observation",
  "relationship_event",
  "situation",
] as const;

export type PulseItemType = (typeof PULSE_ITEM_TYPES)[number];

export const PULSE_REASON_CODES = [
  "commitment_overdue",
  "commitment_due_soon",
  "task_overdue",
  "task_due_soon",
  "decision_awaiting_authority",
  "situation_obligation_unmet",
] as const;

export type PulseReasonCode = (typeof PULSE_REASON_CODES)[number];

export interface PulseItem {
  readonly pulse_id: string;
  readonly item_type: PulseItemType;
  readonly item_ref: string;
  readonly reason_code: PulseReasonCode;
  readonly reason: string;
  readonly basis_refs: readonly string[];
  readonly consequence: string | null;
  readonly next_step: string | null;
  readonly attention_rank: number;
  readonly generated_at: string;
  readonly subject_title?: string;
  readonly subject_state?: string;
  readonly subject_version?: number;
  readonly subject_priority?: string;
}

export interface ContinuityPulseResult {
  readonly pulse_items: readonly PulseItem[];
}

const ITEM_KEYS = [
  "pulse_id",
  "item_type",
  "item_ref",
  "reason_code",
  "reason",
  "basis_refs",
  "consequence",
  "next_step",
  "attention_rank",
  "generated_at",
  "subject_title",
  "subject_state",
  "subject_version",
  "subject_priority",
] as const;

function decodePulseItem(input: unknown): DecodeResult<PulseItem> {
  const known = pick(input, ITEM_KEYS);
  if (!known.ok) return known;
  const pulseId = requiredString(known.value.pulse_id);
  if (!pulseId.ok) return pulseId;
  const itemType = oneOf(known.value.item_type, PULSE_ITEM_TYPES);
  if (!itemType.ok) return itemType;
  const itemRef = requiredString(known.value.item_ref);
  if (!itemRef.ok) return itemRef;
  const reasonCode = oneOf(known.value.reason_code, PULSE_REASON_CODES);
  if (!reasonCode.ok) return reasonCode;
  const reason = requiredString(known.value.reason);
  if (!reason.ok) return reason;
  const basisRefs = requiredStringArray(known.value.basis_refs);
  if (!basisRefs.ok) return basisRefs;
  const consequence = requiredNullableString(known.value.consequence);
  if (!consequence.ok) return consequence;
  const nextStep = requiredNullableString(known.value.next_step);
  if (!nextStep.ok) return nextStep;
  const attentionRank = requiredInt(known.value.attention_rank);
  if (!attentionRank.ok) return attentionRank;
  const generatedAt = requiredString(known.value.generated_at);
  if (!generatedAt.ok) return generatedAt;
  const subjectTitle = optional(known.value.subject_title, requiredString);
  if (!subjectTitle.ok) return subjectTitle;
  const subjectState = optional(known.value.subject_state, requiredString);
  if (!subjectState.ok) return subjectState;
  const subjectVersion = optional(known.value.subject_version, requiredInt);
  if (!subjectVersion.ok) return subjectVersion;
  const subjectPriority = optional(known.value.subject_priority, requiredString);
  if (!subjectPriority.ok) return subjectPriority;
  return ok({
    pulse_id: pulseId.value,
    item_type: itemType.value,
    item_ref: itemRef.value,
    reason_code: reasonCode.value,
    reason: reason.value,
    basis_refs: basisRefs.value,
    consequence: consequence.value,
    next_step: nextStep.value,
    attention_rank: attentionRank.value,
    generated_at: generatedAt.value,
    ...(subjectTitle.value !== undefined ? { subject_title: subjectTitle.value } : {}),
    ...(subjectState.value !== undefined ? { subject_state: subjectState.value } : {}),
    ...(subjectVersion.value !== undefined ? { subject_version: subjectVersion.value } : {}),
    ...(subjectPriority.value !== undefined ? { subject_priority: subjectPriority.value } : {}),
  });
}

export const decodeContinuityPulse: Decoder<ContinuityPulseResult> = (input) => {
  const known = pick(input, ["pulse_items"]);
  if (!known.ok) return known;
  if (known.value.pulse_items === undefined) {
    return fail("a required array was omitted");
  }
  const items = decodeItems(known.value.pulse_items, decodePulseItem);
  if (!items.ok) return items;
  return ok({ pulse_items: items.value });
};
