/** `reports.archive` (WP07 U2): the shared lifecycle answer, operation `archive`. */
import type { Decoder } from "../types";
import { archiveResult, type ReportsArchiveResult } from "./_general-report-lifecycle";

export type { ReportsArchiveResult } from "./_general-report-lifecycle";
export const decodeReportsArchive: Decoder<ReportsArchiveResult> = archiveResult;
