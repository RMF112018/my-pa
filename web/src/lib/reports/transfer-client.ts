/**
 * Large report content through the SAME transfer handlers the MCP facade uses,
 * orchestrated in the browser one capability per request (WP07 contract U6).
 *
 * Staged bytes (WP06 T3 / `domain.reports.content.content_from_staged`, identity
 * encoding):
 * - markdown / text: the UTF-8 of the body;
 * - json: the JSON text of the data;
 * - mixed: the JSON text of `{"body": body, "data": data}`.
 * The server does NOT require canonical JSON here: it parses the staged text
 * with the same bounds as inline data and canonicalizes it itself. The declared
 * `sha256` / `byte_count` name the staged text exactly as sent; the version's
 * `decoded_sha256` names the server's canonical bytes (sorted keys, `,`/`:`
 * separators, no ASCII escaping), which may differ from the staged digest for
 * json and mixed.
 *
 * Upload: refuse more than 16 MiB (or nothing) before any request; begin
 * (identity) -> append chunks of exactly `chunk_byte_limit` (the last shorter),
 * each Base64 with its sha256 -> finalize -> `{sessionId, contentToken}`. Any
 * failure after begin aborts the session (best effort) and answers the refusal.
 * Finalize is sent once (it mints the token once); an ambiguous finalize answers
 * `transfer_state_unknown` ("upload state unknown — try again"), and the next
 * attempt starts a fresh upload.
 *
 * Submit: a form holds one `transferBinding()` per intent. It keeps the
 * finalized `{sessionId, contentToken}` in its closure (component memory only:
 * never rendered state, storage, a URL or a log) while the publish/update
 * answer is ambiguous, so a resubmit of the unchanged draft presents the SAME
 * transfer with the SAME idempotency key and the server replays the original
 * receipt (WP06 T10). A definitive refusal aborts the session; a changed draft
 * or an abandoned intent drops the reference and aborts it, best effort; a
 * success consumed it.
 *
 * Read: `readFullContent` reads `/content` sequentially from offset 0, checks
 * every chunk's sha256 and the whole part's sha256 (= the pointer's) with
 * WebCrypto, and answers nothing on any mismatch.
 */
import {
  abortReportTransfer,
  appendReportTransfer,
  beginReportTransfer,
  fetchReportContentRange,
  finalizeReportTransfer,
  isAmbiguous,
  refusal,
  type InlineReportContent,
  type ReportOutcome,
  type ReportRefusal,
  type TransferReportContent,
} from "./client";

/** The inline request bound: above it, content goes through a transfer (512 KiB). */
export const INLINE_REQUEST_MAX_BYTES = 524_288;
/** The most staged bytes one transfer may declare (16 MiB). */
export const MAX_STAGED_BYTES = 16_777_216;

export type ReportFormat = InlineReportContent["format"];

const encoder = new TextEncoder();

/** The staged bytes of one content value, exactly as WP06 T3 defines them. */
export function stagedBytes(format: ReportFormat, body?: string, data?: unknown): Uint8Array {
  if (format === "markdown" || format === "text") {
    if (typeof body !== "string") throw new TypeError("this format takes a body");
    return encoder.encode(body);
  }
  const text = format === "json" ? JSON.stringify(data) : JSON.stringify({ body, data });
  if (typeof text !== "string" || (format === "mixed" && typeof body !== "string")) {
    throw new TypeError("this format takes JSON data");
  }
  return encoder.encode(text);
}

/** The UTF-8 length of a request's JSON text. */
export function jsonUtf8Length(value: unknown): number {
  return encoder.encode(JSON.stringify(value)).length;
}

/** U6: the inline publish/update request is too large to send inline. */
export function needsTransfer(inlineRequest: unknown): boolean {
  return jsonUtf8Length(inlineRequest) > INLINE_REQUEST_MAX_BYTES;
}

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** SHA-256 hex via WebCrypto. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // A fresh ArrayBuffer of exactly these bytes (a subarray view may be offset).
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return hex(await crypto.subtle.digest("SHA-256", copy.buffer));
}

export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  const step = 0x8000;
  for (let index = 0; index < bytes.length; index += step) {
    binary += String.fromCharCode(...bytes.subarray(index, index + step));
  }
  return btoa(binary);
}

export function fromBase64(text: string): Uint8Array {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

const mismatch = (message: string) => refusal(0, "unavailable", "transfer_mismatch", message);

/** A finalize whose answer was lost: its token cannot be had again, so the upload is redone. */
export const UPLOAD_STATE_UNKNOWN_MESSAGE = "Upload state unknown — try again.";
const uploadStateUnknown = () => refusal(0, "unavailable", "transfer_state_unknown", UPLOAD_STATE_UNKNOWN_MESSAGE);

export interface StagedTransfer {
  readonly sessionId: string;
  readonly contentToken: string;
}

export interface UploadRequest {
  readonly format: ReportFormat;
  readonly staged: Uint8Array;
  /** The begin's own idempotency key, one per upload intent; reused on an ambiguous retry. */
  readonly idempotencyKey: string;
  readonly ttlSeconds?: number;
}

async function abortQuietly(sessionId: string): Promise<void> {
  try {
    await abortReportTransfer(sessionId);
  } catch {
    // Best effort: the session expires on its own.
  }
}

/** begin -> append* -> finalize; abort on any failure after begin. */
export async function uploadViaTransfer(request: UploadRequest): Promise<ReportOutcome<StagedTransfer>> {
  const { staged } = request;
  if (staged.byteLength === 0) {
    return refusal(0, "invalid_request", "content_empty", "There is no content to send.");
  }
  if (staged.byteLength > MAX_STAGED_BYTES) {
    return refusal(0, "invalid_request", "content_too_large", "The content is larger than 16 MiB.");
  }
  const sha256 = await sha256Hex(staged);
  const begun = await beginReportTransfer({
    format: request.format,
    byteCount: staged.byteLength,
    sha256,
    idempotencyKey: request.idempotencyKey,
    ...(request.ttlSeconds !== undefined ? { ttlSeconds: request.ttlSeconds } : {}),
  });
  if (!begun.ok) return begun;
  const session = begun.value;
  const fail = async (outcome: ReportRefusal): Promise<ReportRefusal> => {
    await abortQuietly(session.session_id);
    return outcome;
  };
  const limit = session.chunk_byte_limit;
  const expectedChunks = Math.ceil(staged.byteLength / limit);
  if (
    session.declared_byte_count !== staged.byteLength ||
    session.declared_sha256 !== sha256 ||
    session.encoding !== "identity" ||
    session.chunk_count !== expectedChunks
  ) {
    return fail(mismatch("The transfer session does not match the content."));
  }
  for (let sequence = 0; sequence < expectedChunks; sequence += 1) {
    const chunk = staged.subarray(sequence * limit, Math.min(staged.byteLength, (sequence + 1) * limit));
    const chunkSha256 = await sha256Hex(chunk);
    const appended = await appendReportTransfer(session.session_id, {
      sequence,
      chunk: toBase64(chunk),
      chunkSha256,
    });
    if (!appended.ok) return fail(appended);
    const last = sequence === expectedChunks - 1;
    if (
      appended.value.sequence !== sequence ||
      appended.value.byte_count !== chunk.byteLength ||
      appended.value.chunk_sha256 !== chunkSha256 ||
      appended.value.complete !== last
    ) {
      return fail(mismatch("The transfer did not record the chunk that was sent."));
    }
  }
  const finalized = await finalizeReportTransfer(session.session_id);
  if (!finalized.ok) return fail(isAmbiguous(finalized) ? uploadStateUnknown() : finalized);
  if (finalized.value.byte_count !== staged.byteLength || finalized.value.sha256 !== sha256) {
    return fail(mismatch("The finalized transfer does not match the content."));
  }
  return { ok: true, value: { sessionId: session.session_id, contentToken: finalized.value.content_token } };
}

/**
 * Upload, then hand `{transfer: {sessionId, contentToken}}` to `submit` (a publish
 * or update), so the token never leaves this call. One-shot: nothing is kept for
 * a resubmit, so a form that may resubmit uses `transferBinding()` instead. `submit` is retried by the
 * client itself on an ambiguous answer with the same body (same key, same
 * token); a session whose `submit` did not succeed is aborted, best effort.
 */
export async function withTransferredContent<T>(
  request: UploadRequest,
  submit: (content: TransferReportContent) => Promise<ReportOutcome<T>>,
): Promise<ReportOutcome<T>> {
  const uploaded = await uploadViaTransfer(request);
  if (!uploaded.ok) return uploaded;
  const outcome = await submit({ transfer: { sessionId: uploaded.value.sessionId, contentToken: uploaded.value.contentToken } });
  if (!outcome.ok) await abortQuietly(uploaded.value.sessionId);
  return outcome;
}

/** One intent's held transfer (see the module note). */
export interface TransferBinding {
  /**
   * Submit `signature`'s content through a transfer: reuse the transfer held for
   * the same signature after an ambiguous answer, else upload `request` afresh.
   */
  submit<T>(
    signature: string,
    request: UploadRequest,
    submit: (content: TransferReportContent) => Promise<ReportOutcome<T>>,
  ): Promise<ReportOutcome<T>>;
  /** The intent is abandoned or the draft changed: drop the held transfer, abort it best effort. */
  release(): Promise<void>;
}

export function transferBinding(): TransferBinding {
  let held: { readonly signature: string; readonly transfer: StagedTransfer } | undefined;
  async function release(): Promise<void> {
    const dropped = held;
    held = undefined;
    if (dropped) await abortQuietly(dropped.transfer.sessionId);
  }
  return {
    async submit(signature, request, submit) {
      if (held !== undefined && held.signature !== signature) await release();
      let transfer = held?.transfer;
      if (transfer === undefined) {
        const uploaded = await uploadViaTransfer(request);
        if (!uploaded.ok) return uploaded;
        transfer = uploaded.value;
      }
      held = undefined;
      const outcome = await submit({ transfer: { sessionId: transfer.sessionId, contentToken: transfer.contentToken } });
      if (outcome.ok) return outcome; // consumed by the publish/update
      if (isAmbiguous(outcome)) {
        held = { signature, transfer }; // may have been applied: keep it for the same resubmit
        return outcome;
      }
      await abortQuietly(transfer.sessionId); // definitively refused: not consumed
      return outcome;
    },
    release,
  };
}

/** A `body_chunked_read` / `encoded_chunked_read` pointer from `reports.read`. */
export interface ChunkedReadPointer {
  readonly part: "decoded" | "original";
  readonly byte_count: number;
  readonly sha256: string;
}

export interface ReadFullContentOptions {
  readonly includeWithdrawn?: boolean;
}

/** Every byte of one part of one version, each chunk and the whole verified. */
export async function readFullContent(
  reportId: string,
  versionNumber: number,
  pointer: ChunkedReadPointer,
  options: ReadFullContentOptions = {},
): Promise<ReportOutcome<Uint8Array>> {
  const total = pointer.byte_count;
  if (total > MAX_STAGED_BYTES) return mismatch("The content is larger than this viewer reads.");
  const whole = new Uint8Array(total);
  let offset = 0;
  // Bounded: every range advances the offset by at least one byte and the
  // server's ranges are up to 256 KiB, so a well-behaved read needs at most
  // 64; the guard only stops a server that never says eof.
  for (let guard = 0; guard < 1024; guard += 1) {
    const range = await fetchReportContentRange(reportId, {
      versionNumber,
      part: pointer.part,
      offset,
      ...(options.includeWithdrawn !== undefined ? { includeWithdrawn: options.includeWithdrawn } : {}),
    });
    if (!range.ok) return range;
    const chunk = range.value;
    if (
      chunk.offset !== offset ||
      chunk.part !== pointer.part ||
      chunk.version_number !== versionNumber ||
      chunk.total_byte_count !== total ||
      chunk.part_sha256 !== pointer.sha256
    ) {
      return mismatch("The content read does not match the version.");
    }
    const bytes = fromBase64(chunk.chunk);
    if (bytes.byteLength !== chunk.byte_count || offset + bytes.byteLength > total) {
      return mismatch("A content chunk has the wrong size.");
    }
    if ((await sha256Hex(bytes)) !== chunk.chunk_sha256) {
      return mismatch("A content chunk failed its digest check.");
    }
    whole.set(bytes, offset);
    offset += bytes.byteLength;
    if (chunk.eof) {
      if (offset !== total || chunk.next_offset !== null) return mismatch("The content ended early.");
      if ((await sha256Hex(whole)) !== pointer.sha256) {
        return mismatch("The content failed its digest check.");
      }
      return { ok: true, value: whole };
    }
    if (chunk.next_offset !== offset) return mismatch("The content read skipped a range.");
  }
  return mismatch("The content read did not end.");
}

/** The body/data a format's decoded bytes carry (the inverse of the server's decoded bytes). */
export function contentFromDecoded(
  format: ReportFormat,
  decoded: Uint8Array,
): { readonly body?: string; readonly data?: unknown } | null {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(decoded);
  } catch {
    return null;
  }
  if (format === "markdown" || format === "text") return { body: text };
  try {
    const parsed: unknown = JSON.parse(text);
    if (format === "json") return { data: parsed };
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    if (typeof record.body !== "string" || !Object.hasOwn(record, "data")) return null;
    return { body: record.body, data: record.data };
  } catch {
    return null;
  }
}
