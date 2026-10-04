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
    | "integer-array"
    | "attendee-array";
  readonly required?: boolean;
  readonly nullable?: boolean;
  readonly minLength?: number;
  readonly nonBlank?: boolean;
  readonly maximum?: number;
  readonly pattern?: RegExp;
  readonly uniqueItems?: boolean;
  readonly itemMapping?: Readonly<Record<string, string>>;
  readonly format?: "timestamp" | "timezone" | "https-url" | "email";
  /** Canonical Python character bounds count Unicode code points. Opt-in. */
  readonly codePointLength?: boolean;
  readonly storable?: boolean;
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
export type FieldMap = Readonly<Record<string, WorkField>>;
type InputKind = "query" | "body";

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

export function invalidWorkRequest(message: string) {
  return noStore(NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  ));
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

/** Exact prefix/kind grammar shared by the canonical identifier contract. */
export function isCanonicalId(value: unknown, prefix: string): value is string {
  return typeof value === "string" && new RegExp(`^${prefix}_[A-Za-z0-9]{8,64}$`).exec(value)?.[0] === value;
}

/** RFC3339 aware instant, including calendar validity; Date.parse alone rolls dates. */
export function isAwareRfc3339(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offsetHour, offsetMinute] = match;
  const year = Number(yearText), month = Number(monthText), day = Number(dayText);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]!
    && Number(hourText) <= 23 && Number(minuteText) <= 59 && Number(secondText) <= 59
    && (offsetHour === undefined || (Number(offsetHour) <= 23 && Number(offsetMinute) <= 59));
}

// Generated with the repository's Python Unicode casefold implementation. Only
// exceptions to per-codepoint lowercasing are stored; no normalization is added.
const CASEFOLD_EXCEPTIONS: Readonly<Record<string, string>> = {"\u00b5":"\u03bc","\u00df":"ss","\u0149":"\u02bcn","\u017f":"s","\u01f0":"j\u030c","\u0345":"\u03b9","\u0390":"\u03b9\u0308\u0301","\u03b0":"\u03c5\u0308\u0301","\u03c2":"\u03c3","\u03d0":"\u03b2","\u03d1":"\u03b8","\u03d5":"\u03c6","\u03d6":"\u03c0","\u03f0":"\u03ba","\u03f1":"\u03c1","\u03f5":"\u03b5","\u0587":"\u0565\u0582","\u13a0":"\u13a0","\u13a1":"\u13a1","\u13a2":"\u13a2","\u13a3":"\u13a3","\u13a4":"\u13a4","\u13a5":"\u13a5","\u13a6":"\u13a6","\u13a7":"\u13a7","\u13a8":"\u13a8","\u13a9":"\u13a9","\u13aa":"\u13aa","\u13ab":"\u13ab","\u13ac":"\u13ac","\u13ad":"\u13ad","\u13ae":"\u13ae","\u13af":"\u13af","\u13b0":"\u13b0","\u13b1":"\u13b1","\u13b2":"\u13b2","\u13b3":"\u13b3","\u13b4":"\u13b4","\u13b5":"\u13b5","\u13b6":"\u13b6","\u13b7":"\u13b7","\u13b8":"\u13b8","\u13b9":"\u13b9","\u13ba":"\u13ba","\u13bb":"\u13bb","\u13bc":"\u13bc","\u13bd":"\u13bd","\u13be":"\u13be","\u13bf":"\u13bf","\u13c0":"\u13c0","\u13c1":"\u13c1","\u13c2":"\u13c2","\u13c3":"\u13c3","\u13c4":"\u13c4","\u13c5":"\u13c5","\u13c6":"\u13c6","\u13c7":"\u13c7","\u13c8":"\u13c8","\u13c9":"\u13c9","\u13ca":"\u13ca","\u13cb":"\u13cb","\u13cc":"\u13cc","\u13cd":"\u13cd","\u13ce":"\u13ce","\u13cf":"\u13cf","\u13d0":"\u13d0","\u13d1":"\u13d1","\u13d2":"\u13d2","\u13d3":"\u13d3","\u13d4":"\u13d4","\u13d5":"\u13d5","\u13d6":"\u13d6","\u13d7":"\u13d7","\u13d8":"\u13d8","\u13d9":"\u13d9","\u13da":"\u13da","\u13db":"\u13db","\u13dc":"\u13dc","\u13dd":"\u13dd","\u13de":"\u13de","\u13df":"\u13df","\u13e0":"\u13e0","\u13e1":"\u13e1","\u13e2":"\u13e2","\u13e3":"\u13e3","\u13e4":"\u13e4","\u13e5":"\u13e5","\u13e6":"\u13e6","\u13e7":"\u13e7","\u13e8":"\u13e8","\u13e9":"\u13e9","\u13ea":"\u13ea","\u13eb":"\u13eb","\u13ec":"\u13ec","\u13ed":"\u13ed","\u13ee":"\u13ee","\u13ef":"\u13ef","\u13f0":"\u13f0","\u13f1":"\u13f1","\u13f2":"\u13f2","\u13f3":"\u13f3","\u13f4":"\u13f4","\u13f5":"\u13f5","\u13f8":"\u13f0","\u13f9":"\u13f1","\u13fa":"\u13f2","\u13fb":"\u13f3","\u13fc":"\u13f4","\u13fd":"\u13f5","\u1c80":"\u0432","\u1c81":"\u0434","\u1c82":"\u043e","\u1c83":"\u0441","\u1c84":"\u0442","\u1c85":"\u0442","\u1c86":"\u044a","\u1c87":"\u0463","\u1c88":"\ua64b","\u1e96":"h\u0331","\u1e97":"t\u0308","\u1e98":"w\u030a","\u1e99":"y\u030a","\u1e9a":"a\u02be","\u1e9b":"\u1e61","\u1e9e":"ss","\u1f50":"\u03c5\u0313","\u1f52":"\u03c5\u0313\u0300","\u1f54":"\u03c5\u0313\u0301","\u1f56":"\u03c5\u0313\u0342","\u1f80":"\u1f00\u03b9","\u1f81":"\u1f01\u03b9","\u1f82":"\u1f02\u03b9","\u1f83":"\u1f03\u03b9","\u1f84":"\u1f04\u03b9","\u1f85":"\u1f05\u03b9","\u1f86":"\u1f06\u03b9","\u1f87":"\u1f07\u03b9","\u1f88":"\u1f00\u03b9","\u1f89":"\u1f01\u03b9","\u1f8a":"\u1f02\u03b9","\u1f8b":"\u1f03\u03b9","\u1f8c":"\u1f04\u03b9","\u1f8d":"\u1f05\u03b9","\u1f8e":"\u1f06\u03b9","\u1f8f":"\u1f07\u03b9","\u1f90":"\u1f20\u03b9","\u1f91":"\u1f21\u03b9","\u1f92":"\u1f22\u03b9","\u1f93":"\u1f23\u03b9","\u1f94":"\u1f24\u03b9","\u1f95":"\u1f25\u03b9","\u1f96":"\u1f26\u03b9","\u1f97":"\u1f27\u03b9","\u1f98":"\u1f20\u03b9","\u1f99":"\u1f21\u03b9","\u1f9a":"\u1f22\u03b9","\u1f9b":"\u1f23\u03b9","\u1f9c":"\u1f24\u03b9","\u1f9d":"\u1f25\u03b9","\u1f9e":"\u1f26\u03b9","\u1f9f":"\u1f27\u03b9","\u1fa0":"\u1f60\u03b9","\u1fa1":"\u1f61\u03b9","\u1fa2":"\u1f62\u03b9","\u1fa3":"\u1f63\u03b9","\u1fa4":"\u1f64\u03b9","\u1fa5":"\u1f65\u03b9","\u1fa6":"\u1f66\u03b9","\u1fa7":"\u1f67\u03b9","\u1fa8":"\u1f60\u03b9","\u1fa9":"\u1f61\u03b9","\u1faa":"\u1f62\u03b9","\u1fab":"\u1f63\u03b9","\u1fac":"\u1f64\u03b9","\u1fad":"\u1f65\u03b9","\u1fae":"\u1f66\u03b9","\u1faf":"\u1f67\u03b9","\u1fb2":"\u1f70\u03b9","\u1fb3":"\u03b1\u03b9","\u1fb4":"\u03ac\u03b9","\u1fb6":"\u03b1\u0342","\u1fb7":"\u03b1\u0342\u03b9","\u1fbc":"\u03b1\u03b9","\u1fbe":"\u03b9","\u1fc2":"\u1f74\u03b9","\u1fc3":"\u03b7\u03b9","\u1fc4":"\u03ae\u03b9","\u1fc6":"\u03b7\u0342","\u1fc7":"\u03b7\u0342\u03b9","\u1fcc":"\u03b7\u03b9","\u1fd2":"\u03b9\u0308\u0300","\u1fd3":"\u03b9\u0308\u0301","\u1fd6":"\u03b9\u0342","\u1fd7":"\u03b9\u0308\u0342","\u1fe2":"\u03c5\u0308\u0300","\u1fe3":"\u03c5\u0308\u0301","\u1fe4":"\u03c1\u0313","\u1fe6":"\u03c5\u0342","\u1fe7":"\u03c5\u0308\u0342","\u1ff2":"\u1f7c\u03b9","\u1ff3":"\u03c9\u03b9","\u1ff4":"\u03ce\u03b9","\u1ff6":"\u03c9\u0342","\u1ff7":"\u03c9\u0342\u03b9","\u1ffc":"\u03c9\u03b9","\uab70":"\u13a0","\uab71":"\u13a1","\uab72":"\u13a2","\uab73":"\u13a3","\uab74":"\u13a4","\uab75":"\u13a5","\uab76":"\u13a6","\uab77":"\u13a7","\uab78":"\u13a8","\uab79":"\u13a9","\uab7a":"\u13aa","\uab7b":"\u13ab","\uab7c":"\u13ac","\uab7d":"\u13ad","\uab7e":"\u13ae","\uab7f":"\u13af","\uab80":"\u13b0","\uab81":"\u13b1","\uab82":"\u13b2","\uab83":"\u13b3","\uab84":"\u13b4","\uab85":"\u13b5","\uab86":"\u13b6","\uab87":"\u13b7","\uab88":"\u13b8","\uab89":"\u13b9","\uab8a":"\u13ba","\uab8b":"\u13bb","\uab8c":"\u13bc","\uab8d":"\u13bd","\uab8e":"\u13be","\uab8f":"\u13bf","\uab90":"\u13c0","\uab91":"\u13c1","\uab92":"\u13c2","\uab93":"\u13c3","\uab94":"\u13c4","\uab95":"\u13c5","\uab96":"\u13c6","\uab97":"\u13c7","\uab98":"\u13c8","\uab99":"\u13c9","\uab9a":"\u13ca","\uab9b":"\u13cb","\uab9c":"\u13cc","\uab9d":"\u13cd","\uab9e":"\u13ce","\uab9f":"\u13cf","\uaba0":"\u13d0","\uaba1":"\u13d1","\uaba2":"\u13d2","\uaba3":"\u13d3","\uaba4":"\u13d4","\uaba5":"\u13d5","\uaba6":"\u13d6","\uaba7":"\u13d7","\uaba8":"\u13d8","\uaba9":"\u13d9","\uabaa":"\u13da","\uabab":"\u13db","\uabac":"\u13dc","\uabad":"\u13dd","\uabae":"\u13de","\uabaf":"\u13df","\uabb0":"\u13e0","\uabb1":"\u13e1","\uabb2":"\u13e2","\uabb3":"\u13e3","\uabb4":"\u13e4","\uabb5":"\u13e5","\uabb6":"\u13e6","\uabb7":"\u13e7","\uabb8":"\u13e8","\uabb9":"\u13e9","\uabba":"\u13ea","\uabbb":"\u13eb","\uabbc":"\u13ec","\uabbd":"\u13ed","\uabbe":"\u13ee","\uabbf":"\u13ef","\ufb00":"ff","\ufb01":"fi","\ufb02":"fl","\ufb03":"ffi","\ufb04":"ffl","\ufb05":"st","\ufb06":"st","\ufb13":"\u0574\u0576","\ufb14":"\u0574\u0565","\ufb15":"\u0574\u056b","\ufb16":"\u057e\u0576","\ufb17":"\u0574\u056d","\u1c89":"\u1c89","\ua7cb":"\ua7cb","\ua7cc":"\ua7cc","\ua7da":"\ua7da","\ua7dc":"\ua7dc","\ud803\udd50":"\ud803\udd50","\ud803\udd51":"\ud803\udd51","\ud803\udd52":"\ud803\udd52","\ud803\udd53":"\ud803\udd53","\ud803\udd54":"\ud803\udd54","\ud803\udd55":"\ud803\udd55","\ud803\udd56":"\ud803\udd56","\ud803\udd57":"\ud803\udd57","\ud803\udd58":"\ud803\udd58","\ud803\udd59":"\ud803\udd59","\ud803\udd5a":"\ud803\udd5a","\ud803\udd5b":"\ud803\udd5b","\ud803\udd5c":"\ud803\udd5c","\ud803\udd5d":"\ud803\udd5d","\ud803\udd5e":"\ud803\udd5e","\ud803\udd5f":"\ud803\udd5f","\ud803\udd60":"\ud803\udd60","\ud803\udd61":"\ud803\udd61","\ud803\udd62":"\ud803\udd62","\ud803\udd63":"\ud803\udd63","\ud803\udd64":"\ud803\udd64","\ud803\udd65":"\ud803\udd65"};
function casefold(value: string): string {
  return Array.from(value, (character) => CASEFOLD_EXCEPTIONS[character] ?? character.toLowerCase()).join("");
}

// Python str.strip/isspace includes NEL and C0 separators and excludes BOM.
const PYTHON_SPACE = "[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]";
function pythonTrim(value: string): string {
  return value.replace(new RegExp(`^${PYTHON_SPACE}+|${PYTHON_SPACE}+$`, "gu"), "");
}
function normalizedEmail(value: unknown): string | null {
  if (typeof value !== "string" || Array.from(value).length > 320) return null;
  const email = pythonTrim(value);
  if (new RegExp(PYTHON_SPACE, "u").test(email) || email.split("@").length !== 2) return null;
  const [local, domain] = email.split("@");
  if (!local || !domain) return null;
  const normalized = casefold(email);
  return Array.from(normalized).length <= 320 ? normalized : null;
}

function storable(value: string): boolean {
  return !/\u0000|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value);
}

/**
 * Safe relative ZoneInfo key shape for WP03B. The canonical backend owns the
 * host-dependent semantic lookup; Intl and a browser whitelist are not its authority.
 */
export function isCanonicalTimezoneKey(value: unknown): value is string {
  if (typeof value !== "string" || Array.from(value).length < 1 || Array.from(value).length > 64) return false;
  if (value !== pythonTrim(value) || !storable(value) || value.startsWith("/") || value.includes("\\")) return false;
  return value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

function formatAccepted(value: string, format: WorkField["format"]): boolean {
  if (format === "timestamp") return isAwareRfc3339(value);
  if (format === "timezone") return isCanonicalTimezoneKey(value);
  if (format === "email") return normalizedEmail(value) !== null;
  if (format === "https-url") {
    if (value !== value.trim() || /[\u0000-\u0020\u007F]/u.test(value)) return false;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !!url.hostname && !url.username && !url.password;
    } catch { return false; }
  }
  return true;
}

/** Closed attendee objects, raw values retained; normalized forms serve only validation. */
function attendeeArray(value: unknown, maximum: number): Record<string, unknown>[] | string {
  if (!Array.isArray(value) || value.length > maximum) return "must be a bounded attendee array";
  const allowed = ["displayName", "email", "entityId", "isOrganizer", "responseStatus"];
  const responses = ["unknown", "needs_action", "accepted", "declined", "tentative"];
  const entities = new Set<string>(), emails = new Set<string>(), tuples = new Set<string>();
  const attendees: Record<string, unknown>[] = [];
  let organizers = 0;
  for (const item of value) {
    if (!isRecord(item) || Object.keys(item).some((key) => !allowed.includes(key))) return "contains an invalid attendee object";
    const name = item.displayName ?? null, email = item.email ?? null, entity = item.entityId ?? null;
    const organizer = item.isOrganizer === undefined ? false : item.isOrganizer;
    const response = item.responseStatus === undefined ? "unknown" : item.responseStatus;
    if (name !== null && (typeof name !== "string" || Array.from(name).length > 200 || !storable(name))) return "contains an invalid attendee displayName";
    if (email !== null && (typeof email !== "string" || !storable(email))) return "contains an invalid attendee email";
    const normalizedName = typeof name === "string" ? pythonTrim(name) || null : null;
    const normalized = email === null ? null : normalizedEmail(email);
    if (email !== null && normalized === null) return "contains an invalid attendee email";
    if (entity !== null && !isCanonicalId(entity, "ent")) return "contains an invalid attendee entityId";
    if (typeof organizer !== "boolean" || typeof response !== "string" || !responses.includes(response)) return "contains an invalid attendee flag or response";
    if (normalizedName === null && normalized === null && entity === null) return "contains an attendee without identity";
    if (typeof entity === "string" && entities.has(entity)) return "contains duplicate attendee entities";
    if (normalized !== null && emails.has(normalized)) return "contains duplicate attendee emails";
    const tuple = JSON.stringify([normalizedName, normalized, entity, organizer, response]);
    if (tuples.has(tuple)) return "contains duplicate attendees";
    if (organizer && ++organizers > 1) return "contains multiple organizers";
    if (typeof entity === "string") entities.add(entity);
    if (normalized !== null) emails.add(normalized);
    tuples.add(tuple);
    const mapped: Record<string, unknown> = {};
    const names: Readonly<Record<string, string>> = {displayName: "display_name", email: "email", entityId: "entity_id", isOrganizer: "is_organizer", responseStatus: "response_status"};
    for (const [key, entry] of Object.entries(item)) mapped[names[key]!] = entry;
    attendees.push(mapped);
  }
  return attendees;
}

function parseField(browserName: string, value: unknown, field: WorkField, input: InputKind):
  | { readonly ok: true; readonly gateway: string; readonly value: unknown }
  | { readonly ok: false; readonly response: NextResponse } {
  const { gateway, type, values } = field;
  if (value === null && input === "body" && field.nullable) return { ok: true, gateway, value: null };
  if (type === "string") {
    if (typeof value === "string") {
      const length = field.codePointLength ? Array.from(value).length : value.length;
      if ((field.minLength !== undefined && length < field.minLength) || (field.nonBlank && !pythonTrim(value))) {
        return { ok: false, response: invalidWorkRequest(`${browserName} must contain required text`) };
      }
      if ((field.pattern && field.pattern.exec(value)?.[0] !== value) || !formatAccepted(value, field.format) || (field.storable && !storable(value))) {
        return { ok: false, response: invalidWorkRequest(`${browserName} is malformed`) };
      }
      if (field.maxLength !== undefined && length > field.maxLength) {
        return {
          ok: false,
          response: invalidWorkRequest(`${browserName} must be at most ${field.maxLength} characters`),
        };
      }
      if (values && !values.includes(value)) {
        return { ok: false, response: invalidWorkRequest(`${browserName} is not an accepted value`) };
      }
      return { ok: true, gateway, value };
    }
    return { ok: false, response: invalidWorkRequest(`${browserName} must be a string`) };
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
      return { ok: false, response: invalidWorkRequest(`${browserName} must be an integer`) };
    }
    if (minimum !== undefined && integer < minimum) {
      return {
        ok: false,
        response: invalidWorkRequest(`${browserName} must be an integer of at least ${minimum}`),
      };
    }
    if (field.maximum !== undefined && integer > field.maximum) {
      return { ok: false, response: invalidWorkRequest(`${browserName} exceeds its maximum`) };
    }
    return { ok: true, gateway, value: integer };
  }
  if (type === "boolean") {
    if (typeof value === "boolean") return { ok: true, gateway, value };
    if (input === "query" && value === "true") return { ok: true, gateway, value: true };
    if (input === "query" && value === "false") return { ok: true, gateway, value: false };
    return { ok: false, response: invalidWorkRequest(`${browserName} must be true or false`) };
  }
  const maximum = field.maxItems ?? (type === "mutation-array" ? 100 : 32);
  if (type === "string-array") {
    if (isStringArray(value, maximum)) {
      if (values && value.some((item) => !values.includes(item))) {
        return { ok: false, response: invalidWorkRequest(`${browserName} contains a value that is not accepted`) };
      }
      if ((field.uniqueItems && new Set(value).size !== value.length) || (field.pattern && value.some((item) => field.pattern!.exec(item)?.[0] !== item))) {
        return { ok: false, response: invalidWorkRequest(`${browserName} contains duplicate or malformed values`) };
      }
      return { ok: true, gateway, value: field.itemMapping ? value.map((item) => field.itemMapping![item]) : value };
    }
    return {
      ok: false,
      response: invalidWorkRequest(`${browserName} must be an array of at most ${maximum} strings`),
    };
  }
  if (type === "attendee-array") {
    const attendees = attendeeArray(value, field.maxItems ?? 100);
    if (typeof attendees === "string") return { ok: false, response: invalidWorkRequest(`${browserName} ${attendees}`) };
    return { ok: true, gateway, value: attendees };
  }
  if (type === "party-ref-array") {
    const parties = partyRefArray(value, maximum);
    if (typeof parties === "string") {
      return { ok: false, response: invalidWorkRequest(`${browserName} ${parties}`) };
    }
    return { ok: true, gateway, value: parties };
  }
  if (type === "integer-array") {
    if (isBoundedIntegerArray(value, maximum)) return { ok: true, gateway, value };
    return {
      ok: false,
      response: invalidWorkRequest(
        `${browserName} must be an array of at most ${maximum} non-negative integers`,
      ),
    };
  }
  if (isBoundedMutationArray(value, maximum)) return { ok: true, gateway, value };
  return {
    ok: false,
    response: invalidWorkRequest(`${browserName} must contain between 1 and ${maximum} valid mutations`),
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
  const unknown = Object.keys(source).filter((key) => !Object.hasOwn(fields, key));
  if (unknown.length > 0) return { ok: false as const, response: invalidWorkRequest(`unknown fields: ${unknown.join(", ")}`) };

  // Validate timezone if present
  if ("timezone" in source && source.timezone !== undefined) {
    if (!isValidIANATimezone(source.timezone)) {
      return { ok: false as const, response: invalidWorkRequest("timezone is not a valid IANA timezone name") };
    }
  }

  const payload: Record<string, unknown> = {};
  for (const [browserName, field] of Object.entries(fields)) {
    const value = source[browserName];
    if (value === undefined) {
      if (field.required) return { ok: false as const, response: invalidWorkRequest(`${browserName} is required`) };
      continue;
    }
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
export type WorkResultProjection = (
  result: Readonly<Record<string, unknown>>,
  payload: Readonly<Record<string, unknown>>,
) => Record<string, unknown> | null;

export type WorkGetOptions = {
  readonly strictQuery?: boolean;
  readonly validate?: (payload: Readonly<Record<string, unknown>>) => string | null;
  /** null refuses a decoded result that violates this request's projection boundary. */
  readonly project?: WorkResultProjection;
};

export type WorkPostOptions = WorkGetOptions & {
  /** Keyless document transitions accept a genuinely empty body or a closed JSON object. */
  readonly bodyOptional?: boolean;
  readonly admit?: (context: AdmissionContext) => Promise<NextResponse | null>;
};

async function dispatch(
  principal: PrincipalSession,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
  admit?: WorkPostOptions["admit"],
  project?: WorkResultProjection,
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
  const projected = project ? project(outcome.result, payload) : outcome.result;
  if (projected === null) return gatewayRefusal(scope, 503, {
    errorClass: "unavailable", code: "upstream_contract_invalid",
    message: "the gateway result did not match the request boundary",
  });
  return NextResponse.json({
    shape: "backend",
    ...publicResult(projected),
    disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
  });
}

async function serve(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
  project?: WorkResultProjection,
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  return dispatch(guard.principal, scope, capability, payload, undefined, project);
}

export async function workGet(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
  options: WorkGetOptions = {},
) {
  if (options.strictQuery) {
    for (const key of request.nextUrl.searchParams.keys()) {
      if (!Object.hasOwn(fields, key) || (fields[key]!.type !== "string-array" && request.nextUrl.searchParams.getAll(key).length > 1)) {
        return invalidWorkRequest("unknown or repeated scalar query field");
      }
    }
  }
  const result = mapped(readQuery(request.nextUrl.searchParams, fields), fields, "query");
  if (!result.ok) return noStore(result.response);
  const payload = { ...result.payload, ...fixed };
  const refusal = options.validate?.(payload) ?? null;
  if (refusal !== null) return invalidWorkRequest(refusal);
  return noStore(await serve(request, scope, capability, payload, options.project));
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
  if (options.strictQuery && request.nextUrl.searchParams.size > 0) return invalidWorkRequest("query fields are not accepted");
  const emptyBody = options.bodyOptional && (await request.clone().text()) === "";
  const parsed = emptyBody ? { ok: true as const, body: {} } : await readCleanBody(request);
  if (!parsed.ok) return noStore(parsed.response);
  const result = mapped(parsed.body, fields, "body");
  if (!result.ok) return noStore(result.response);
  const payload = { ...result.payload, ...fixed };
  const refused = options.validate?.(payload) ?? null;
  if (refused !== null) return noStore(invalidWorkRequest(refused));
  return noStore(
    await dispatch(
      guard.principal,
      scope,
      capability,
      payload,
      options.admit,
      options.project,
    ),
  );
}
