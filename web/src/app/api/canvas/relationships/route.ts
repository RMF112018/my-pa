/**
 * Canvas relationship create — one directed edge between two entities.
 *
 * Browser → this BFF → `entities.relationships.create`. Identity is the session,
 * not the body. A stale endpoint version is a typed conflict (409), not a
 * silent overwrite.
 */
import { type NextRequest } from "next/server";
import { invokeGateway } from "@/lib/api/gateway";
import { RELATIONSHIP_TYPES } from "@/lib/api/decode/capabilities/_entity-read-helpers";
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
} from "./_shared";

const ALLOWED_KEYS = [
  "from_entity_id",
  "to_entity_id",
  "relationship_type",
  "expected_from_version",
  "expected_to_version",
  "idempotency_key",
  "scope_entity_id",
  "expected_scope_version",
  "effective_from",
  "effective_to",
  "evidence_refs",
] as const;

function parseRelationshipType(value: unknown): (typeof RELATIONSHIP_TYPES)[number] | null {
  if (typeof value !== "string") return null;
  for (const candidate of RELATIONSHIP_TYPES) {
    if (value === candidate) return candidate;
  }
  return null;
}

export async function POST(request: NextRequest) {
  const admitted = await admitRelationshipWrite(request);
  if (!admitted.ok) return admitted.response;

  const unexpected = refuseUnknownKeys(admitted.value.body, ALLOWED_KEYS);
  if (unexpected) return unexpected;

  const fromEntityId = requiredNonEmptyString(admitted.value.body["from_entity_id"]);
  if (fromEntityId === null) {
    return refuse("invalid_from_entity_id", "from_entity_id must be a non-empty string");
  }
  const toEntityId = requiredNonEmptyString(admitted.value.body["to_entity_id"]);
  if (toEntityId === null) {
    return refuse("invalid_to_entity_id", "to_entity_id must be a non-empty string");
  }
  if (fromEntityId === toEntityId) {
    return refuse("invalid_to_entity_id", "to_entity_id must differ from from_entity_id");
  }

  const relationshipType = parseRelationshipType(admitted.value.body["relationship_type"]);
  if (relationshipType === null) {
    return refuse("invalid_relationship_type", "relationship_type must be an admitted relationship type");
  }

  const expectedFromVersion = requiredVersion(admitted.value.body["expected_from_version"]);
  if (expectedFromVersion === null) {
    return refuse("invalid_expected_from_version", "expected_from_version must be an integer >= 1");
  }
  const expectedToVersion = requiredVersion(admitted.value.body["expected_to_version"]);
  if (expectedToVersion === null) {
    return refuse("invalid_expected_to_version", "expected_to_version must be an integer >= 1");
  }

  const idempotencyKey = requiredNonEmptyString(admitted.value.body["idempotency_key"]);
  if (idempotencyKey === null) {
    return refuse("invalid_idempotency_key", "idempotency_key must be a non-empty string");
  }

  const scopeEntityId = optionalNonEmptyString(admitted.value.body["scope_entity_id"]);
  if (scopeEntityId === "invalid") {
    return refuse("invalid_scope_entity_id", "scope_entity_id must be a non-empty string");
  }
  const expectedScopeVersionRaw = admitted.value.body["expected_scope_version"];
  const scopeVersionAbsent =
    expectedScopeVersionRaw === undefined || expectedScopeVersionRaw === null;
  if ((scopeEntityId === undefined) !== scopeVersionAbsent) {
    return refuse(
      "invalid_expected_scope_version",
      "scope_entity_id and expected_scope_version must be supplied together",
    );
  }
  let expectedScopeVersion: number | undefined;
  if (!scopeVersionAbsent) {
    const parsedScopeVersion = requiredVersion(expectedScopeVersionRaw);
    if (parsedScopeVersion === null) {
      return refuse("invalid_expected_scope_version", "expected_scope_version must be an integer >= 1");
    }
    expectedScopeVersion = parsedScopeVersion;
  }

  const effectiveFrom = optionalNonEmptyString(admitted.value.body["effective_from"]);
  if (effectiveFrom === "invalid") {
    return refuse("invalid_effective_from", "effective_from must be a non-empty string");
  }
  const effectiveTo = optionalNonEmptyString(admitted.value.body["effective_to"]);
  if (effectiveTo === "invalid") {
    return refuse("invalid_effective_to", "effective_to must be a non-empty string");
  }

  const evidenceRefs = optionalEvidenceRefs(admitted.value.body["evidence_refs"]);
  if (evidenceRefs === "invalid") {
    return refuse("invalid_evidence_refs", "evidence_refs must be an array of non-empty strings");
  }

  const serving = backendOrRefuse();
  if (serving) return serving;

  const payload: Record<string, unknown> = {
    from_entity_id: fromEntityId,
    to_entity_id: toEntityId,
    relationship_type: relationshipType,
    expected_from_version: expectedFromVersion,
    expected_to_version: expectedToVersion,
    idempotency_key: idempotencyKey,
  };
  if (scopeEntityId !== undefined) payload.scope_entity_id = scopeEntityId;
  if (expectedScopeVersion !== undefined) payload.expected_scope_version = expectedScopeVersion;
  if (effectiveFrom !== undefined) payload.effective_from = effectiveFrom;
  if (effectiveTo !== undefined) payload.effective_to = effectiveTo;
  if (evidenceRefs !== undefined) payload.evidence_refs = evidenceRefs;

  const outcome = await invokeGateway(
    admitted.value.principal,
    "entities.relationships.create",
    payload,
  );
  if (!outcome.ok) return refusedGateway(outcome.status, outcome.error);
  return writeReceiptJson(outcome.result);
}
