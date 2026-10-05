/**
 * `knowledge.assertions.read` — one stored Knowledge Assertion (KLP R6 section 10.2).
 *
 * The Review workbench reads the fact a Knowledge decision produced through
 * this capability instead of extraction Reveal (`knowledge.reveal`), which is
 * capture-oriented and refuses every Knowledge identifier. The Python
 * `assertion_view` publishes the fact and its lifecycle and nothing of its
 * evidence; this decoder holds every key to that shape and every token to the
 * Python vocabulary, so a drifted backend is a contract failure, not a render.
 */
import { isRecord, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";
import { KNOWLEDGE_SUBJECT_KINDS } from "./review.list";

export const KNOWLEDGE_VALUE_TYPES = ["text", "datetime"] as const;

export const KNOWLEDGE_ASSERTION_LIFECYCLES = [
  "active",
  "revalidation_required",
  "superseded",
  "archived",
] as const;

export const KNOWLEDGE_EPISTEMIC_STATUSES = [
  "source_observed",
  "principal_asserted",
  "review_accepted",
  "contested",
] as const;

export const KNOWLEDGE_CLASSIFICATIONS = [
  "synthetic_test",
  "private_local",
  "restricted_local",
] as const;

export interface KnowledgeAssertionView {
  readonly assertion_id: string;
  readonly subject_kind: (typeof KNOWLEDGE_SUBJECT_KINDS)[number];
  readonly subject_id: string;
  readonly predicate_code: string;
  readonly predicate_version: number;
  readonly value_type: (typeof KNOWLEDGE_VALUE_TYPES)[number];
  readonly value: string | null;
  readonly qualifier: Readonly<Record<string, unknown>> | null;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly epistemic_status: (typeof KNOWLEDGE_EPISTEMIC_STATUSES)[number];
  readonly classification: (typeof KNOWLEDGE_CLASSIFICATIONS)[number];
  readonly lifecycle: (typeof KNOWLEDGE_ASSERTION_LIFECYCLES)[number];
  readonly version: number;
  readonly supersedes_assertion_id: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface KnowledgeAssertionReadResult {
  readonly assertion: KnowledgeAssertionView;
}

const ASSERTION_KEYS = [
  "assertion_id",
  "subject_kind",
  "subject_id",
  "predicate_code",
  "predicate_version",
  "value_type",
  "value",
  "qualifier",
  "effective_from",
  "effective_to",
  "epistemic_status",
  "classification",
  "lifecycle",
  "version",
  "supersedes_assertion_id",
  "created_at",
  "updated_at",
] as const;

function nullableQualifier(value: unknown): DecodeResult<Readonly<Record<string, unknown>> | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isRecord(value)) return fail("a required field was not the expected type");
  return ok(value);
}

function decodeAssertion(input: unknown): DecodeResult<KnowledgeAssertionView> {
  const known = pick(input, ASSERTION_KEYS);
  if (!known.ok) return known;
  const v = known.value;
  const assertionId = requiredString(v.assertion_id);
  if (!assertionId.ok) return assertionId;
  const subjectKind = oneOf(v.subject_kind, KNOWLEDGE_SUBJECT_KINDS);
  if (!subjectKind.ok) return subjectKind;
  const subjectId = requiredString(v.subject_id);
  if (!subjectId.ok) return subjectId;
  const predicateCode = requiredString(v.predicate_code);
  if (!predicateCode.ok) return predicateCode;
  const predicateVersion = requiredInt(v.predicate_version);
  if (!predicateVersion.ok) return predicateVersion;
  const valueType = oneOf(v.value_type, KNOWLEDGE_VALUE_TYPES);
  if (!valueType.ok) return valueType;
  const value = requiredNullableString(v.value);
  if (!value.ok) return value;
  const qualifier = nullableQualifier(v.qualifier);
  if (!qualifier.ok) return qualifier;
  const effectiveFrom = requiredNullableString(v.effective_from);
  if (!effectiveFrom.ok) return effectiveFrom;
  const effectiveTo = requiredNullableString(v.effective_to);
  if (!effectiveTo.ok) return effectiveTo;
  const epistemic = oneOf(v.epistemic_status, KNOWLEDGE_EPISTEMIC_STATUSES);
  if (!epistemic.ok) return epistemic;
  const classification = oneOf(v.classification, KNOWLEDGE_CLASSIFICATIONS);
  if (!classification.ok) return classification;
  const lifecycle = oneOf(v.lifecycle, KNOWLEDGE_ASSERTION_LIFECYCLES);
  if (!lifecycle.ok) return lifecycle;
  const version = requiredInt(v.version);
  if (!version.ok) return version;
  const supersedes = requiredNullableString(v.supersedes_assertion_id);
  if (!supersedes.ok) return supersedes;
  const createdAt = requiredString(v.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(v.updated_at);
  if (!updatedAt.ok) return updatedAt;
  return ok({
    assertion_id: assertionId.value,
    subject_kind: subjectKind.value,
    subject_id: subjectId.value,
    predicate_code: predicateCode.value,
    predicate_version: predicateVersion.value,
    value_type: valueType.value,
    value: value.value,
    qualifier: qualifier.value,
    effective_from: effectiveFrom.value,
    effective_to: effectiveTo.value,
    epistemic_status: epistemic.value,
    classification: classification.value,
    lifecycle: lifecycle.value,
    version: version.value,
    supersedes_assertion_id: supersedes.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
  });
}

export const decodeKnowledgeAssertionsRead: Decoder<KnowledgeAssertionReadResult> = (input) => {
  const known = pick(input, ["assertion"]);
  if (!known.ok) return known;
  if (known.value.assertion === undefined) return fail("a required object was missing");
  const assertion = decodeAssertion(known.value.assertion);
  if (!assertion.ok) return assertion;
  return ok({ assertion: assertion.value });
};
