/**
 * Runtime decode of Python `ProblemDetail`.
 *
 * Maps onto the web `ErrorEnvelope` vocabulary. Unknown extra keys are
 * ignored. `safe_details` is never copied into the error body.
 *
 * WP06-E: rate_limited HTTP status stays 503 until Worker E.
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

export interface DecodedProblem {
  readonly code: string;
  readonly message: string;
  readonly correlationId?: string;
}

const PROBLEM_KEYS = ["code", "message", "correlation_id"] as const;

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
  return ok(
    correlation.value === undefined
      ? { code: known.code, message }
      : { code: known.code, message, correlationId: correlation.value },
  );
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
  // WP06-E: rate_limited HTTP status stays 503 until Worker E
  rate_limited: "unavailable",
  unsupported: "unavailable",
  unavailable: "unavailable",
  internal_error: "internal",
};
