/** `reports.delete` (WP07 U2): the shared lifecycle answer, operation `delete` (to Trash). */
import type { Decoder } from "../types";
import { deleteResult, type ReportsDeleteResult } from "./_general-report-lifecycle";

export type { ReportsDeleteResult } from "./_general-report-lifecycle";
export const decodeReportsDelete: Decoder<ReportsDeleteResult> = deleteResult;
