/**
 * The standalone Reports BFF surface (Reports Modernization WP07, contract U4/U5).
 *
 * Every /api/reports route is one `workGet` / `workPost` call: the same
 * same-origin admission, session Principal, closed body / strict query,
 * serving resolution, refusal rendering, `publicResult` and disclosure as
 * every other work route. This module adds only what the reports surface
 * needs on top of that, and no second copy of any guard:
 *
 * - `reportsRead`: the three standalone reads (`reports.read`, `.list`,
 *   `.search`) answered through `invokeStandaloneReports` instead of
 *   `invokeGateway` (contract Amendment A1). The invoker is the only thing
 *   that differs.
 * - closed parsers for the two nested objects a report command takes,
 *   `content` and `patch`. The UI route is narrower than the capability on
 *   purpose: inline content is `{format, body?, data?}` only (no `encoding`,
 *   so no gzip+base64 from a browser), and `metadata`, `associations` and
 *   `coverage_period` are not accepted (carried to WP08).
 * - `reportConflictCurrent`: on a `409` from update/archive/delete/restore,
 *   one `reports.read` (no body, withdrawn included) supplies `current`.
 *
 * Nothing here logs. Refusal messages name a field, never its value, so no
 * body, chunk or content token can reach an error.
 */
import type { NextRequest } from "next/server";
import { invokeStandaloneReports } from "@/lib/api/gateway";
import type { StandaloneReportCapability } from "@/lib/api/decode/standalone";
import {
  isCanonicalId,
  workGet,
  workPost,
  type FieldMap,
  type WorkConflictCurrent,
  type WorkField,
  type WorkGetOptions,
  type WorkPostOptions,
} from "@/lib/api/work-route";

/** The disclosure scope every /api/reports answer carries. */
export const REPORTS_SCOPE = "reports";

/** Content formats `reports.publish` / `reports.update` / `reports.transfer.begin` accept. */
export const REPORT_FORMATS = ["markdown", "text", "json", "mixed"] as const;

const CONTENT_TOKEN = /^grxtk_[0-9a-f]{64}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;
const CALENDAR_DATE = /^\d{4}-\d{2}-\d{2}$/;
/** Python `MAX_TERMS`: topics and tags are bounded alike. */
const MAX_TERMS = 24;

type Parsed = { readonly ok: true; readonly value: unknown } | { readonly ok: false; readonly message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function onlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

/**
 * `content`, closed: inline `{format, body?, data?}` with the keys the format
 * needs (markdown/text: body; json: data; mixed: both), or a staged
 * `{transfer: {sessionId, contentToken}}` sent as the gateway spells it.
 */
export function parseReportContent(value: unknown): Parsed {
  if (!isRecord(value)) return { ok: false, message: "must be a content object" };
  if (Object.hasOwn(value, "transfer")) {
    const transfer = value.transfer;
    if (
      Object.keys(value).length !== 1 ||
      !isRecord(transfer) ||
      Object.keys(transfer).length !== 2 ||
      !isCanonicalId(transfer.sessionId, "grxfr") ||
      typeof transfer.contentToken !== "string" ||
      !CONTENT_TOKEN.test(transfer.contentToken)
    ) {
      return { ok: false, message: "transfer must be exactly {sessionId, contentToken}" };
    }
    return {
      ok: true,
      value: { transfer: { session_id: transfer.sessionId, content_token: transfer.contentToken } },
    };
  }
  if (!onlyKeys(value, ["format", "body", "data"])) {
    return { ok: false, message: "accepts only format, body and data" };
  }
  const format = value.format;
  if (typeof format !== "string" || !(REPORT_FORMATS as readonly string[]).includes(format)) {
    return { ok: false, message: "format is not an accepted value" };
  }
  const wantsBody = format !== "json";
  const wantsData = format === "json" || format === "mixed";
  if (Object.hasOwn(value, "body") !== wantsBody || Object.hasOwn(value, "data") !== wantsData) {
    return { ok: false, message: "does not carry the body/data this format takes" };
  }
  if (wantsBody && typeof value.body !== "string") return { ok: false, message: "body must be a string" };
  if (wantsData && value.data === undefined) return { ok: false, message: "data is required" };
  return {
    ok: true,
    value: {
      format,
      ...(wantsBody ? { body: value.body } : {}),
      ...(wantsData ? { data: value.data } : {}),
    },
  };
}

function isTermArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= MAX_TERMS && value.every((item) => typeof item === "string");
}

/** The patchable fields of the WP07 UI, browser spelling -> gateway spelling. */
const PATCH_FIELDS: Readonly<Record<string, string>> = {
  title: "title",
  content: "content",
  type: "type",
  topics: "topics",
  tags: "tags",
  summary: "summary",
  reportDate: "report_date",
};

/** `patch`, closed: present keys only, no nulls (an absent field is unchanged). */
export function parseReportPatch(value: unknown): Parsed {
  if (!isRecord(value)) return { ok: false, message: "must be a patch object" };
  if (!onlyKeys(value, Object.keys(PATCH_FIELDS))) {
    return { ok: false, message: "accepts only title, content, type, topics, tags, summary and reportDate" };
  }
  const patch: Record<string, unknown> = {};
  for (const [name, entry] of Object.entries(value)) {
    if (name === "content") {
      const content = parseReportContent(entry);
      if (!content.ok) return { ok: false, message: `content ${content.message}` };
      patch.content = content.value;
    } else if (name === "topics" || name === "tags") {
      if (!isTermArray(entry)) return { ok: false, message: `${name} must be an array of at most ${MAX_TERMS} strings` };
      patch[name] = entry;
    } else if (name === "reportDate") {
      if (typeof entry !== "string" || !CALENDAR_DATE.test(entry)) return { ok: false, message: "reportDate is malformed" };
      patch.report_date = entry;
    } else {
      if (typeof entry !== "string") return { ok: false, message: `${name} must be a string` };
      patch[PATCH_FIELDS[name]!] = entry;
    }
  }
  return { ok: true, value: patch };
}

const idempotencyKey: WorkField = {
  gateway: "idempotency_key", type: "string", required: true, minLength: 1, maxLength: 128, codePointLength: true,
};
const terms = (gateway: string): WorkField => ({ gateway, type: "string-array", maxItems: MAX_TERMS });
const calendarDate = (gateway: string): WorkField => ({ gateway, type: "string", pattern: CALENDAR_DATE });

/** `POST /api/reports` -> `reports.publish`. */
export const PUBLISH_FIELDS: FieldMap = {
  title: { gateway: "title", type: "string", required: true },
  content: { gateway: "content", type: "closed-object", required: true, parse: parseReportContent },
  type: { gateway: "type", type: "string" },
  topics: terms("topics"),
  tags: terms("tags"),
  summary: { gateway: "summary", type: "string" },
  reportDate: calendarDate("report_date"),
  idempotencyKey,
  clientIntentId: { gateway: "client_intent_id", type: "string" },
};

/** `POST /api/reports/[reportId]/update` -> `reports.update`. */
export const UPDATE_FIELDS: FieldMap = {
  expectedVersion: { gateway: "expected_version", type: "integer", required: true, minimum: 1 },
  patch: { gateway: "patch", type: "closed-object", required: true, parse: parseReportPatch },
  clearFields: {
    gateway: "clear_fields", type: "string-array", maxItems: 3, uniqueItems: true,
    values: ["type", "summary", "reportDate"],
    itemMapping: { type: "type", summary: "summary", reportDate: "report_date" },
  },
  changeReason: { gateway: "change_reason", type: "string", required: true },
  idempotencyKey,
};

/** `POST /api/reports/[reportId]/archive|delete|restore`. */
export const LIFECYCLE_FIELDS: FieldMap = {
  expectedLifecycleRevision: { gateway: "expected_lifecycle_revision", type: "integer", required: true, minimum: 0 },
  idempotencyKey,
  reason: { gateway: "reason", type: "string" },
};

/** `GET /api/reports` -> `reports.list`, or `reports.search` when `query` is present. */
export const CATALOG_FIELDS: FieldMap = {
  plane: { gateway: "plane", type: "string", required: true, values: ["standalone", "all"] },
  query: { gateway: "query", type: "string", nonBlank: true },
  type: { gateway: "type", type: "string" },
  topics: terms("topics"),
  tags: terms("tags"),
  lifecycleStates: {
    gateway: "lifecycle_states", type: "string-array", maxItems: 3, uniqueItems: true,
    values: ["active", "archived", "trashed"],
  },
  createdFrom: { gateway: "created_from", type: "string", format: "timestamp" },
  createdTo: { gateway: "created_to", type: "string", format: "timestamp" },
  reportDateFrom: calendarDate("report_date_from"),
  reportDateTo: calendarDate("report_date_to"),
  pageSize: { gateway: "page_size", type: "integer", minimum: 1, maximum: 100 },
  cursor: { gateway: "cursor", type: "string", minLength: 1 },
};

/** `GET /api/reports/[reportId]` -> `reports.read` (standalone). */
export const READ_FIELDS: FieldMap = {
  versionNumber: { gateway: "version_number", type: "integer", minimum: 1 },
  versionId: { gateway: "version_id", type: "string", pattern: /^grver_[A-Za-z0-9]{8,64}$/ },
  includeBody: { gateway: "include_body", type: "boolean" },
  includeManifest: { gateway: "include_manifest", type: "boolean" },
  includeWithdrawn: { gateway: "include_withdrawn", type: "boolean" },
};

/** `GET /api/reports/[reportId]/history` -> `reports.history`. */
export const HISTORY_FIELDS: FieldMap = {
  entries: { gateway: "entries", type: "string", values: ["versions", "lifecycle"] },
  pageSize: { gateway: "page_size", type: "integer", minimum: 1, maximum: 50 },
  after: { gateway: "after", type: "string", pattern: /^(?:grver|grlev)_[A-Za-z0-9]{8,64}$/ },
  includeWithdrawn: { gateway: "include_withdrawn", type: "boolean" },
  includeManifests: { gateway: "include_manifests", type: "boolean" },
};

/** `GET /api/reports/[reportId]/content` -> `reports.transfer.read_chunk`. */
export const CONTENT_FIELDS: FieldMap = {
  versionNumber: { gateway: "version_number", type: "integer", minimum: 1 },
  versionId: { gateway: "version_id", type: "string", pattern: /^grver_[A-Za-z0-9]{8,64}$/ },
  part: { gateway: "part", type: "string", values: ["decoded", "original"] },
  offset: { gateway: "offset", type: "integer", minimum: 0 },
  length: { gateway: "length", type: "integer", minimum: 1 },
  includeWithdrawn: { gateway: "include_withdrawn", type: "boolean" },
};

/** Exactly one of `version_id` / `version_number`, as `ReadReportTransferChunk` requires. */
export function exactlyOneVersion(payload: Readonly<Record<string, unknown>>): string | null {
  return (payload.version_id === undefined) === (payload.version_number === undefined)
    ? "exactly one of versionNumber or versionId is required"
    : null;
}

/** `POST /api/reports/transfers` -> `reports.transfer.begin` (encoding fixed `identity`). */
export const TRANSFER_BEGIN_FIELDS: FieldMap = {
  format: { gateway: "format", type: "string", required: true, values: REPORT_FORMATS },
  byteCount: { gateway: "byte_count", type: "integer", required: true, minimum: 1 },
  sha256: { gateway: "sha256", type: "string", required: true, pattern: SHA256_HEX },
  idempotencyKey,
  ttlSeconds: { gateway: "ttl_seconds", type: "integer", minimum: 1 },
};

/** `POST /api/reports/transfers/[sessionId]/append` -> `reports.transfer.append`. */
export const TRANSFER_APPEND_FIELDS: FieldMap = {
  sequence: { gateway: "sequence", type: "integer", required: true, minimum: 0 },
  chunk: { gateway: "chunk", type: "string", required: true, minLength: 1 },
  chunkSha256: { gateway: "chunk_sha256", type: "string", required: true, pattern: SHA256_HEX },
};

/**
 * One standalone read: `workGet` with `invokeStandaloneReports` as its
 * invoker. The query is always strict.
 */
export function reportsRead(
  request: NextRequest,
  capability: StandaloneReportCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
  options: Omit<WorkGetOptions, "invoke" | "strictQuery"> = {},
) {
  return workGet(request, REPORTS_SCOPE, capability, fields, fixed, {
    ...options,
    strictQuery: true,
    invoke: (principal, _capability, payload) => invokeStandaloneReports(principal, capability, payload),
  });
}

/**
 * U5: what a `409` from update/archive/delete/restore is answered with
 * besides the unchanged refusal — the report's head and lifecycle now, read
 * once without its body. Any failure of that read is the plain refusal.
 */
export const reportConflictCurrent: WorkConflictCurrent = async (principal, payload) => {
  const reportId = payload.report_id;
  if (typeof reportId !== "string") return null;
  const outcome = await invokeStandaloneReports(principal, "reports.read", {
    report_id: reportId,
    include_body: false,
    include_withdrawn: true,
  });
  if (!outcome.ok || outcome.result.report_id !== reportId) return null;
  const read = outcome.result;
  return {
    headVersionNumber: read.head_version_number,
    headVersionId: read.head_version_id,
    lifecycleState: read.lifecycle_state,
    lifecycleRevision: read.lifecycle_revision,
    held: read.held,
  };
};

type ReportMutation =
  | "reports.publish"
  | "reports.update"
  | "reports.archive"
  | "reports.delete"
  | "reports.restore"
  | "reports.transfer.begin"
  | "reports.transfer.append"
  | "reports.transfer.finalize"
  | "reports.transfer.abort";

const CONFLICT_READ: ReadonlySet<ReportMutation> = new Set([
  "reports.update",
  "reports.archive",
  "reports.delete",
  "reports.restore",
]);

/** One report mutation: `workPost`, strict (no query), with U5 where it applies. */
export function reportsMutation(
  request: NextRequest,
  capability: ReportMutation,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
  options: Pick<WorkPostOptions, "bodyOptional"> = {},
) {
  return workPost(request, REPORTS_SCOPE, capability, fields, fixed, {
    ...options,
    strictQuery: true,
    ...(CONFLICT_READ.has(capability) ? { conflictCurrent: reportConflictCurrent } : {}),
  });
}

/** A path `reportId` is a canonical standalone report (`grpt_`). */
export const isReportId = (value: unknown): value is string => isCanonicalId(value, "grpt");
/** A path `sessionId` is a canonical transfer session (`grxfr_`). */
export const isTransferSessionId = (value: unknown): value is string => isCanonicalId(value, "grxfr");
