import { ok } from "../primitives";
import type { Decoder } from "../types";
import { pick, requiredNullableString, requiredString } from "./_read-helpers";
import {
  decodeArtifactKind,
  decodeArtifactState,
  decodeIntelligenceStage,
  type ArtifactKind,
  type ArtifactState,
  type IntelligenceStage,
} from "./reports.read";

export interface ReportsLatestResult {
  readonly report_id: string;
  readonly cycle_run_id: string;
  readonly stage: IntelligenceStage;
  readonly artifact_kind: ArtifactKind;
  readonly focus_area_id: string | null;
  readonly source_lane: string | null;
  readonly content_sha256: string;
  readonly artifact_state: ArtifactState;
}

const LATEST_KEYS = [
  "report_id",
  "cycle_run_id",
  "stage",
  "artifact_kind",
  "focus_area_id",
  "source_lane",
  "content_sha256",
  "artifact_state",
] as const;

export const decodeReportsLatest: Decoder<ReportsLatestResult> = (input) => {
  const known = pick(input, LATEST_KEYS);
  if (!known.ok) return known;
  const reportId = requiredString(known.value.report_id);
  if (!reportId.ok) return reportId;
  const cycleRunId = requiredString(known.value.cycle_run_id);
  if (!cycleRunId.ok) return cycleRunId;
  const stage = decodeIntelligenceStage(known.value.stage);
  if (!stage.ok) return stage;
  const kind = decodeArtifactKind(known.value.artifact_kind);
  if (!kind.ok) return kind;
  const focusAreaId = requiredNullableString(known.value.focus_area_id);
  if (!focusAreaId.ok) return focusAreaId;
  const sourceLane = requiredNullableString(known.value.source_lane);
  if (!sourceLane.ok) return sourceLane;
  const digest = requiredString(known.value.content_sha256);
  if (!digest.ok) return digest;
  const artifactState = decodeArtifactState(known.value.artifact_state);
  if (!artifactState.ok) return artifactState;
  return ok({
    report_id: reportId.value,
    cycle_run_id: cycleRunId.value,
    stage: stage.value,
    artifact_kind: kind.value,
    focus_area_id: focusAreaId.value,
    source_lane: sourceLane.value,
    content_sha256: digest.value,
    artifact_state: artifactState.value,
  });
};
