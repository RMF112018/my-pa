/**
 * Explicit type guards for BFF decoding. No schema library; unknown extra
 * keys are ignored by reading only the known keys a decoder names.
 *
 * Failure messages are caller-safe: they never echo the raw input.
 */

export type DecodeResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly code: string; readonly message: string };

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

export function isFiniteInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && Number.isFinite(value);
}

export function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every(isString);
}

/** Treat missing and `null` as absent; otherwise run `decode`. */
export function optional<T>(
  value: unknown,
  decode: (present: unknown) => DecodeResult<T>,
): DecodeResult<T | undefined> {
  if (value === undefined || value === null) return { ok: true, value: undefined };
  return decode(value);
}

/**
 * Ignore unknown extra keys by copying only `knownKeys`. Decoders must still
 * treat required known fields strictly on the returned object.
 */
export function ignoreUnknownKeys(
  input: Record<string, unknown>,
  knownKeys: readonly string[],
): Record<string, unknown> {
  const picked: Record<string, unknown> = {};
  for (const key of knownKeys) {
    if (Object.prototype.hasOwnProperty.call(input, key)) {
      picked[key] = input[key];
    }
  }
  return picked;
}

export function closed(code: string, message: string): DecodeResult<never> {
  return { ok: false, code, message };
}

export function ok<T>(value: T): DecodeResult<T> {
  return { ok: true, value };
}
