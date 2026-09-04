import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export const RESOLVER_MEMBER_STATES = [
  "READY",
  "MISSING",
  "PARTIAL",
  "FAILED",
  "STALE",
  "SUPERSEDED",
  "NOT_EXPECTED",
] as const;

export type ResolverMemberState = (typeof RESOLVER_MEMBER_STATES)[number];

export const RESOLVER_AGGREGATES = ["READY", "DEGRADED", "BLOCKED"] as const;

export type ResolverAggregate = (typeof RESOLVER_AGGREGATES)[number];

export interface ResolveSetMember {
  readonly member_id: string;
  readonly readiness: ResolverMemberState;
  readonly required: boolean;
  readonly focus_area_id: string | null;
  readonly source_lane: string | null;
  readonly artifact_id: string | null;
  readonly producer_run_id: string | null;
  readonly content_sha256: string | null;
  readonly committed_at: string | null;
  readonly readiness_reason: string;
}

export interface ReportsResolveSetResult {
  readonly cycle_run_id: string;
  readonly cycle_id: string;
  readonly business_date: string;
  readonly set_id: string;
  readonly aggregate: ResolverAggregate;
  readonly members: readonly ResolveSetMember[];
}

const MEMBER_KEYS = [
  "member_id",
  "focus_area_id",
  "source_lane",
  "readiness",
  "required",
  "artifact_id",
  "producer_run_id",
  "content_sha256",
  "committed_at",
  "readiness_reason",
] as const;

function decodeMember(input: unknown): DecodeResult<ResolveSetMember> {
  const known = pick(input, MEMBER_KEYS);
  if (!known.ok) return known;
  const memberId = requiredString(known.value.member_id);
  if (!memberId.ok) return memberId;
  const readiness = oneOf(known.value.readiness, RESOLVER_MEMBER_STATES);
  if (!readiness.ok) return readiness;
  const required = requiredBoolean(known.value.required);
  if (!required.ok) return required;
  const focusAreaId = requiredNullableString(known.value.focus_area_id);
  if (!focusAreaId.ok) return focusAreaId;
  const sourceLane = requiredNullableString(known.value.source_lane);
  if (!sourceLane.ok) return sourceLane;
  const artifactId = requiredNullableString(known.value.artifact_id);
  if (!artifactId.ok) return artifactId;
  const producerRunId = requiredNullableString(known.value.producer_run_id);
  if (!producerRunId.ok) return producerRunId;
  const digest = requiredNullableString(known.value.content_sha256);
  if (!digest.ok) return digest;
  const committedAt = requiredNullableString(known.value.committed_at);
  if (!committedAt.ok) return committedAt;
  const reason = requiredString(known.value.readiness_reason);
  if (!reason.ok) return reason;
  return ok({
    member_id: memberId.value,
    readiness: readiness.value,
    required: required.value,
    focus_area_id: focusAreaId.value,
    source_lane: sourceLane.value,
    artifact_id: artifactId.value,
    producer_run_id: producerRunId.value,
    content_sha256: digest.value,
    committed_at: committedAt.value,
    readiness_reason: reason.value,
  });
}

export const decodeReportsResolveSet: Decoder<ReportsResolveSetResult> = (input) => {
  const known = pick(input, [
    "cycle_run_id",
    "cycle_id",
    "business_date",
    "set_id",
    "aggregate",
    "members",
  ]);
  if (!known.ok) return known;
  const cycleRunId = requiredString(known.value.cycle_run_id);
  if (!cycleRunId.ok) return cycleRunId;
  const cycleId = requiredString(known.value.cycle_id);
  if (!cycleId.ok) return cycleId;
  const businessDate = requiredString(known.value.business_date);
  if (!businessDate.ok) return businessDate;
  const setId = requiredString(known.value.set_id);
  if (!setId.ok) return setId;
  const aggregate = oneOf(known.value.aggregate, RESOLVER_AGGREGATES);
  if (!aggregate.ok) return aggregate;
  if (known.value.members === undefined) return fail("a required array was omitted");
  const members = decodeItems(known.value.members, decodeMember);
  if (!members.ok) return members;
  return ok({
    cycle_run_id: cycleRunId.value,
    cycle_id: cycleId.value,
    business_date: businessDate.value,
    set_id: setId.value,
    aggregate: aggregate.value,
    members: members.value,
  });
};
