/** `reports.transfer.append` (WP07 U2): Python `service._transfer_append_payload` (WP06 T8), closed. */
import type { Decoder } from "../types";
import {
  boolean,
  digest,
  nullable,
  strictObject,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import { count, positiveCount, transferSessionId } from "./_general-report-helpers";

const result = strictObject({
  session_id: transferSessionId,
  sequence: count,
  byte_offset: count,
  byte_count: positiveCount,
  chunk_sha256: digest,
  received_byte_count: positiveCount,
  declared_byte_count: positiveCount,
  complete: boolean,
  next_sequence: nullable(count),
  expires_at: timestamp,
  replayed: boolean,
});

export type ReportsTransferAppendResult = Decoded<typeof result>;
export const decodeReportsTransferAppend: Decoder<ReportsTransferAppendResult> = result;
