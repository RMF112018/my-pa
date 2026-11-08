/**
 * The standalone-plane decoder path (WP07 contract Amendment A1).
 *
 * `reports.read` of a `grpt_` report and `reports.list` / `reports.search`
 * with an explicit `plane` answer shapes the legacy `DECODERS` entries never
 * accept. Those entries stay the pipeline shapes byte for byte, so every
 * existing consumer (Intelligence included) keeps its base behaviour; only the
 * /api/reports routes reach these, through `invokeStandaloneReports`.
 */
import type { Decoder } from "./types";
import {
  decodeStandaloneReportList,
  decodeStandaloneReportRead,
  decodeStandaloneReportSearch,
  type StandaloneReportListResult,
  type StandaloneReportReadResult,
  type StandaloneReportSearchResult,
} from "./capabilities/reports.standalone";

export type StandaloneReportResults = {
  readonly "reports.read": StandaloneReportReadResult;
  readonly "reports.list": StandaloneReportListResult;
  readonly "reports.search": StandaloneReportSearchResult;
};

export type StandaloneReportCapability = keyof StandaloneReportResults;

export const STANDALONE_REPORT_DECODERS = {
  "reports.read": decodeStandaloneReportRead,
  "reports.list": decodeStandaloneReportList,
  "reports.search": decodeStandaloneReportSearch,
} as const satisfies { [K in StandaloneReportCapability]: Decoder<StandaloneReportResults[K]> };

export function decodeStandaloneReport<C extends StandaloneReportCapability>(
  capability: C,
  input: unknown,
): import("./primitives").DecodeResult<StandaloneReportResults[C]> {
  return (STANDALONE_REPORT_DECODERS[capability] as Decoder<StandaloneReportResults[C]>)(input);
}
