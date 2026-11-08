/** `reports.update` (WP07 U2): Python `service._general_update_payload`, closed. */
import type { Decoder } from "../types";
import {
  boolean,
  digest,
  enumeration,
  integer,
  nullable,
  strictObject,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_CHANGE_KINDS,
  REPORT_RECEIPT_OUTCOMES,
  STANDALONE_PLANE,
  auditId,
  correlationId,
  reportContentId,
  reportId,
  reportReceiptId,
  reportVersionId,
} from "./_general-report-helpers";

const result = strictObject({
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  outcome: enumeration(REPORT_RECEIPT_OUTCOMES),
  version_id: reportVersionId,
  version_number: integer(1),
  change_kind: nullable(enumeration(REPORT_CHANGE_KINDS)),
  content_id: reportContentId,
  decoded_sha256: digest,
  manifest_sha256: digest,
  receipt: strictObject({
    receipt_id: reportReceiptId,
    operation: enumeration(["update"] as const),
    outcome: enumeration(REPORT_RECEIPT_OUTCOMES),
    expected_version: integer(1),
    issued_at: timestamp,
    correlation_id: correlationId,
    audit_id: auditId,
  }),
  replayed: boolean,
});

export type ReportsUpdateResult = Decoded<typeof result>;
export const decodeReportsUpdate: Decoder<ReportsUpdateResult> = result;
