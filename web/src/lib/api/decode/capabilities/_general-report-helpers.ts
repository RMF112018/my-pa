/**
 * Shared vocabulary of the standalone (general) report plane decoders (WP07 U2).
 *
 * Every value set below is the Python one (`my_pa.domain.reports.vocabulary`,
 * `my_pa.domain.reports.creator`, `my_pa.domain.common.identifiers`); the
 * success-parity fixtures are built from the real payload builders, so a drift
 * on either side fails `parity.test.ts`. The decoders are closed: an unknown key
 * at any depth is `upstream_contract_invalid`, and no failure echoes a value.
 */
import { closed, ok } from "../primitives";
import type { Decoder } from "../types";
import {
  checked,
  enumeration,
  identifier,
  integer,
  strictObject,
  text,
} from "./continuity.projects.create";

export const STANDALONE_PLANE = ["standalone"] as const;
export const REPORT_LIFECYCLE_STATES = ["active", "archived", "trashed"] as const;
export type ReportLifecycleState = (typeof REPORT_LIFECYCLE_STATES)[number];
export const REPORT_LIFECYCLE_OPERATIONS = ["archive", "delete", "restore"] as const;
export type ReportLifecycleOperation = (typeof REPORT_LIFECYCLE_OPERATIONS)[number];
export const REPORT_CONTENT_FORMATS = ["markdown", "text", "json", "mixed"] as const;
export type ReportContentFormat = (typeof REPORT_CONTENT_FORMATS)[number];
export const REPORT_CONTENT_ENCODINGS = ["identity", "gzip+base64"] as const;
export type ReportContentEncoding = (typeof REPORT_CONTENT_ENCODINGS)[number];
export const REPORT_STORAGE_KINDS = ["inline", "managed_blob"] as const;
export const REPORT_CHANGE_KINDS = ["initial", "content", "metadata"] as const;
export type ReportChangeKind = (typeof REPORT_CHANGE_KINDS)[number];
export const REPORT_RECEIPT_OUTCOMES = ["applied", "no_op"] as const;
export type ReportReceiptOutcome = (typeof REPORT_RECEIPT_OUTCOMES)[number];
export const REPORT_CREATOR_KINDS = ["local_principal", "remote_client"] as const;
export const REPORT_HISTORY_ENTRIES = ["versions", "lifecycle"] as const;
export const REPORT_TRANSFER_PARTS = ["decoded", "original"] as const;
export type ReportTransferPart = (typeof REPORT_TRANSFER_PARTS)[number];

export const reportId = identifier("grpt");
export const reportVersionId = identifier("grver");
export const reportContentId = identifier("grcnt");
export const reportReceiptId = identifier("grrc");
export const reportLifecycleEventId = identifier("grlev");
export const transferSessionId = identifier("grxfr");
export const correlationId = identifier("corr");
export const auditId = identifier("audit");

/** A creator or author as outputs carry it: its kind and pseudonym only (WP05 A4). */
export const reportCreator = strictObject({
  kind: enumeration(REPORT_CREATOR_KINDS),
  id: checked(text(), (value) => /^gcrt_[0-9a-f]{40}$/.test(value)),
});

/** Python `CONTENT_TOKEN_PATTERN`: opaque, one-use; decoded only, never logged or echoed. */
export const CONTENT_TOKEN_PATTERN = /^grxtk_[0-9a-f]{64}$/;
export const contentToken = checked(text(), (value) => CONTENT_TOKEN_PATTERN.test(value));

/** Canonical padded standard Base64 of at least one byte. */
export const base64Chunk = checked(text(1), (value) =>
  /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value),
);

/** A positive count of bytes (a declared or staged size). */
export const positiveCount = integer(1);
export const count = integer(0);

/** A JSON object carried as data (a manifest): any record, never an array or null. */
export const jsonRecord: Decoder<Readonly<Record<string, unknown>>> = (input) =>
  input !== null && typeof input === "object" && !Array.isArray(input)
    ? ok(input as Readonly<Record<string, unknown>>)
    : closed("upstream_contract_invalid", "Invalid capability success contract");
