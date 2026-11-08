/**
 * The one answer shape of `reports.archive`, `reports.delete` and
 * `reports.restore` (WP07 U2): Python `service._general_lifecycle_payload`,
 * closed, with the operation pinned to the capability that answers it.
 */
import type { Decoder } from "../types";
import {
  boolean,
  enumeration,
  nullable,
  strictObject,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_LIFECYCLE_STATES,
  REPORT_RECEIPT_OUTCOMES,
  STANDALONE_PLANE,
  auditId,
  correlationId,
  count,
  reportId,
  reportLifecycleEventId,
  reportReceiptId,
  type ReportLifecycleOperation,
} from "./_general-report-helpers";

function lifecycleResult<const O extends ReportLifecycleOperation>(operation: O) {
  const op = enumeration([operation] as const);
  return strictObject({
    plane: enumeration(STANDALONE_PLANE),
    report_id: reportId,
    operation: op,
    outcome: enumeration(REPORT_RECEIPT_OUTCOMES),
    prior_state: enumeration(REPORT_LIFECYCLE_STATES),
    lifecycle_state: enumeration(REPORT_LIFECYCLE_STATES),
    lifecycle_revision: count,
    event_id: nullable(reportLifecycleEventId),
    receipt: strictObject({
      receipt_id: reportReceiptId,
      operation: op,
      outcome: enumeration(REPORT_RECEIPT_OUTCOMES),
      expected_lifecycle_revision: count,
      issued_at: timestamp,
      correlation_id: correlationId,
      audit_id: auditId,
    }),
    replayed: boolean,
  });
}

const archive = lifecycleResult("archive");
const del = lifecycleResult("delete");
const restore = lifecycleResult("restore");

export type ReportsArchiveResult = Decoded<typeof archive>;
export type ReportsDeleteResult = Decoded<typeof del>;
export type ReportsRestoreResult = Decoded<typeof restore>;
/** Any of the three: what the UI renders as a lifecycle receipt. */
export type ReportLifecycleResult = ReportsArchiveResult | ReportsDeleteResult | ReportsRestoreResult;

export const archiveResult: Decoder<ReportsArchiveResult> = archive;
export const deleteResult: Decoder<ReportsDeleteResult> = del;
export const restoreResult: Decoder<ReportsRestoreResult> = restore;
