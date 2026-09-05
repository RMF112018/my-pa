/**
 * Canvas relationship end — record that a directed edge stopped holding.
 *
 * Browser → this BFF → `entities.relationships.end`. Identity is the session,
 * not the body. A stale expected_version is a typed conflict (409), not a
 * silent overwrite. `end_now` and `effective_end` are exclusive, matching
 * Python `(effective_end is None) is not end_now`.
 */
import { type NextRequest } from "next/server";
import { invokeGateway } from "@/lib/api/gateway";
import {
  admitRelationshipWrite,
  backendOrRefuse,
  optionalNonEmptyString,
  refuse,
  refuseUnknownKeys,
  refusedGateway,
  requiredNonEmptyString,
  requiredVersion,
  writeReceiptJson,
} from "../_shared";

const ALLOWED_KEYS = [
  "relationship_id",
  "expected_version",
  "reason",
  "idempotency_key",
  "effective_end",
  "end_now",
] as const;

export async function POST(request: NextRequest) {
  const admitted = await admitRelationshipWrite(request);
  if (!admitted.ok) return admitted.response;

  const unexpected = refuseUnknownKeys(admitted.value.body, ALLOWED_KEYS);
  if (unexpected) return unexpected;

  const relationshipId = requiredNonEmptyString(admitted.value.body["relationship_id"]);
  if (relationshipId === null) {
    return refuse("invalid_relationship_id", "relationship_id must be a non-empty string");
  }

  const expectedVersion = requiredVersion(admitted.value.body["expected_version"]);
  if (expectedVersion === null) {
    return refuse("invalid_expected_version", "expected_version must be an integer >= 1");
  }

  const reason = requiredNonEmptyString(admitted.value.body["reason"]);
  if (reason === null) {
    return refuse("invalid_reason", "reason must be a non-empty string");
  }

  const idempotencyKey = requiredNonEmptyString(admitted.value.body["idempotency_key"]);
  if (idempotencyKey === null) {
    return refuse("invalid_idempotency_key", "idempotency_key must be a non-empty string");
  }

  const endNowRaw = admitted.value.body["end_now"];
  if (endNowRaw !== undefined && endNowRaw !== null && typeof endNowRaw !== "boolean") {
    return refuse("invalid_end_now", "end_now must be a boolean");
  }
  const endNow = endNowRaw === true;

  const effectiveEnd = optionalNonEmptyString(admitted.value.body["effective_end"]);
  if (effectiveEnd === "invalid") {
    return refuse("invalid_effective_end", "effective_end must be a non-empty string");
  }

  // Python: (effective_end is None) is not end_now — exactly one of the two.
  if ((effectiveEnd === undefined) !== endNow) {
    return refuse("invalid_end_now", "exactly one of end_now or effective_end is required");
  }

  const serving = backendOrRefuse();
  if (serving) return serving;

  const payload: Record<string, unknown> = {
    relationship_id: relationshipId,
    expected_version: expectedVersion,
    reason,
    idempotency_key: idempotencyKey,
  };
  if (endNow) {
    payload.end_now = true;
  } else if (effectiveEnd !== undefined) {
    payload.effective_end = effectiveEnd;
  }

  const outcome = await invokeGateway(
    admitted.value.principal,
    "entities.relationships.end",
    payload,
  );
  if (!outcome.ok) return refusedGateway(outcome.status, outcome.error);
  return writeReceiptJson(outcome.result);
}
