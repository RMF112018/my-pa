/** `reports.transfer.read_chunk` (WP07 U2): Python `ApplicationService._transfer_read_range` (WP06 T15), closed. */
import type { Decoder } from "../types";
import {
  boolean,
  digest,
  enumeration,
  integer,
  nullable,
  strictObject,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_TRANSFER_PARTS,
  STANDALONE_PLANE,
  base64Chunk,
  count,
  positiveCount,
  reportId,
  reportVersionId,
} from "./_general-report-helpers";

const result = strictObject({
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  version_id: reportVersionId,
  version_number: integer(1),
  part: enumeration(REPORT_TRANSFER_PARTS),
  offset: count,
  byte_count: positiveCount,
  chunk: base64Chunk,
  chunk_sha256: digest,
  total_byte_count: positiveCount,
  part_sha256: digest,
  eof: boolean,
  next_offset: nullable(positiveCount),
});

export type ReportsTransferReadChunkResult = Decoded<typeof result>;
export const decodeReportsTransferReadChunk: Decoder<ReportsTransferReadChunkResult> = result;
