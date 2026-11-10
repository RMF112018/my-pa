/**
 * What the browser report forms refuse to send or to edit, and the one flag the
 * Reports read route adds (Reports Modernization WP08, C-WP07 R1 #4 and #6).
 *
 * Identity keys. The BFF refuses any request body that names a principal
 * (`rejectCallerSuppliedPrincipal`, recursive), so inline JSON data holding
 * such a key is refused with `400 caller_supplied_principal`, while the same
 * data above 512 KiB travels as staged bytes and is accepted. The forms
 * therefore run that SAME check (`holdsIdentityKeys`, no second key list) over
 * the JSON data before they choose inline or transfer, and refuse both paths
 * alike before any request. On read, every work route's `publicResult` strips
 * `principal_id` / `principalId` keys anywhere in a result (no identity echo);
 * the Reports read route says when that strip removed something from
 * `content.data` with `identity_keys_withheld: true`, so the edit form shows
 * the content read-only instead of silently dropping those keys on save.
 * MCP clients may still store any JSON: nothing here changes the server.
 *
 * Numbers. The browser's `JSON.parse` keeps a number as an IEEE double, so an
 * integer beyond 2^53 - 1 (and any literal whose value a double cannot hold
 * exactly) changes when the data is edited and saved. `hasUnsafeJsonNumber`
 * reads the JSON source text (numbers outside strings) and flags a literal whose
 * magnitude exceeds `Number.MAX_SAFE_INTEGER`, that is not finite, or whose
 * parsed value is not the same decimal value (excess fractional precision
 * included); it serves typed text and chunk-loaded content.
 * `hasUnsafeNumberValue` checks data that was already parsed on the way here
 * (the BFF parses the gateway's answer, so a read's inline data has no source
 * text left) and flags only a number whose magnitude exceeds
 * `Number.MAX_SAFE_INTEGER` or that is not finite. The two do NOT answer the
 * same: a fractional literal that lost precision when parsed (for example
 * `0.12345678901234567890123`) is invisible once parsed, so inline-loaded
 * content holding one is not locked and an edit saves the rounded value.
 *
 * Nothing here logs, and no message carries a value from the data.
 */
import { FORBIDDEN_IDENTITY_FIELDS } from "@/contracts/identity";
import { CallerSuppliedPrincipalError, rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";
import {
  decodeStandaloneReportRead,
  type StandaloneReportReadResult,
} from "@/lib/api/decode/capabilities/reports.standalone";
import type { Decoder } from "@/lib/api/decode/types";

// --- identity keys -----------------------------------------------------------------

/** Whether `data` holds a key the BFF refuses as a caller-supplied identity (the BFF's own check). */
export function holdsIdentityKeys(data: unknown): boolean {
  try {
    rejectCallerSuppliedPrincipal(data);
    return false;
  } catch (error) {
    if (error instanceof CallerSuppliedPrincipalError) return true;
    throw error;
  }
}

export const IDENTITY_KEYS_MESSAGE =
  `The JSON data contains an identity key (${FORBIDDEN_IDENTITY_FIELDS.join(", ")}). ` +
  "Reports cannot be saved with those keys from this page; remove or rename them.";

/** The keys `publicResult` strips everywhere in a work-route result (work-route.ts). */
const STRIPPED_IDENTITY_KEYS: readonly string[] = ["principal_id", "principalId"];

/** Whether the BFF's result strip would remove anything from `data`. */
export function losesStrippedIdentityKeys(data: unknown): boolean {
  if (data === null || typeof data !== "object") return false;
  if (Array.isArray(data)) return data.some(losesStrippedIdentityKeys);
  return Object.entries(data as Record<string, unknown>).some(
    ([key, value]) => STRIPPED_IDENTITY_KEYS.includes(key) || losesStrippedIdentityKeys(value),
  );
}

/** The closed flag the Reports read route adds to a read whose `content.data` lost identity keys. */
export const IDENTITY_KEYS_WITHHELD = "identity_keys_withheld";

/** A standalone read as the BFF answers it: the gateway's read plus the closed flag. */
export type ReportReadAnswer = StandaloneReportReadResult & { readonly identity_keys_withheld?: true };

/**
 * The browser decoder of `GET /api/reports/[reportId]`: the flag is absent or
 * exactly `true`; everything else is the gateway read's own strict decoder.
 */
export const decodeReportReadAnswer: Decoder<ReportReadAnswer> = (input) => {
  if (input === null || typeof input !== "object" || Array.isArray(input) || !Object.hasOwn(input, IDENTITY_KEYS_WITHHELD)) {
    return decodeStandaloneReportRead(input);
  }
  const { [IDENTITY_KEYS_WITHHELD]: flag, ...read } = input as Record<string, unknown>;
  if (flag !== true) {
    return { ok: false, code: "upstream_contract_invalid", message: `${IDENTITY_KEYS_WITHHELD} must be true when present` };
  }
  const decoded = decodeStandaloneReportRead(read);
  return decoded.ok ? { ok: true, value: { ...decoded.value, identity_keys_withheld: true } } : decoded;
};

// --- numbers -----------------------------------------------------------------------

export const UNSAFE_NUMBER_MESSAGE =
  "The JSON data contains a number this browser cannot keep exactly (beyond 9,007,199,254,740,991). " +
  "Store it as a string, or save the report through an MCP client.";

const NUMBER_LITERAL = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const NUMBER_PARTS = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/;

/** A decimal literal's exact value as `digits e exponent` (no leading or trailing zeros; zero is "0"). */
function exactDecimal(literal: string): string {
  const parts = NUMBER_PARTS.exec(literal);
  if (parts === null) return literal;
  const [, sign, whole, fraction = "", exponent = "0"] = parts;
  const digits = `${whole}${fraction}`.replace(/^0+/, "");
  if (digits === "") return "0";
  const significant = digits.replace(/0+$/, "");
  const scale = BigInt(exponent) - BigInt(fraction.length) + BigInt(digits.length - significant.length);
  return `${sign}${significant}e${scale.toString()}`;
}

function unsafeNumber(value: number): boolean {
  return !Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER;
}

/** Whether one JSON number literal changes when the browser parses it. */
function unsafeLiteral(literal: string): boolean {
  const value = Number(literal);
  if (unsafeNumber(value)) return true;
  return exactDecimal(literal) !== exactDecimal(String(value));
}

/**
 * Whether JSON source text holds a number (outside strings) the browser cannot
 * keep exactly: magnitude beyond `Number.MAX_SAFE_INTEGER`, not finite, or a
 * literal whose parsed value is not the same decimal value.
 */
export function hasUnsafeJsonNumber(text: string): boolean {
  let index = 0;
  while (index < text.length) {
    const char = text[index]!;
    if (char === '"') {
      index += 1;
      while (index < text.length && text[index] !== '"') index += text[index] === "\\" ? 2 : 1;
      index += 1;
      continue;
    }
    if (char === "-" || (char >= "0" && char <= "9")) {
      NUMBER_LITERAL.lastIndex = index;
      const match = NUMBER_LITERAL.exec(text);
      if (match === null) {
        index += 1;
        continue;
      }
      if (unsafeLiteral(match[0])) return true;
      index += match[0].length;
      continue;
    }
    index += 1;
  }
  return false;
}

/**
 * The parsed-data check (no source text is left): magnitude beyond
 * `Number.MAX_SAFE_INTEGER` or not finite only; excess fractional precision is
 * already gone and cannot be detected here.
 */
export function hasUnsafeNumberValue(data: unknown): boolean {
  if (typeof data === "number") return unsafeNumber(data);
  if (data === null || typeof data !== "object") return false;
  if (Array.isArray(data)) return data.some(hasUnsafeNumberValue);
  return Object.values(data as Record<string, unknown>).some(hasUnsafeNumberValue);
}

// --- the forms' checks -------------------------------------------------------------

/**
 * Why typed JSON data may not be sent (new or edit, inline or transfer alike),
 * or null. `text` is the JSON source as typed; `data` is its parse.
 */
export function jsonSubmitProblem(text: string, data: unknown): string | null {
  if (holdsIdentityKeys(data)) return IDENTITY_KEYS_MESSAGE;
  if (hasUnsafeJsonNumber(text)) return UNSAFE_NUMBER_MESSAGE;
  return null;
}

export type ContentLock = "identity" | "precision";

export const CONTENT_LOCK_MESSAGES: { readonly [L in ContentLock]: string } = {
  identity:
    "This report's JSON data contains identity keys, which this page does not show in full or send back. " +
    "Its content is read-only here; you can still change its details.",
  precision:
    "This report's JSON data contains numbers this browser cannot keep exactly. " +
    "Its content is read-only here; you can still change its details.",
};

/**
 * Why loaded content must stay read-only in the edit form, or null: the read's
 * flag, the same identity check the forms submit with, or an unsafe number.
 * `text` is the source text when the content was read in chunks.
 */
export function contentLockOf(content: {
  readonly withheld?: boolean;
  readonly data?: unknown;
  readonly text?: string;
}): ContentLock | null {
  if (content.withheld === true || (content.data !== undefined && holdsIdentityKeys(content.data))) return "identity";
  if (content.text !== undefined ? hasUnsafeJsonNumber(content.text) : hasUnsafeNumberValue(content.data)) {
    return "precision";
  }
  return null;
}
