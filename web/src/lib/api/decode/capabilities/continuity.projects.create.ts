import { closed, isRecord, ok } from "../primitives";
import type { Decoder } from "../types";

// Shared only by the twelve closed WP03B success contracts. These validate and
// reconstruct every object rather than dropping unknown upstream fields.
export type Decoded<D> = D extends Decoder<infer T> ? T : never;
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

export function strictObject<S extends Record<string, Decoder<unknown>>>(
  schema: S,
): Decoder<{ readonly [K in keyof S]: Decoded<S[K]> }> {
  return (input) => {
    if (
      !isRecord(input) ||
      Object.keys(input).length !== Object.keys(schema).length ||
      Object.keys(input).some((key) => !Object.hasOwn(schema, key))
    ) return invalid();
    const output: Record<string, unknown> = {};
    for (const key of Object.keys(schema)) {
      if (!Object.hasOwn(input, key)) return invalid();
      const result = schema[key](input[key]);
      if (!result.ok) return result;
      output[key] = result.value;
    }
    return ok(output as { readonly [K in keyof S]: Decoded<S[K]> });
  };
}
export function nullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return (input) => input === null ? ok(null) : decode(input);
}
export function arrayOf<T>(
  decode: Decoder<T>,
  maximum = Number.MAX_SAFE_INTEGER,
): Decoder<readonly T[]> {
  return (input) => {
    if (!Array.isArray(input) || input.length > maximum) return invalid();
    const output: T[] = [];
    for (const item of input) {
      const result = decode(item);
      if (!result.ok) return result;
      output.push(result.value);
    }
    return ok(output);
  };
}
export function checked<T>(decode: Decoder<T>, check: (value: T) => boolean): Decoder<T> {
  return (input) => {
    const result = decode(input);
    return result.ok && !check(result.value) ? invalid() : result;
  };
}
export function text(minimum = 0, maximum = Number.MAX_SAFE_INTEGER): Decoder<string> {
  return (input) => {
    if (typeof input !== "string") return invalid();
    const length = Array.from(input).length;
    return length >= minimum && length <= maximum ? ok(input) : invalid();
  };
}
export function integer(minimum = 0, maximum = Number.MAX_SAFE_INTEGER): Decoder<number> {
  return (input) => typeof input === "number" && Number.isSafeInteger(input) &&
    input >= minimum && input <= maximum ? ok(input) : invalid();
}
export const boolean: Decoder<boolean> = (input) => typeof input === "boolean" ? ok(input) : invalid();
export function enumeration<const V extends readonly string[]>(values: V): Decoder<V[number]> {
  return (input) => typeof input === "string" && values.includes(input) ? ok(input as V[number]) : invalid();
}
export function identifier(prefix: string): Decoder<string> {
  return checked(text(), (value) => new RegExp(`^${prefix}_[A-Za-z0-9]{8,64}$`).exec(value)?.[0] === value);
}
export const digest = checked(text(64, 64), (value) => /^[a-f0-9]{64}$/.test(value));
export const timestamp: Decoder<string> = checked(text(), (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || match[0] !== value) return false;
  const [, year, month, day, hour, minute, second, offset] = match;
  const y = Number(year);
  const m = Number(month);
  const d = Number(day);
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y >= 1 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1] &&
    Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60 &&
    (offset === "Z" || (Number(offset.slice(1, 3)) < 24 && Number(offset.slice(4)) < 60));
});

const projectCreate = strictObject({
  project_id: identifier("prj"), name: checked(text(1), (value) => /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(value)), state: enumeration(["active", "on_hold", "closed"]),
  description: nullable(text()), replayed: boolean, version: integer(1),
});
export type ContinuityProjectsCreateResult = Decoded<typeof projectCreate>;
export const decodeContinuityProjectsCreate: Decoder<ContinuityProjectsCreateResult> = projectCreate;
