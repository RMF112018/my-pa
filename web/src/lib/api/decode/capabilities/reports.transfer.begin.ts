/** `reports.transfer.begin` (WP07 U2): Python `service._transfer_begin_payload` (WP06 T18), closed. */
import type { Decoder } from "../types";
import {
  boolean,
  digest,
  enumeration,
  strictObject,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_CONTENT_ENCODINGS,
  REPORT_CONTENT_FORMATS,
  positiveCount,
  transferSessionId,
} from "./_general-report-helpers";

const result = strictObject({
  session_id: transferSessionId,
  state: enumeration(["open"] as const),
  format: enumeration(REPORT_CONTENT_FORMATS),
  encoding: enumeration(REPORT_CONTENT_ENCODINGS),
  declared_byte_count: positiveCount,
  declared_sha256: digest,
  chunk_byte_limit: positiveCount,
  chunk_count: positiveCount,
  expires_at: timestamp,
  replayed: boolean,
});

export type ReportsTransferBeginResult = Decoded<typeof result>;
export const decodeReportsTransferBegin: Decoder<ReportsTransferBeginResult> = result;
