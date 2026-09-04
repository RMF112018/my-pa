import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import {
  decodeArtifactKind,
  decodeIntelligenceStage,
  type ArtifactKind,
  type IntelligenceStage,
} from "./reports.read";

export interface ReportSearchMatch {
  readonly report_id: string;
  readonly title: string;
  readonly snippet: string;
  readonly cycle_run_id: string;
  readonly stage: IntelligenceStage;
  readonly artifact_kind: ArtifactKind;
}

export interface ReportsSearchResult {
  readonly items: readonly ReportSearchMatch[];
}

const MATCH_KEYS = [
  "report_id",
  "title",
  "snippet",
  "cycle_run_id",
  "stage",
  "artifact_kind",
] as const;

function decodeMatch(input: unknown): DecodeResult<ReportSearchMatch> {
  const known = pick(input, MATCH_KEYS);
  if (!known.ok) return known;
  const reportId = requiredString(known.value.report_id);
  if (!reportId.ok) return reportId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const snippet = requiredString(known.value.snippet);
  if (!snippet.ok) return snippet;
  const cycleRunId = requiredString(known.value.cycle_run_id);
  if (!cycleRunId.ok) return cycleRunId;
  const stage = decodeIntelligenceStage(known.value.stage);
  if (!stage.ok) return stage;
  const kind = decodeArtifactKind(known.value.artifact_kind);
  if (!kind.ok) return kind;
  return ok({
    report_id: reportId.value,
    title: title.value,
    snippet: snippet.value,
    cycle_run_id: cycleRunId.value,
    stage: stage.value,
    artifact_kind: kind.value,
  });
}

export const decodeReportsSearch: Decoder<ReportsSearchResult> = (input) => {
  const known = pick(input, ["items"]);
  if (!known.ok) return known;
  if (known.value.items === undefined) return fail("a required array was omitted");
  const items = decodeItems(known.value.items, decodeMatch);
  if (!items.ok) return items;
  return ok({ items: items.value });
};
