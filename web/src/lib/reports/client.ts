/**
 * The browser side of the standalone Reports BFF (Reports Modernization WP07,
 * contract U4-U7, Amendment A2).
 *
 * One typed function per /api/reports route. Every answer is decoded strictly
 * again with the capability's own closed decoder (the same discipline as
 * `lib/api/work-client.ts`), so a view never renders a shape it was not
 * promised. Every function answers a `ReportOutcome`: `ok` with the decoded
 * value, or a `ReportRefusal` carrying the BFF's status, class, code and
 * message (and, for a 409 from update/archive/delete/restore, `current`).
 *
 * Idempotency: the caller holds one key per intent (`reportIntent`). A POST
 * whose answer is ambiguous (the network failed, or 502/503/504) is retried
 * once here with the SAME body, so the SAME key; the server's receipt replay
 * makes that safe. A definitive refusal is never retried, and a conflict is
 * never retried or overwritten (U5). `reports.transfer.finalize` is the one
 * POST sent exactly once: it mints its content token once, so a retry after a
 * lost answer would only be refused (`transfer-client.ts` answers an ambiguous
 * finalize as "upload state unknown" and the next attempt uploads afresh).
 * Only a transfer's begin and append take an `AbortSignal` (`request_cancelled`,
 * never retried); no publish, update, finalize or abort request is ever aborted.
 *
 * Nothing here logs, and no body, chunk or content token is put in a URL: every
 * content-bearing request is a POST body.
 */
import { mutationKey } from "@/lib/api/work-client";
import type { Decoder } from "@/lib/api/decode/types";
import {
  decodeStandaloneReportList,
  decodeStandaloneReportSearch,
  type StandaloneReportListResult,
  type StandaloneReportSearchResult,
} from "@/lib/api/decode/capabilities/reports.standalone";
import { decodeReportReadAnswer, type ReportReadAnswer } from "./content-guards";
import { decodeReportsPublish, type ReportsPublishResult } from "@/lib/api/decode/capabilities/reports.publish";
import { decodeReportsUpdate, type ReportsUpdateResult } from "@/lib/api/decode/capabilities/reports.update";
import { decodeReportsHistory, type ReportsHistoryResult } from "@/lib/api/decode/capabilities/reports.history";
import { decodeReportsArchive } from "@/lib/api/decode/capabilities/reports.archive";
import { decodeReportsDelete } from "@/lib/api/decode/capabilities/reports.delete";
import { decodeReportsRestore } from "@/lib/api/decode/capabilities/reports.restore";
import type { ReportLifecycleResult } from "@/lib/api/decode/capabilities/_general-report-lifecycle";
import {
  decodeReportsTransferBegin,
  type ReportsTransferBeginResult,
} from "@/lib/api/decode/capabilities/reports.transfer.begin";
import {
  decodeReportsTransferAppend,
  type ReportsTransferAppendResult,
} from "@/lib/api/decode/capabilities/reports.transfer.append";
import {
  decodeReportsTransferFinalize,
  type ReportsTransferFinalizeResult,
} from "@/lib/api/decode/capabilities/reports.transfer.finalize";
import {
  decodeReportsTransferAbort,
  type ReportsTransferAbortResult,
} from "@/lib/api/decode/capabilities/reports.transfer.abort";
import {
  decodeReportsTransferReadChunk,
  type ReportsTransferReadChunkResult,
} from "@/lib/api/decode/capabilities/reports.transfer.read_chunk";

// --- outcomes ------------------------------------------------------------------

/** U5: the report's head and lifecycle at the moment a 409 was answered. */
export interface ReportConflictCurrent {
  readonly headVersionNumber: number;
  readonly headVersionId: string;
  readonly lifecycleState: string;
  readonly lifecycleRevision: number;
  readonly held: boolean;
}

/**
 * A refusal. `status` 0 means no HTTP answer was had: the request was refused
 * in the browser before it was sent (`code` names why), or the network failed
 * (`transport_failed`).
 */
export interface ReportRefusal {
  readonly ok: false;
  readonly status: number;
  readonly errorClass: string;
  readonly code: string;
  readonly message: string;
  readonly current?: ReportConflictCurrent;
}

export type ReportOutcome<T> = { readonly ok: true; readonly value: T } | ReportRefusal;

export function refusal(
  status: number,
  errorClass: string,
  code: string,
  message: string,
  current?: ReportConflictCurrent,
): ReportRefusal {
  return { ok: false, status, errorClass, code, message, ...(current ? { current } : {}) };
}

/** An answer that may or may not have been applied: retried with the same key, never rotated. */
export function isAmbiguous(outcome: ReportOutcome<unknown>): boolean {
  return !outcome.ok && (outcome.code === "transport_failed" || [502, 503, 504].includes(outcome.status));
}

const contractInvalid = () =>
  refusal(503, "unavailable", "upstream_contract_invalid", "the route success did not match the capability contract");

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function conflictCurrent(value: unknown): ReportConflictCurrent | undefined {
  if (!isRecord(value)) return undefined;
  const { headVersionNumber, headVersionId, lifecycleState, lifecycleRevision, held } = value;
  if (
    typeof headVersionNumber !== "number" || !Number.isSafeInteger(headVersionNumber) ||
    typeof headVersionId !== "string" ||
    typeof lifecycleState !== "string" ||
    typeof lifecycleRevision !== "number" || !Number.isSafeInteger(lifecycleRevision) ||
    typeof held !== "boolean"
  ) return undefined;
  return { headVersionNumber, headVersionId, lifecycleState, lifecycleRevision, held };
}

/** Decode one BFF answer: `{shape:"backend", ...result, disclosure}` or a refusal envelope. */
async function decodeAnswer<T>(response: Response, decode: Decoder<T>): Promise<ReportOutcome<T>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return response.ok ? contractInvalid() : refusal(response.status, "unavailable", "unreadable_answer", `Request failed (${response.status})`);
  }
  if (!response.ok) {
    const envelope = isRecord(body) ? body : {};
    const error = isRecord(envelope.error) ? envelope.error : {};
    return refusal(
      response.status,
      typeof error.errorClass === "string" ? error.errorClass : "unavailable",
      typeof error.code === "string" ? error.code : "refused",
      typeof error.message === "string" ? error.message : `Request failed (${response.status})`,
      response.status === 409 ? conflictCurrent(envelope.current) : undefined,
    );
  }
  if (!isRecord(body)) return contractInvalid();
  const { shape, disclosure, ...result } = body;
  void disclosure;
  if (shape !== "backend") return contractInvalid();
  const decoded = decode(result);
  return decoded.ok ? { ok: true, value: decoded.value } : contractInvalid();
}

/** How many times one POST is sent when its answer is ambiguous (the same body each time). */
export const POST_ATTEMPTS = 2;

/** The request was stopped by its owner (`signal`) before an answer was had: never retried. */
export const cancelled = () => refusal(0, "unavailable", "request_cancelled", "The request was stopped.");

async function send<T>(
  path: string,
  decode: Decoder<T>,
  body?: unknown,
  options: { readonly retry?: boolean; readonly signal?: AbortSignal } = {},
): Promise<ReportOutcome<T>> {
  const { signal } = options;
  const init: RequestInit = body === undefined
    ? { method: "GET", cache: "no-store" }
    : { method: "POST", cache: "no-store", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  if (signal !== undefined) init.signal = signal;
  const attempts = body === undefined || options.retry === false ? 1 : POST_ATTEMPTS;
  let outcome: ReportOutcome<T> = refusal(0, "unavailable", "transport_failed", "The request could not be sent.");
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (signal?.aborted) return cancelled();
    let response: Response;
    try {
      response = await fetch(path, init);
    } catch {
      if (signal?.aborted) return cancelled();
      outcome = refusal(0, "unavailable", "transport_failed", "The request could not be sent.");
      continue;
    }
    outcome = await decodeAnswer(response, decode);
    if (!isAmbiguous(outcome)) return outcome;
  }
  return outcome;
}

// --- idempotency -----------------------------------------------------------------

/**
 * One key per intent (work-client's `mutationKey` style). The key is kept for
 * the same payload while answers are ambiguous; it rotates after success or a
 * definitive refusal, and whenever the payload changes, so a resubmission after
 * a conflict always carries a NEW key (U5, A2).
 */
export function reportIntent(prefix: string) {
  let signature: string | undefined;
  let key: string | undefined;
  return {
    keyFor(payload: unknown): string {
      const next = JSON.stringify(payload);
      if (next !== signature || key === undefined) {
        signature = next;
        key = mutationKey(prefix);
      }
      return key;
    },
    settle(outcome: ReportOutcome<unknown>): void {
      if (!isAmbiguous(outcome)) {
        signature = undefined;
        key = undefined;
      }
    },
  };
}

// --- A2: stale versus other conflicts --------------------------------------------

/** What the user submitted that a 409 is judged against. */
export type SubmittedExpectation =
  | { readonly expectedVersion: number }
  | { readonly expectedLifecycleRevision: number };

export type ConflictClassification =
  | { readonly kind: "none" }
  | { readonly kind: "stale"; readonly current: ReportConflictCurrent }
  | { readonly kind: "conflict" };

export const STALE_MESSAGE = (headVersionNumber: number) =>
  `This report changed since you opened it (now version ${headVersionNumber}).`;
/** A stale lifecycle action (A2): the lifecycle moved on, not (necessarily) the version. */
const LIFECYCLE_STATE_WORDS: Readonly<Record<string, string>> = { active: "active", archived: "archived", trashed: "in Trash" };
export const LIFECYCLE_STALE_MESSAGE = (lifecycleState: string) =>
  `This report's state changed since you opened it (now ${Object.hasOwn(LIFECYCLE_STATE_WORDS, lifecycleState) ? LIFECYCLE_STATE_WORDS[lifecycleState] : lifecycleState}).`;
export const CONFLICT_MESSAGE =
  "This request conflicted with an earlier one; review the latest state and submit again.";

/**
 * Amendment A2: a 409 whose `current` differs from what was submitted (head
 * version for an update, lifecycle revision for a lifecycle action) is the
 * stale case; any other 409 (same value, or no `current`) is the generic one.
 */
export function classifyConflict(
  outcome: ReportOutcome<unknown>,
  submitted: SubmittedExpectation,
): ConflictClassification {
  if (outcome.ok || outcome.status !== 409) return { kind: "none" };
  const current = outcome.current;
  if (current === undefined) return { kind: "conflict" };
  const changed = "expectedVersion" in submitted
    ? current.headVersionNumber !== submitted.expectedVersion
    : current.lifecycleRevision !== submitted.expectedLifecycleRevision;
  return changed ? { kind: "stale", current } : { kind: "conflict" };
}

// --- reads -----------------------------------------------------------------------

export type ReportPlane = "standalone" | "all";
export type ReportLifecycleFilter = "active" | "archived" | "trashed";

export interface CatalogQuery {
  readonly plane: ReportPlane;
  readonly query?: string;
  readonly type?: string;
  readonly tags?: readonly string[];
  readonly topics?: readonly string[];
  readonly lifecycleStates?: readonly ReportLifecycleFilter[];
  readonly pageSize?: number;
  readonly cursor?: string;
}

/** The query string of one catalog read; `plane` is always sent. */
export function catalogPath(query: CatalogQuery): string {
  const search = new URLSearchParams({ plane: query.plane });
  const text = query.query?.trim();
  if (text) search.set("query", text);
  const type = query.type?.trim();
  if (type) search.set("type", type);
  for (const tag of query.tags ?? []) search.append("tags", tag);
  for (const topic of query.topics ?? []) search.append("topics", topic);
  for (const state of query.lifecycleStates ?? []) search.append("lifecycleStates", state);
  if (query.pageSize !== undefined) search.set("pageSize", String(query.pageSize));
  if (query.cursor !== undefined) search.set("cursor", query.cursor);
  return `/api/reports?${search.toString()}`;
}

export type CatalogPage = StandaloneReportListResult | StandaloneReportSearchResult;

/** `GET /api/reports`: `reports.search` when a query is present, else `reports.list`. */
export function fetchReportCatalog(query: CatalogQuery): Promise<ReportOutcome<CatalogPage>> {
  const searching = Boolean(query.query?.trim());
  return send<CatalogPage>(catalogPath(query), searching ? decodeStandaloneReportSearch : decodeStandaloneReportList);
}

const reportPath = (reportId: string) => `/api/reports/${encodeURIComponent(reportId)}`;

export interface ReadOptions {
  readonly versionNumber?: number;
  readonly includeBody?: boolean;
  readonly includeWithdrawn?: boolean;
}

/**
 * `GET /api/reports/[reportId]`: one exact version (or the head), with the
 * BFF's `identity_keys_withheld` flag when it applies (content-guards.ts).
 */
export function fetchReport(reportId: string, options: ReadOptions = {}): Promise<ReportOutcome<ReportReadAnswer>> {
  const search = new URLSearchParams();
  if (options.versionNumber !== undefined) search.set("versionNumber", String(options.versionNumber));
  if (options.includeBody !== undefined) search.set("includeBody", String(options.includeBody));
  if (options.includeWithdrawn !== undefined) search.set("includeWithdrawn", String(options.includeWithdrawn));
  const query = search.size > 0 ? `?${search.toString()}` : "";
  return send(`${reportPath(reportId)}${query}`, decodeReportReadAnswer);
}

export interface HistoryOptions {
  readonly entries: "versions" | "lifecycle";
  readonly pageSize?: number;
  readonly after?: string;
  readonly includeWithdrawn?: boolean;
}

/** `GET /api/reports/[reportId]/history`: one page of versions or lifecycle events. */
export function fetchReportHistory(reportId: string, options: HistoryOptions): Promise<ReportOutcome<ReportsHistoryResult>> {
  const search = new URLSearchParams({ entries: options.entries });
  if (options.pageSize !== undefined) search.set("pageSize", String(options.pageSize));
  if (options.after !== undefined) search.set("after", options.after);
  if (options.includeWithdrawn !== undefined) search.set("includeWithdrawn", String(options.includeWithdrawn));
  return send(`${reportPath(reportId)}/history?${search.toString()}`, decodeReportsHistory);
}

export interface ContentRangeOptions {
  readonly versionNumber: number;
  readonly part?: "decoded" | "original";
  readonly offset: number;
  readonly length?: number;
  readonly includeWithdrawn?: boolean;
}

/** `GET /api/reports/[reportId]/content`: one verified range of one pinned version. */
export function fetchReportContentRange(
  reportId: string,
  options: ContentRangeOptions,
): Promise<ReportOutcome<ReportsTransferReadChunkResult>> {
  const search = new URLSearchParams({ versionNumber: String(options.versionNumber), offset: String(options.offset) });
  if (options.part !== undefined) search.set("part", options.part);
  if (options.length !== undefined) search.set("length", String(options.length));
  if (options.includeWithdrawn !== undefined) search.set("includeWithdrawn", String(options.includeWithdrawn));
  return send(`${reportPath(reportId)}/content?${search.toString()}`, decodeReportsTransferReadChunk);
}

// --- mutations -------------------------------------------------------------------

/** Inline content as the route accepts it (no `encoding`: no gzip from a browser). */
export type InlineReportContent =
  | { readonly format: "markdown" | "text"; readonly body: string }
  | { readonly format: "json"; readonly data: unknown }
  | { readonly format: "mixed"; readonly body: string; readonly data: unknown };

/** Staged content: a finalized transfer, presented once. */
export interface TransferReportContent {
  readonly transfer: { readonly sessionId: string; readonly contentToken: string };
}

export type ReportContentInput = InlineReportContent | TransferReportContent;

export interface PublishRequest {
  readonly title: string;
  readonly content: ReportContentInput;
  readonly type?: string;
  readonly topics?: readonly string[];
  readonly tags?: readonly string[];
  readonly summary?: string;
  readonly reportDate?: string;
  readonly idempotencyKey: string;
  readonly clientIntentId?: string;
}

/** `POST /api/reports` -> `reports.publish`. */
export function publishReport(request: PublishRequest): Promise<ReportOutcome<ReportsPublishResult>> {
  return send("/api/reports", decodeReportsPublish, request);
}

export interface ReportPatch {
  readonly title?: string;
  readonly content?: ReportContentInput;
  readonly type?: string;
  readonly topics?: readonly string[];
  readonly tags?: readonly string[];
  readonly summary?: string;
  readonly reportDate?: string;
}

export interface UpdateRequest {
  readonly expectedVersion: number;
  readonly patch: ReportPatch;
  readonly clearFields?: readonly ("type" | "summary" | "reportDate")[];
  readonly changeReason: string;
  readonly idempotencyKey: string;
}

/** `POST /api/reports/[reportId]/update` -> `reports.update`. */
export function updateReport(reportId: string, request: UpdateRequest): Promise<ReportOutcome<ReportsUpdateResult>> {
  return send(`${reportPath(reportId)}/update`, decodeReportsUpdate, request);
}

export type LifecycleOperation = "archive" | "delete" | "restore";

export interface LifecycleRequest {
  readonly expectedLifecycleRevision: number;
  readonly idempotencyKey: string;
  readonly reason?: string;
}

const LIFECYCLE_DECODERS: { readonly [O in LifecycleOperation]: Decoder<ReportLifecycleResult> } = {
  archive: decodeReportsArchive,
  delete: decodeReportsDelete,
  restore: decodeReportsRestore,
};

/** `POST /api/reports/[reportId]/archive|delete|restore`. */
export function changeReportLifecycle(
  reportId: string,
  operation: LifecycleOperation,
  request: LifecycleRequest,
): Promise<ReportOutcome<ReportLifecycleResult>> {
  const body = request.reason?.trim()
    ? { ...request, reason: request.reason.trim() }
    : { expectedLifecycleRevision: request.expectedLifecycleRevision, idempotencyKey: request.idempotencyKey };
  return send(`${reportPath(reportId)}/${operation}`, LIFECYCLE_DECODERS[operation], body);
}

// --- transfers (one capability per request; orchestrated by transfer-client.ts) --

export interface TransferBeginRequest {
  readonly format: InlineReportContent["format"];
  readonly byteCount: number;
  readonly sha256: string;
  readonly idempotencyKey: string;
  readonly ttlSeconds?: number;
}

const transferPath = (sessionId: string) => `/api/reports/transfers/${encodeURIComponent(sessionId)}`;

/** `signal` stops the begin (an upload whose owner left); see transfer-client.ts. */
export function beginReportTransfer(
  request: TransferBeginRequest,
  signal?: AbortSignal,
): Promise<ReportOutcome<ReportsTransferBeginResult>> {
  return send("/api/reports/transfers", decodeReportsTransferBegin, request, signal ? { signal } : {});
}

/** `signal` stops the append (an upload whose owner left); see transfer-client.ts. */
export function appendReportTransfer(
  sessionId: string,
  request: { readonly sequence: number; readonly chunk: string; readonly chunkSha256: string },
  signal?: AbortSignal,
): Promise<ReportOutcome<ReportsTransferAppendResult>> {
  return send(`${transferPath(sessionId)}/append`, decodeReportsTransferAppend, request, signal ? { signal } : {});
}

export function finalizeReportTransfer(sessionId: string): Promise<ReportOutcome<ReportsTransferFinalizeResult>> {
  // Never retried automatically: the token is minted once (see the module note).
  return send(`${transferPath(sessionId)}/finalize`, decodeReportsTransferFinalize, {}, { retry: false });
}

export function abortReportTransfer(sessionId: string): Promise<ReportOutcome<ReportsTransferAbortResult>> {
  return send(`${transferPath(sessionId)}/abort`, decodeReportsTransferAbort, {});
}
