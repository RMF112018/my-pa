/**
 * Canvas relationship revise — correct when an existing edge applies.
 *
 * Browser → this BFF → `entities.relationships.revise`. Identity is the session,
 * not the body. A stale expected_version is a typed conflict (409), not a
 * silent overwrite.
 */
import { type NextRequest } from "next/server";
import { invokeGateway } from "@/lib/api/gateway";
import {
  admitRelationshipWrite,
  backendOrRefuse,
  optionalEvidenceRefs,
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
  "idempotency_key",
  "effective_from",
  "effective_to",
  "clear",
  "evidence_refs",
] as const;

type ClearableField = "effective_from" | "effective_to";

function parseClear(value: unknown): readonly ClearableField[] | undefined | "invalid" {
  if (value === undefined || value === null) return undefined;
  if (!Array.isArray(value)) return "invalid";
  const names: ClearableField[] = [];
  for (const item of value) {
    if (item !== "effective_from" && item !== "effective_to") return "invalid";
    if (names.includes(item)) return "invalid";
    names.push(item);
  }
  return names;
}

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

  const idempotencyKey = requiredNonEmptyString(admitted.value.body["idempotency_key"]);
  if (idempotencyKey === null) {
    return refuse("invalid_idempotency_key", "idempotency_key must be a non-empty string");
  }

  const effectiveFrom = optionalNonEmptyString(admitted.value.body["effective_from"]);
  if (effectiveFrom === "invalid") {
    return refuse("invalid_effective_from", "effective_from must be a non-empty string");
  }
  const effectiveTo = optionalNonEmptyString(admitted.value.body["effective_to"]);
  if (effectiveTo === "invalid") {
    return refuse("invalid_effective_to", "effective_to must be a non-empty string");
  }

  const clear = parseClear(admitted.value.body["clear"]);
  if (clear === "invalid") {
    return refuse("invalid_clear", "clear must be a unique subset of effective_from, effective_to");
  }
  if (clear !== undefined) {
    if (effectiveFrom !== undefined && clear.includes("effective_from")) {
      return refuse("invalid_effective_from", "effective_from cannot be stated and cleared together");
    }
    if (effectiveTo !== undefined && clear.includes("effective_to")) {
      return refuse("invalid_effective_to", "effective_to cannot be stated and cleared together");
    }
  }

  if (!("evidence_refs" in admitted.value.body)) {
    return refuse(
      "missing_evidence_refs",
      "evidence_refs must be stated; omitting it would replace existing citations with none",
    );
  }
  const evidenceRefs = optionalEvidenceRefs(admitted.value.body["evidence_refs"]);
  if (evidenceRefs === undefined || evidenceRefs === "invalid") {
    return refuse("invalid_evidence_refs", "evidence_refs must be an array of non-empty strings");
  }

  const serving = backendOrRefuse();
  if (serving) return serving;

  const payload: Record<string, unknown> = {
    relationship_id: relationshipId,
    expected_version: expectedVersion,
    idempotency_key: idempotencyKey,
    evidence_refs: evidenceRefs,
  };
  if (effectiveFrom !== undefined) payload.effective_from = effectiveFrom;
  if (effectiveTo !== undefined) payload.effective_to = effectiveTo;
  if (clear !== undefined) payload.clear = clear;

  const outcome = await invokeGateway(
    admitted.value.principal,
    "entities.relationships.revise",
    payload,
  );
  if (!outcome.ok) return refusedGateway(outcome.status, outcome.error);
  return writeReceiptJson(outcome.result);
}
