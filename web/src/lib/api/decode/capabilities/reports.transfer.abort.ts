/** `reports.transfer.abort` (WP07 U2): the `_reports_transfer_abort` handler answer (WP06 T17), closed. */
import type { Decoder } from "../types";
import { boolean, enumeration, strictObject, type Decoded } from "./continuity.projects.create";
import { transferSessionId } from "./_general-report-helpers";

const result = strictObject({
  session_id: transferSessionId,
  state: enumeration(["aborted"] as const),
  replayed: boolean,
});

export type ReportsTransferAbortResult = Decoded<typeof result>;
export const decodeReportsTransferAbort: Decoder<ReportsTransferAbortResult> = result;
