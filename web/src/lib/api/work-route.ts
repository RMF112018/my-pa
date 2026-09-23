import { NextResponse, type NextRequest } from "next/server";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayCapability,
  type GatewayOutcome,
} from "@/lib/api/gateway";
import type { CapabilityResults } from "@/lib/api/decode";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import type { PrincipalSession } from "@/contracts/identity";
import type { ErrorEnvelope } from "@/contracts/envelope";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { WEB_LIMITATIONS } from "@/lib/diagnostics/safe-detail";

export type WorkField = {
  readonly gateway: string;
  readonly type:
    | "string"
    | "integer"
    | "boolean"
    | "string-array"
    | "mutation-array"
    | "party-ref-array"
    | "integer-array";
  readonly maxItems?: number;
  /**
   * The longest `string` this field admits, in UTF-16 code units.
   *
   * Omitted, a string is unbounded here exactly as before; the backend command
   * still owns its own shape. Present only where a write contract fixes a
   * transport ceiling (a Constraint-plane `idempotencyKey` is at most 128).
   */
  readonly maxLength?: number;
  /**
   * The smallest `integer` this field admits.
   *
   * Omitted, any safe integer passes as before — the existing Task, Commitment
   * and settings maps never set it, so their behaviour is unchanged. The
   * Constraint authoring maps set `0` on `expectedVersion`/`displayOrder`, which
   * is the `>= 0` the backend commands check with `type(value) is int`.
   */
  readonly minimum?: number;
  /**
   * The closed vocabulary this field's value must be a member of.
   *
   * Present only where the backend command itself declares a closed set, so the
   * BFF refuses a value the gateway would refuse anyway — before the request
   * leaves the process, and naming the browser field rather than a Python one.
   * Omitted, the field keeps its previous behaviour of accepting any string.
   */
  readonly values?: readonly string[];
};
type FieldMap = Readonly<Record<string, WorkField>>;
type InputKind = "query" | "body";

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

function invalid(message: string) {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown, maximum: number): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every((item) => typeof item === "string")
  );
}

const BULK_UPDATE_VALUES: Readonly<Record<string, "string" | "boolean">> = {
  title: "string",
  description: "string",
  priority: "string",
  due_at: "string",
  scheduled_at: "string",
  deferred_until: "string",
  commitment_id: "string",
  role: "string",
  archived: "boolean",
};
const BULK_CLEAR_FIELDS = new Set([
  "description",
  "priority",
  "due_at",
  "scheduled_at",
  "deferred_until",
  "commitment_id",
  "role",
]);

function isBoundedMutationArray(value: unknown, maximum: number): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > maximum) return false;
  return value.every((item) => {
    if (!isRecord(item)) return false;
    if (
      typeof item.kind !== "string" ||
      typeof item.task_id !== "string" ||
      typeof item.expected_version !== "number" ||
      !Number.isSafeInteger(item.expected_version) ||
      item.expected_version < 1
    ) {
      return false;
    }
    if (item.kind === "update") {
      const keys = Object.keys(item);
      if (
        keys.some(
          (key) =>
            !["kind", "task_id", "expected_version", "values", "clear_fields"].includes(key),
        ) ||
        !isRecord(item.values) ||
        !isStringArray(item.clear_fields, BULK_CLEAR_FIELDS.size)
      ) {
        return false;
      }
      if (
        item.clear_fields.some((name) => !BULK_CLEAR_FIELDS.has(name)) ||
        new Set(item.clear_fields).size !== item.clear_fields.length
      ) {
        return false;
      }
      const valueEntries = Object.entries(item.values);
      if (valueEntries.length < 1 && item.clear_fields.length < 1) return false;
      return valueEntries.every(([name, entry]) => {
        const expected = BULK_UPDATE_VALUES[name];
        return expected !== undefined && typeof entry === expected;
      });
    }
    if (item.kind === "transition") {
      if (
        Object.keys(item).some(
          (key) =>
            ![
              "kind",
              "task_id",
              "expected_version",
              "to_state",
              "closure_evidence_ref",
            ].includes(key),
        ) ||
        typeof item.to_state !== "string"
      ) {
        return false;
      }
      return (
        item.closure_evidence_ref === undefined ||
        typeof item.closure_evidence_ref === "string"
      );
    }
    return false;
  });
}

/**
 * The three keys a browser PartyRef may carry, in the browser's spelling.
 *
 * Deliberately not a generic object passthrough: an object with any other key
 * is refused rather than forwarded or silently trimmed, so `entity_id` (the
 * gateway spelling) is as unknown here as `principalId` would be.
 */
const PARTY_REF_KEYS: ReadonlySet<string> = new Set(["kind", "entityId", "label"]);

/** The gateway spelling one admitted PartyRef is serialized to. */
type GatewayPartyRef = {
  readonly kind: "principal" | "entity" | "unresolved";
  readonly entity_id: string | null;
  readonly label: string | null;
};

function isNonBlank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * One browser PartyRef as the gateway document, or the reason it is refused.
 *
 * The kind rules are `PartyRef.__post_init__`'s, stated at the transport so a
 * malformed party is a `400` naming the browser field rather than a gateway
 * round trip: a `principal` carries neither identity nor label, an `entity`
 * names an identity and may carry presentation wording, an `unresolved` party
 * *is* its non-blank wording and names no identity. `null` and absent are one
 * answer for an optional member, as they are to the Python normalizer, which
 * reads both through `Mapping.get`.
 *
 * Text is never trimmed or rewritten. `trim()` is consulted only to refuse a
 * label that is all whitespace; the label that travels is the one that arrived,
 * byte for byte. The serialized shape always carries all three keys, with
 * `null` for an absent member, which is what the backend's party digest reads.
 */
function partyRef(item: unknown): GatewayPartyRef | string {
  if (!isRecord(item)) return "must contain only party objects";
  if (Object.keys(item).some((key) => !PARTY_REF_KEYS.has(key))) {
    return "contains a party with an unknown key";
  }
  const { kind } = item;
  const entityId = item.entityId ?? null;
  const label = item.label ?? null;
  if (label !== null && !isNonBlank(label)) {
    return "contains a party whose label is not non-blank text";
  }
  if (kind === "principal") {
    if (entityId !== null || label !== null) {
      return "contains a principal party carrying an entityId or label";
    }
    return { kind, entity_id: null, label: null };
  }
  if (kind === "entity") {
    if (!isNonBlank(entityId)) return "contains an entity party without an entityId";
    return { kind, entity_id: entityId, label };
  }
  if (kind === "unresolved") {
    if (entityId !== null) return "contains an unresolved party carrying an entityId";
    if (label === null) return "contains an unresolved party without a label";
    return { kind, entity_id: null, label };
  }
  return "contains a party of an unknown kind";
}

/**
 * A bounded PartyRef array, in order and with duplicates kept.
 *
 * Order is meaningful (the first BIC is the one a Register row leads with) and
 * a duplicate is the backend's to accept or refuse, so neither is normalized
 * away here. An empty array is valid transport: whether a Constraint is
 * complete enough to publish is the domain's decision.
 */
function partyRefArray(value: unknown, maximum: number): GatewayPartyRef[] | string {
  if (!Array.isArray(value) || value.length > maximum) {
    return `must be an array of at most ${maximum} parties`;
  }
  const parties: GatewayPartyRef[] = [];
  for (const item of value) {
    const party = partyRef(item);
    if (typeof party === "string") return party;
    parties.push(party);
  }
  return parties;
}

/** A bounded array of safe non-negative integers, in order and with duplicates kept. */
function isBoundedIntegerArray(value: unknown, maximum: number): value is number[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every((item) => typeof item === "number" && Number.isSafeInteger(item) && item >= 0)
  );
}

function parseField(browserName: string, value: unknown, field: WorkField, input: InputKind):
  | { readonly ok: true; readonly gateway: string; readonly value: unknown }
  | { readonly ok: false; readonly response: NextResponse } {
  const { gateway, type, values } = field;
  if (type === "string") {
    if (typeof value === "string") {
      if (field.maxLength !== undefined && value.length > field.maxLength) {
        return {
          ok: false,
          response: invalid(`${browserName} must be at most ${field.maxLength} characters`),
        };
      }
      if (values && !values.includes(value)) {
        return { ok: false, response: invalid(`${browserName} is not an accepted value`) };
      }
      return { ok: true, gateway, value };
    }
    return { ok: false, response: invalid(`${browserName} must be a string`) };
  }
  if (type === "integer") {
    const { minimum } = field;
    let integer: number | undefined;
    if (typeof value === "number" && Number.isSafeInteger(value)) {
      integer = value;
    } else if (input === "query" && typeof value === "string" && /^(0|[1-9]\d*)$/.test(value)) {
      const parsed = Number(value);
      if (Number.isSafeInteger(parsed)) integer = parsed;
    }
    if (integer === undefined) {
      return { ok: false, response: invalid(`${browserName} must be an integer`) };
    }
    if (minimum !== undefined && integer < minimum) {
      return {
        ok: false,
        response: invalid(`${browserName} must be an integer of at least ${minimum}`),
      };
    }
    return { ok: true, gateway, value: integer };
  }
  if (type === "boolean") {
    if (typeof value === "boolean") return { ok: true, gateway, value };
    if (input === "query" && value === "true") return { ok: true, gateway, value: true };
    if (input === "query" && value === "false") return { ok: true, gateway, value: false };
    return { ok: false, response: invalid(`${browserName} must be true or false`) };
  }
  const maximum = field.maxItems ?? (type === "mutation-array" ? 100 : 32);
  if (type === "string-array") {
    if (isStringArray(value, maximum)) {
      if (values && value.some((item) => !values.includes(item))) {
        return { ok: false, response: invalid(`${browserName} contains a value that is not accepted`) };
      }
      return { ok: true, gateway, value };
    }
    return {
      ok: false,
      response: invalid(`${browserName} must be an array of at most ${maximum} strings`),
    };
  }
  if (type === "party-ref-array") {
    const parties = partyRefArray(value, maximum);
    if (typeof parties === "string") {
      return { ok: false, response: invalid(`${browserName} ${parties}`) };
    }
    return { ok: true, gateway, value: parties };
  }
  if (type === "integer-array") {
    if (isBoundedIntegerArray(value, maximum)) return { ok: true, gateway, value };
    return {
      ok: false,
      response: invalid(
        `${browserName} must be an array of at most ${maximum} non-negative integers`,
      ),
    };
  }
  if (isBoundedMutationArray(value, maximum)) return { ok: true, gateway, value };
  return {
    ok: false,
    response: invalid(`${browserName} must contain between 1 and ${maximum} valid mutations`),
  };
}

function isValidIANATimezone(timezone: unknown): timezone is string {
  if (typeof timezone !== "string") return false;
  if (timezone.length === 0 || timezone.length > 64) return false;
  if (!/^[A-Za-z0-9_+\/-]+$/.test(timezone)) return false;
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
    return true;
  } catch {
    return false;
  }
}

function mapped(source: Record<string, unknown>, fields: FieldMap, input: InputKind) {
  const unknown = Object.keys(source).filter((key) => !(key in fields));
  if (unknown.length > 0) return { ok: false as const, response: invalid(`unknown fields: ${unknown.join(", ")}`) };

  // Validate timezone if present
  if ("timezone" in source && source.timezone !== undefined) {
    if (!isValidIANATimezone(source.timezone)) {
      return { ok: false as const, response: invalid("timezone is not a valid IANA timezone name") };
    }
  }

  const payload: Record<string, unknown> = {};
  for (const [browserName, field] of Object.entries(fields)) {
    const value = source[browserName];
    if (value === undefined) continue;
    const parsed = parseField(browserName, value, field, input);
    if (!parsed.ok) return { ok: false as const, response: parsed.response };
    payload[parsed.gateway] = parsed.value;
  }
  return {
    ok: true as const,
    payload,
  };
}

/**
 * The declared query, read off the URL — never the URL's own parameter bag.
 *
 * A field the map does not declare is still copied in, because `mapped` is what
 * refuses an unknown name and it has to see one to refuse it. What this adds is
 * repetition: a declared `string-array` field collects every occurrence of its
 * name, so `?status=open&status=closed` is a two-member filter rather than the
 * last value silently winning. No `URLSearchParams` is ever handed onward.
 */
function readQuery(search: URLSearchParams, fields: FieldMap): Record<string, unknown> {
  const query: Record<string, unknown> = Object.fromEntries(search.entries());
  for (const [name, field] of Object.entries(fields)) {
    if (field.type === "string-array" && search.has(name)) query[name] = search.getAll(name);
  }
  return query;
}

function publicResult(result: Record<string, unknown>) {
  return JSON.parse(
    JSON.stringify(result, (key, value) =>
      key === "principal_id" || key === "principalId" ? undefined : value,
    ),
  ) as Record<string, unknown>;
}

/**
 * What a pre-dispatch admission check is handed, and all it is handed.
 *
 * `principal` is the session-derived Principal the mutation itself will carry —
 * the same object, not a second resolution — and `read` is bound to it, so an
 * admission check cannot address the gateway as anyone else. `payload` is the
 * final gateway payload (the mapped body with the route's fixed fields merged
 * over it), exactly what would be dispatched. `refuse` renders a gateway
 * refusal the way this module renders the mutation's own, so a refused
 * preflight is indistinguishable in shape from a refused mutation.
 */
export type AdmissionContext = {
  readonly principal: PrincipalSession;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly read: <C extends GatewayCapability>(
    capability: C,
    payload: Record<string, unknown>,
  ) => Promise<GatewayOutcome<CapabilityResults[C]>>;
  readonly refuse: (status: number, error: ErrorEnvelope) => NextResponse;
};

/**
 * The two optional hooks a write route may add, and no others.
 *
 * - `validate` is a closed cross-field check over the mapped payload (gateway
 *   spelling), run after every field has parsed and before anything else. A
 *   string return is a `400 invalid_request` carrying that message. It exists
 *   for rules no single field can state, such as a reorder's two arrays having
 *   one length.
 * - `admit` runs after `validate`, once the serving provider is known to be the
 *   backend, and immediately before the mutation capability is invoked. `null`
 *   proceeds; a response is returned as the answer, `private, no-store`, and the
 *   mutation is never dispatched.
 *
 * Neither can alter the payload: both see it read-only, and what is dispatched
 * is what was mapped.
 */
export type WorkPostOptions = {
  readonly validate?: (payload: Readonly<Record<string, unknown>>) => string | null;
  readonly admit?: (context: AdmissionContext) => Promise<NextResponse | null>;
};

async function dispatch(
  principal: PrincipalSession,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
  admit?: WorkPostOptions["admit"],
) {
  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(scope, WEB_LIMITATIONS.syntheticNoWork);
  }
  if (admit) {
    // Only a backend-served request is admitted: a build that will not dispatch
    // has already answered above, and a preflight read there would spend a
    // gateway call on a request that was never going to reach one.
    const refusal = await admit({
      principal,
      payload,
      read: (read, readPayload) => invokeGateway(principal, read, readPayload),
      refuse: (status, error) => gatewayRefusal(scope, status, error),
    });
    if (refusal) return refusal;
  }
  const outcome = await invokeGateway(principal, capability, payload);
  if (!outcome.ok) {
    const identifier = typeof payload.task_id === "string" ? { capability: "tasks.read" as const, payload: { task_id: payload.task_id }, key: "task" }
      : typeof payload.commitment_id === "string" ? { capability: "commitments.read" as const, payload: { commitment_id: payload.commitment_id }, key: "commitment" }
      : undefined;
    if (outcome.status === 409 && identifier) {
      const current = await invokeGateway(principal, identifier.capability, identifier.payload);
      if (current.ok && isRecord(current.result)) {
        const record = current.result[identifier.key];
        if (!isRecord(record)) {
          return gatewayRefusal(scope, outcome.status, outcome.error);
        }
        const refusal = await gatewayRefusal(scope, outcome.status, outcome.error).json();
        return NextResponse.json({ ...refusal, current: publicResult(record) }, { status: 409 });
      }
    }
    return gatewayRefusal(scope, outcome.status, outcome.error);
  }
  if (!isRecord(outcome.result)) {
    return gatewayRefusal(scope, 503, {
      errorClass: "unavailable",
      code: "upstream_contract_invalid",
      message: "the gateway result did not match the capability contract",
    });
  }
  return NextResponse.json({
    shape: "backend",
    ...publicResult(outcome.result),
    disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
  });
}

async function serve(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  return dispatch(guard.principal, scope, capability, payload);
}

export async function workGet(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
) {
  const result = mapped(readQuery(request.nextUrl.searchParams, fields), fields, "query");
  if (!result.ok) return noStore(result.response);
  return noStore(await serve(request, scope, capability, { ...result.payload, ...fixed }));
}

export async function workPost(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
  options: WorkPostOptions = {},
) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return noStore(blocked as NextResponse);
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);
  const parsed = await readCleanBody(request);
  if (!parsed.ok) return noStore(parsed.response);
  const result = mapped(parsed.body, fields, "body");
  if (!result.ok) return noStore(result.response);
  const refused = options.validate?.(result.payload) ?? null;
  if (refused !== null) return noStore(invalid(refused));
  return noStore(
    await dispatch(
      guard.principal,
      scope,
      capability,
      { ...result.payload, ...fixed },
      options.admit,
    ),
  );
}
