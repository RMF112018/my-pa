export type UrlField<Value> = {
  defaultValue: Value;
  emitDefault?: boolean;
  resetsCursor?: boolean;
} & (
  | { cardinality: "one"; parse: (value: string) => Value; serialize: (value: Value) => string }
  | { cardinality: "many"; parse: (values: readonly string[]) => Value; serialize: (value: Value) => readonly string[] }
);

type Field<State> = {
  [Key in keyof State & string]: UrlField<State[Key]> & { key: Key };
}[keyof State & string];

/** Declare each state key exactly once; cursor keys must name declared fields. */
export type UrlSchema<State> = {
  fields: readonly Field<State>[];
  cursorKeys?: readonly (keyof State & string)[];
};

export type ParsedUrlState<State> = {
  state: State;
  passthrough: readonly (readonly [string, string])[];
  invalidKnownKeys: readonly (keyof State & string)[];
};

function values<Value>(field: UrlField<Value>, value: Value): readonly string[] {
  return field.cardinality === "one" ? [field.serialize(value)] : field.serialize(value);
}

function equal<Value>(field: UrlField<Value>, left: Value, right: Value): boolean {
  const a = values(field, left);
  const b = values(field, right);
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function validate<State>(schema: UrlSchema<State>): void {
  const keys = schema.fields.map((field) => field.key);
  if (new Set(keys).size !== keys.length || schema.cursorKeys?.some((key) => !keys.includes(key))) {
    throw new Error("URL schema requires unique fields and declared cursor keys");
  }
}

/** Parsers throw for invalid input. Missing fields use defaults without parsing. */
export function parseUrlState<State>(schema: UrlSchema<State>, params: URLSearchParams): ParsedUrlState<State> {
  validate(schema);
  // The schema supplies every state key; populate each through its typed field.
  const state = {} as State;
  const invalidKnownKeys: (keyof State & string)[] = [];
  function parseField<Key extends keyof State & string>(field: UrlField<State[Key]> & { key: Key }) {
    const input = params.getAll(field.key);
    let value = field.defaultValue;
    if (input.length > 0) {
      try {
        value = field.cardinality === "one" ? field.parse(input[0]) : field.parse(input);
      } catch {
        invalidKnownKeys.push(field.key);
      }
    }
    state[field.key] = value;
  }
  schema.fields.forEach(parseField);
  const known = new Set<string>(schema.fields.map((field) => field.key));
  const passthrough = Array.from(params.entries()).filter(([key]) => !known.has(key));
  return { state, passthrough, invalidKnownKeys };
}

/** Callback output defines canonical semantic equality, including defaults. */
export function serializeUrlState<State>(schema: UrlSchema<State>, parsed: ParsedUrlState<State>): URLSearchParams {
  validate(schema);
  const params = new URLSearchParams();
  function serializeField<Key extends keyof State & string>(field: UrlField<State[Key]> & { key: Key }) {
    const value = parsed.state[field.key];
    if (field.emitDefault || !equal(field, value, field.defaultValue)) {
      for (const entry of values(field, value)) params.append(field.key, entry);
    }
  }
  schema.fields.forEach(serializeField);
  const known = new Set<string>(schema.fields.map((field) => field.key));
  for (const [key, value] of parsed.passthrough) {
    if (!known.has(key)) params.append(key, value);
  }
  return params;
}

/** Cursor removal wins over concurrent cursor patches and emitDefault. */
export function patchUrlState<State>(schema: UrlSchema<State>, parsed: ParsedUrlState<State>, patch: Partial<State>): URLSearchParams {
  const state = { ...parsed.state, ...patch };
  const resetsCursor = schema.fields.some((field) => field.resetsCursor && !equal(field, parsed.state[field.key], state[field.key]));
  const params = serializeUrlState(schema, { ...parsed, state });
  if (resetsCursor) {
    for (const key of schema.cursorKeys ?? []) params.delete(key);
  }
  return params;
}
