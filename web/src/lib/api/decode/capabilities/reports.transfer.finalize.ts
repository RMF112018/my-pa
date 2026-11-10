/**
 * `reports.transfer.finalize` (WP07 U2): Python `service._transfer_finalize_payload`
 * (WP06 T9), closed. `content_token` is an opaque one-use string matching
 * `^grxtk_[0-9a-f]{64}$`; it is decoded only and never logged, echoed or stored.
 */
import type { Decoder } from "../types";
import {
  digest,
  enumeration,
  strictObject,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_CONTENT_ENCODINGS,
  REPORT_CONTENT_FORMATS,
  contentToken,
  count,
  positiveCount,
  transferSessionId,
} from "./_general-report-helpers";

const result = strictObject({
  session_id: transferSessionId,
  state: enumeration(["finalized"] as const),
  content_token: contentToken,
  expires_at: timestamp,
  byte_count: positiveCount,
  sha256: digest,
  format: enumeration(REPORT_CONTENT_FORMATS),
  encoding: enumeration(REPORT_CONTENT_ENCODINGS),
  decoded_byte_count: count,
  decoded_sha256: digest,
});

export type ReportsTransferFinalizeResult = Decoded<typeof result>;
export const decodeReportsTransferFinalize: Decoder<ReportsTransferFinalizeResult> = result;
