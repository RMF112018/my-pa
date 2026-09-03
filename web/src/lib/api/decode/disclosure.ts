/**
 * Runtime decode of the Python `Disclosure` known fields.
 *
 * Required known fields are strict. Unknown extra keys (`scope`,
 * `source_references`, `classification`, `cloud_eligible`, coverage counts,
 * `truncation.reason`, …) are ignored. Invalid enums and missing required
 * fields fail closed. Nothing here defaults coverage to complete or trust to
 * `"derived"`.
 */
import {
  closed,
  ignoreUnknownKeys,
  isBoolean,
  isRecord,
  isString,
  isStringArray,
  ok,
  optional,
  type DecodeResult,
} from "./primitives";

export const COVERAGE_STATES = [
  "not_enrolled",
  "eligible",
  "queued",
  "processed",
  "partially_processed",
  "unsupported",
  "quarantined",
  "unavailable",
  "stale",
  "superseded",
] as const;

export type CoverageState = (typeof COVERAGE_STATES)[number];

export const FRESHNESS_STATES = ["current_for_observed_version", "stale", "unknown"] as const;

export type FreshnessState = (typeof FRESHNESS_STATES)[number];

export const TRUST_LEVELS = ["source_original", "source_bound_derived", "model_proposed"] as const;

export type TrustLevel = (typeof TRUST_LEVELS)[number];

export interface DecodedDisclosure {
  readonly coverage: { readonly state: CoverageState };
  readonly freshness: { readonly observed_at: string; readonly state: FreshnessState };
  readonly trust: { readonly level: TrustLevel; readonly basis: readonly string[] };
  readonly truncation: { readonly is_truncated: boolean; readonly next_cursor?: string };
  readonly limitations: readonly string[];
  readonly partial_result: boolean;
}

const DISCLOSURE_KEYS = [
  "coverage",
  "freshness",
  "trust",
  "truncation",
  "limitations",
  "partial_result",
] as const;

const INVALID = "upstream_contract_invalid";

function oneOf<T extends string>(
  value: unknown,
  allowed: readonly T[],
): DecodeResult<T> {
  if (isString(value)) {
    for (const candidate of allowed) {
      if (value === candidate) return ok(candidate);
    }
  }
  return closed(INVALID, "a required field was not an allowed value");
}

function decodeCoverage(value: unknown): DecodeResult<{ state: CoverageState }> {
  if (!isRecord(value)) {
    return closed(INVALID, "disclosure coverage was missing or unreadable");
  }
  const known = ignoreUnknownKeys(value, ["state"]);
  const state = oneOf(known.state, COVERAGE_STATES);
  if (!state.ok) return state;
  return ok({ state: state.value });
}

function decodeFreshness(
  value: unknown,
): DecodeResult<{ observed_at: string; state: FreshnessState }> {
  if (!isRecord(value)) {
    return closed(INVALID, "disclosure freshness was missing or unreadable");
  }
  const known = ignoreUnknownKeys(value, ["observed_at", "state"]);
  if (!isString(known.observed_at)) {
    return closed(INVALID, "a required disclosure field was missing");
  }
  const state = oneOf(known.state, FRESHNESS_STATES);
  if (!state.ok) return state;
  return ok({ observed_at: known.observed_at, state: state.value });
}

function decodeTrust(
  value: unknown,
): DecodeResult<{ level: TrustLevel; basis: readonly string[] }> {
  if (!isRecord(value)) {
    return closed(INVALID, "disclosure trust was missing or unreadable");
  }
  const known = ignoreUnknownKeys(value, ["level", "basis"]);
  const level = oneOf(known.level, TRUST_LEVELS);
  if (!level.ok) return level;
  if (!isStringArray(known.basis)) {
    return closed(INVALID, "a required disclosure field was missing");
  }
  return ok({ level: level.value, basis: known.basis });
}

function decodeTruncation(
  value: unknown,
): DecodeResult<{ is_truncated: boolean; next_cursor?: string }> {
  if (!isRecord(value)) {
    return closed(INVALID, "disclosure truncation was missing or unreadable");
  }
  const known = ignoreUnknownKeys(value, ["is_truncated", "next_cursor"]);
  if (!isBoolean(known.is_truncated)) {
    return closed(INVALID, "a required disclosure field was missing");
  }
  const cursor = optional(known.next_cursor, (present) =>
    isString(present)
      ? ok(present)
      : closed(INVALID, "a disclosure field was not the expected type"),
  );
  if (!cursor.ok) return cursor;
  return ok(
    cursor.value === undefined
      ? { is_truncated: known.is_truncated }
      : { is_truncated: known.is_truncated, next_cursor: cursor.value },
  );
}

export function decodeDisclosure(input: unknown): DecodeResult<DecodedDisclosure> {
  if (!isRecord(input)) {
    return closed(INVALID, "disclosure was missing or unreadable");
  }
  const known = ignoreUnknownKeys(input, DISCLOSURE_KEYS);
  const coverage = decodeCoverage(known.coverage);
  if (!coverage.ok) return coverage;
  const freshness = decodeFreshness(known.freshness);
  if (!freshness.ok) return freshness;
  const trust = decodeTrust(known.trust);
  if (!trust.ok) return trust;
  const truncation = decodeTruncation(known.truncation);
  if (!truncation.ok) return truncation;
  if (!isStringArray(known.limitations)) {
    return closed(INVALID, "a required disclosure field was missing");
  }
  if (!isBoolean(known.partial_result)) {
    return closed(INVALID, "a required disclosure field was missing");
  }
  return ok({
    coverage: coverage.value,
    freshness: freshness.value,
    trust: trust.value,
    truncation: truncation.value,
    limitations: known.limitations,
    partial_result: known.partial_result,
  });
}
