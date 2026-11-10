/** `reports.restore` (WP07 U2): the shared lifecycle answer, operation `restore`. */
import type { Decoder } from "../types";
import { restoreResult, type ReportsRestoreResult } from "./_general-report-lifecycle";

export type { ReportsRestoreResult } from "./_general-report-lifecycle";
export const decodeReportsRestore: Decoder<ReportsRestoreResult> = restoreResult;
