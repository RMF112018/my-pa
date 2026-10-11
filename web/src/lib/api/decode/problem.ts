/**
 * Runtime decode of Python `ProblemDetail`.
 *
 * Maps onto the web `ErrorEnvelope` vocabulary. Unknown extra keys are
 * ignored. `safe_details` is never copied into the error body; it is read only
 * to check that each `allowed_values` entry names one of its tokens.
 *
 * `allowed_values` is an optional hint on `invalid_request`: the closed
 * vocabulary a rejected field accepts. It is decoded lossily on purpose. A
 * malformed hint drops (the offending entry, or the whole list when the list
 * itself is out of contract) and never turns an otherwise readable refusal into
 * `upstream_contract_invalid`, which would hide the real validation error.
 * Nothing unvalidated is kept: every surviving entry matches the Python
 * `AllowedValues` bounds exactly.
 *
 * `rate_limited` stays errorClass `unavailable` (no ninth class). HTTP 429
 * is applied by `httpStatusForProblem`, not by widening the class map.
 */
import type { ErrorEnvelope } from "@/contracts/envelope";
import {
  closed,
  ignoreUnknownKeys,
  isRecord,
  isString,
  ok,
  optional,
  type DecodeResult,
} from "./primitives";

export const ERROR_CODES = [
  "invalid_request",
  "ambiguous_request",
  "denied",
  "unavailable",
  "unsupported",
  "not_found",
  "conflict",
  "rate_limited",
  "quarantined",
  "cancelled",
  "internal_error",
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export interface AllowedValues {
  /** The `safe_details` token naming the rejected field. */
  readonly detail: string;
  /** The vocabulary's members in declaration order (1..64 code tokens). */
  readonly values: readonly string[];
  /** True when `values` is a prefix of a longer vocabulary. */
  readonly truncated: boolean;
}

export interface DecodedProblem {
  readonly code: string;
  readonly message: string;
  readonly correlationId?: string;
  /** Only on `invalid_request`; omitted when absent, empty, or wholly malformed. */
  readonly allowedValues?: readonly AllowedValues[];
}

const PROBLEM_KEYS = [
  "code",
  "message",
  "correlation_id",
  "safe_details",
  "allowed_values",
] as const;

/** Python `_SAFE_DETAIL_PATTERN`. */
const SAFE_DETAIL_PATTERN = /^[a-z][a-z0-9_.]{0,63}$/;
/** Python `_ALLOWED_VALUE_PATTERN`. */
const ALLOWED_VALUE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
/** Python `MAX_ALLOWED_VALUE_ENTRIES` (the `safe_details` bound). */
export const MAX_ALLOWED_VALUE_ENTRIES = 16;
/** Python `MAX_ALLOWED_VALUES`. */
export const MAX_ALLOWED_VALUES = 64;

const ALLOWED_VALUE_KEYS = ["detail", "values", "truncated"] as const;

function decodeAllowedValuesEntry(
  input: unknown,
  safeDetails: ReadonlySet<string>,
): AllowedValues | undefined {
  if (!isRecord(input)) return undefined;
  const known = ignoreUnknownKeys(input, ALLOWED_VALUE_KEYS);
  const { detail, values, truncated } = known;
  if (!isString(detail) || !SAFE_DETAIL_PATTERN.test(detail)) return undefined;
  if (!safeDetails.has(detail)) return undefined;
  if (typeof truncated !== "boolean") return undefined;
  if (!Array.isArray(values)) return undefined;
  if (values.length < 1 || values.length > MAX_ALLOWED_VALUES) return undefined;
  const listed: string[] = [];
  for (const value of values) {
    if (!isString(value) || !ALLOWED_VALUE_PATTERN.test(value)) return undefined;
    listed.push(value);
  }
  if (new Set(listed).size !== listed.length) return undefined;
  return { detail, values: listed, truncated };
}

/**
 * Lossy decode of `allowed_values`. Returns `undefined` (field omitted) for any
 * code but `invalid_request`, a non-array, an over-long list, or no surviving
 * entry; otherwise the well-formed entries whose detail is a `safe_details`
 * token, first occurrence per detail.
 */
function decodeAllowedValues(
  code: string,
  raw: unknown,
  safeDetailsRaw: unknown,
): readonly AllowedValues[] | undefined {
  if (raw === undefined || code !== "invalid_request") return undefined;
  if (!Array.isArray(raw) || raw.length > MAX_ALLOWED_VALUE_ENTRIES) return undefined;
  const safeDetails = new Set(
    Array.isArray(safeDetailsRaw)
      ? safeDetailsRaw.filter(
          (item): item is string => isString(item) && SAFE_DETAIL_PATTERN.test(item),
        )
      : [],
  );
  const seen = new Set<string>();
  const entries: AllowedValues[] = [];
  for (const item of raw) {
    const entry = decodeAllowedValuesEntry(item, safeDetails);
    if (entry === undefined || seen.has(entry.detail)) continue;
    seen.add(entry.detail);
    entries.push(entry);
  }
  return entries.length > 0 ? entries : undefined;
}

const INVALID = "upstream_contract_invalid";

export function decodeProblem(input: unknown): DecodeResult<DecodedProblem> {
  if (!isRecord(input)) {
    return closed(INVALID, "the gateway problem was unreadable");
  }
  const known = ignoreUnknownKeys(input, PROBLEM_KEYS);
  if (!isString(known.code)) {
    return closed(INVALID, "the gateway problem was unreadable");
  }
  const message = isString(known.message) ? known.message : "the gateway refused the request";
  const correlation = optional(known.correlation_id, (present) =>
    isString(present)
      ? ok(present)
      : closed(INVALID, "the gateway problem was unreadable"),
  );
  if (!correlation.ok) return correlation;
  const allowedValues = decodeAllowedValues(
    known.code,
    known.allowed_values,
    known.safe_details,
  );
  return ok({
    code: known.code,
    message,
    ...(correlation.value === undefined ? {} : { correlationId: correlation.value }),
    ...(allowedValues === undefined ? {} : { allowedValues }),
  });
}

/** The eleven Python error codes, mapped onto the web tier's error vocabulary. */
export const PROBLEM_ERROR_CLASS: Record<string, ErrorEnvelope["errorClass"]> = {
  invalid_request: "validation",
  ambiguous_request: "validation",
  denied: "authorization",
  quarantined: "policy_denied",
  not_found: "not_found",
  conflict: "conflict",
  cancelled: "conflict",
  rate_limited: "unavailable",
  unsupported: "unavailable",
  unavailable: "unavailable",
  internal_error: "internal",
};

/**
 * HTTP status override keyed by Python code, not errorClass.
 *
 * `statusForErrorClass` cannot express 429 while `rate_limited` remains
 * `unavailable` (503). Callers apply this before the class table.
 */
export function httpStatusForProblem(code: string): number | undefined {
  return code === "rate_limited" ? 429 : undefined;
}
