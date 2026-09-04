import { isRecord, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const INTELLIGENCE_STAGES = [
  "collector",
  "researcher",
  "synthesizer",
  "reporter",
  "morning_brief",
] as const;

export type IntelligenceStage = (typeof INTELLIGENCE_STAGES)[number];

export const ARTIFACT_KINDS = [
  "collector_candidates",
  "research_context",
  "synthesis_package",
  "focus_report",
  "morning_brief",
] as const;

export type ArtifactKind = (typeof ARTIFACT_KINDS)[number];

export const ARTIFACT_STATES = ["partial", "final", "superseded", "rejected"] as const;

export type ArtifactState = (typeof ARTIFACT_STATES)[number];

export const PROVENANCE_RELATIONS = [
  "supports",
  "contradicts",
  "context",
  "derived_from",
] as const;

export type ProvenanceRelation = (typeof PROVENANCE_RELATIONS)[number];

export interface ReportProvenanceRef {
  readonly source_system: string;
  readonly source_ref: string;
  readonly relation: ProvenanceRelation;
  readonly source_url: string | null;
}

export interface ReportsReadResult {
  readonly report_id: string;
  readonly report_run_id: string;
  readonly cycle_run_id: string;
  readonly focus_area_id: string | null;
  readonly stage: IntelligenceStage;
  readonly artifact_kind: ArtifactKind;
  readonly source_lane: string | null;
  readonly report_date: string;
  readonly title: string;
  readonly artifact_state: ArtifactState;
  readonly content_sha256: string;
  readonly content_bytes: number;
  readonly committed_at: string;
  readonly version: number;
  readonly supersedes_report_id: string | null;
  readonly dependency_report_ids: readonly string[];
  readonly provenance: readonly ReportProvenanceRef[];
  readonly body_markdown?: string;
  readonly structured_content?: Readonly<Record<string, unknown>>;
}

const PROVENANCE_KEYS = ["source_system", "source_ref", "relation", "source_url"] as const;

const READ_KEYS = [
  "report_id",
  "report_run_id",
  "cycle_run_id",
  "focus_area_id",
  "stage",
  "artifact_kind",
  "source_lane",
  "report_date",
  "title",
  "artifact_state",
  "content_sha256",
  "content_bytes",
  "committed_at",
  "version",
  "supersedes_report_id",
  "dependency_report_ids",
  "provenance",
  "body_markdown",
  "structured_content",
] as const;

function decodeProvenance(input: unknown): DecodeResult<ReportProvenanceRef> {
  const known = pick(input, PROVENANCE_KEYS);
  if (!known.ok) return known;
  const sourceSystem = requiredString(known.value.source_system);
  if (!sourceSystem.ok) return sourceSystem;
  const sourceRef = requiredString(known.value.source_ref);
  if (!sourceRef.ok) return sourceRef;
  const relation = oneOf(known.value.relation, PROVENANCE_RELATIONS);
  if (!relation.ok) return relation;
  const sourceUrl = requiredNullableString(known.value.source_url);
  if (!sourceUrl.ok) return sourceUrl;
  return ok({
    source_system: sourceSystem.value,
    source_ref: sourceRef.value,
    relation: relation.value,
    source_url: sourceUrl.value,
  });
}

export function decodeIntelligenceStage(value: unknown): DecodeResult<IntelligenceStage> {
  return oneOf(value, INTELLIGENCE_STAGES);
}

export function decodeArtifactKind(value: unknown): DecodeResult<ArtifactKind> {
  return oneOf(value, ARTIFACT_KINDS);
}

export function decodeArtifactState(value: unknown): DecodeResult<ArtifactState> {
  return oneOf(value, ARTIFACT_STATES);
}

export const decodeReportsRead: Decoder<ReportsReadResult> = (input) => {
  const known = pick(input, READ_KEYS);
  if (!known.ok) return known;
  const reportId = requiredString(known.value.report_id);
  if (!reportId.ok) return reportId;
  const reportRunId = requiredString(known.value.report_run_id);
  if (!reportRunId.ok) return reportRunId;
  const cycleRunId = requiredString(known.value.cycle_run_id);
  if (!cycleRunId.ok) return cycleRunId;
  const focusAreaId = requiredNullableString(known.value.focus_area_id);
  if (!focusAreaId.ok) return focusAreaId;
  const stage = decodeIntelligenceStage(known.value.stage);
  if (!stage.ok) return stage;
  const kind = decodeArtifactKind(known.value.artifact_kind);
  if (!kind.ok) return kind;
  const sourceLane = requiredNullableString(known.value.source_lane);
  if (!sourceLane.ok) return sourceLane;
  const reportDate = requiredString(known.value.report_date);
  if (!reportDate.ok) return reportDate;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const artifactState = decodeArtifactState(known.value.artifact_state);
  if (!artifactState.ok) return artifactState;
  const digest = requiredString(known.value.content_sha256);
  if (!digest.ok) return digest;
  const contentBytes = requiredInt(known.value.content_bytes);
  if (!contentBytes.ok) return contentBytes;
  const committedAt = requiredString(known.value.committed_at);
  if (!committedAt.ok) return committedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const supersedes = requiredNullableString(known.value.supersedes_report_id);
  if (!supersedes.ok) return supersedes;
  const dependencies = requiredStringArray(known.value.dependency_report_ids);
  if (!dependencies.ok) return dependencies;
  if (known.value.provenance === undefined) return fail("a required array was omitted");
  const provenance = decodeItems(known.value.provenance, decodeProvenance);
  if (!provenance.ok) return provenance;
  let bodyMarkdown: string | undefined;
  if (known.value.body_markdown !== undefined) {
    const body = requiredString(known.value.body_markdown);
    if (!body.ok) return body;
    bodyMarkdown = body.value;
  }
  let structuredContent: Readonly<Record<string, unknown>> | undefined;
  if (known.value.structured_content !== undefined) {
    if (!isRecord(known.value.structured_content)) {
      return fail("a required field was not the expected type");
    }
    structuredContent = known.value.structured_content;
  }
  return ok({
    report_id: reportId.value,
    report_run_id: reportRunId.value,
    cycle_run_id: cycleRunId.value,
    focus_area_id: focusAreaId.value,
    stage: stage.value,
    artifact_kind: kind.value,
    source_lane: sourceLane.value,
    report_date: reportDate.value,
    title: title.value,
    artifact_state: artifactState.value,
    content_sha256: digest.value,
    content_bytes: contentBytes.value,
    committed_at: committedAt.value,
    version: version.value,
    supersedes_report_id: supersedes.value,
    dependency_report_ids: dependencies.value,
    provenance: provenance.value,
    ...(bodyMarkdown !== undefined ? { body_markdown: bodyMarkdown } : {}),
    ...(structuredContent !== undefined ? { structured_content: structuredContent } : {}),
  });
};
