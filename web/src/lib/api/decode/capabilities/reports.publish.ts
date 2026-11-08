/** `reports.publish` (WP07 U2): Python `service._general_publish_payload`, closed. */
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
  REPORT_CONTENT_FORMATS,
  REPORT_LIFECYCLE_STATES,
  STANDALONE_PLANE,
  count,
  reportContentId,
  reportId,
  reportReceiptId,
  reportVersionId,
} from "./_general-report-helpers";

const result = strictObject({
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  version_id: reportVersionId,
  version_number: integer(1),
  lifecycle_state: enumeration(REPORT_LIFECYCLE_STATES),
  lifecycle_revision: count,
  content: strictObject({
    content_id: reportContentId,
    format: enumeration(REPORT_CONTENT_FORMATS),
    decoded_sha256: digest,
    decoded_byte_count: count,
    canonical_sha256: nullable(digest),
  }),
  manifest_sha256: digest,
  receipt_id: reportReceiptId,
  recorded_at: timestamp,
  replayed: boolean,
});

export type ReportsPublishResult = Decoded<typeof result>;
export const decodeReportsPublish: Decoder<ReportsPublishResult> = result;
