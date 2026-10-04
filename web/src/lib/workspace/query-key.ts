/** Credential-free resource identity; feature adapters own semantic normalization. */
export type ResourceFilterValue =
  | string
  | number
  | boolean
  | null
  | readonly string[]
  | readonly number[]
  | readonly boolean[]
  | readonly null[];

export interface BuildResourceKeyInput {
  readonly family: string;
  readonly mode: string;
  readonly identity?: string | null;
  readonly filters?: Readonly<Record<string, ResourceFilterValue | undefined>>;
  readonly cursor?: string | null;
  readonly pageSize?: number | null;
  readonly sessionEpoch: string | number;
}

export interface ResourceKey {
  readonly family: string;
  readonly mode: string;
  readonly identity: string | null;
  readonly filters: Readonly<Record<string, ResourceFilterValue>>;
  readonly cursor: string | null;
  readonly pageSize: number | null;
  readonly sessionEpoch: string;
}

function requiredString(value: string, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value.trim();
}

function optionalString(value: string | null | undefined, field: string): string | null {
  if (value == null || value === "") return null;
  if (typeof value !== "string") throw new TypeError(`${field} must be a string or null`);
  return value;
}

function isPrimitive(value: unknown): value is string | number | boolean | null {
  return value === null || typeof value === "string" || typeof value === "boolean"
    || (typeof value === "number" && Number.isFinite(value));
}

function filterValue(value: ResourceFilterValue): ResourceFilterValue {
  if (isPrimitive(value)) return value;
  if (Array.isArray(value)) {
    const firstType = value[0] === null ? "null" : typeof value[0];
    for (const element of value) {
      const elementType = element === null ? "null" : typeof element;
      if (!isPrimitive(element) || elementType !== firstType) {
        throw new TypeError("filter arrays must contain one primitive type");
      }
    }
    return Object.freeze([...value]) as ResourceFilterValue;
  }
  throw new TypeError("filters must contain primitive values or homogeneous primitive arrays");
}

export function buildResourceKey(input: BuildResourceKeyInput): ResourceKey {
  const family = requiredString(input.family, "family");
  const mode = requiredString(input.mode, "mode");
  const identity = optionalString(input.identity, "identity");
  const cursor = optionalString(input.cursor, "cursor");
  const pageSize = input.pageSize ?? null;
  if (pageSize !== null && (!Number.isSafeInteger(pageSize) || pageSize <= 0)) {
    throw new RangeError("pageSize must be a positive safe integer");
  }
  let sessionEpoch: string;
  if (typeof input.sessionEpoch === "number") {
    if (!Number.isSafeInteger(input.sessionEpoch)) {
      throw new TypeError("sessionEpoch must be an integer-representable number or non-empty string");
    }
    sessionEpoch = String(input.sessionEpoch);
  } else {
    sessionEpoch = requiredString(input.sessionEpoch, "sessionEpoch");
  }
  if (input.filters != null && (
    typeof input.filters !== "object" || Array.isArray(input.filters)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(input.filters))
  )) {
    throw new TypeError("filters must be a record");
  }
  const filters = Object.fromEntries(
    Object.entries(input.filters ?? {}).filter(([, value]) => value !== undefined)
      .map(([name, value]) => [name, filterValue(value!)]),
  );
  return Object.freeze({ family, mode, identity, filters: Object.freeze(filters), cursor, pageSize, sessionEpoch });
}

export function serializeResourceKey(key: ResourceKey): string {
  return JSON.stringify([
    "resource-key:v1", key.family, key.mode, key.identity,
    Object.keys(key.filters).sort().map((name) => [name, key.filters[name]]),
    key.cursor, key.pageSize, key.sessionEpoch,
  ]);
}

export function resourceKeysEqual(a: ResourceKey, b: ResourceKey): boolean {
  return serializeResourceKey(a) === serializeResourceKey(b);
}
