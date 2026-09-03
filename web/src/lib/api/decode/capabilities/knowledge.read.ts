import { optional, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import { fail, oneOf, pick, requiredBoolean, requiredInt, requiredString } from "./_read-helpers";

export const TRUST_LEVELS = ["source_original", "source_bound_derived", "model_proposed"] as const;

export type KnowledgeTrustLevel = (typeof TRUST_LEVELS)[number];

export interface KnowledgeProvenance {
  readonly source_id: string;
  readonly source_object_id: string;
  readonly version_id: string;
  readonly extractor: string;
  readonly extractor_version: string;
  readonly trust_level: KnowledgeTrustLevel;
  readonly observed_at: string;
  readonly processed_at: string;
}

export interface KnowledgeReadResult {
  readonly knowledge_id: string;
  readonly label: string;
  readonly media_type: string;
  readonly character_count: number;
  readonly metadata_only: boolean;
  readonly is_truncated: boolean;
  readonly provenance: KnowledgeProvenance;
  readonly text?: string;
}

function decodeProvenance(input: unknown): DecodeResult<KnowledgeProvenance> {
  const known = pick(input, [
    "source_id",
    "source_object_id",
    "version_id",
    "extractor",
    "extractor_version",
    "trust_level",
    "observed_at",
    "processed_at",
  ]);
  if (!known.ok) return known;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const sourceObjectId = requiredString(known.value.source_object_id);
  if (!sourceObjectId.ok) return sourceObjectId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  const extractor = requiredString(known.value.extractor);
  if (!extractor.ok) return extractor;
  const extractorVersion = requiredString(known.value.extractor_version);
  if (!extractorVersion.ok) return extractorVersion;
  const trust = oneOf(known.value.trust_level, TRUST_LEVELS);
  if (!trust.ok) return trust;
  const observedAt = requiredString(known.value.observed_at);
  if (!observedAt.ok) return observedAt;
  const processedAt = requiredString(known.value.processed_at);
  if (!processedAt.ok) return processedAt;
  return ok({
    source_id: sourceId.value,
    source_object_id: sourceObjectId.value,
    version_id: versionId.value,
    extractor: extractor.value,
    extractor_version: extractorVersion.value,
    trust_level: trust.value,
    observed_at: observedAt.value,
    processed_at: processedAt.value,
  });
}

export const decodeKnowledgeRead: Decoder<KnowledgeReadResult> = (input) => {
  const known = pick(input, [
    "knowledge_id",
    "label",
    "media_type",
    "character_count",
    "metadata_only",
    "is_truncated",
    "provenance",
    "text",
  ]);
  if (!known.ok) return known;
  const knowledgeId = requiredString(known.value.knowledge_id);
  if (!knowledgeId.ok) return knowledgeId;
  const label = requiredString(known.value.label);
  if (!label.ok) return label;
  const mediaType = requiredString(known.value.media_type);
  if (!mediaType.ok) return mediaType;
  const characterCount = requiredInt(known.value.character_count);
  if (!characterCount.ok) return characterCount;
  const metadataOnly = requiredBoolean(known.value.metadata_only);
  if (!metadataOnly.ok) return metadataOnly;
  const truncated = requiredBoolean(known.value.is_truncated);
  if (!truncated.ok) return truncated;
  if (known.value.provenance === undefined) return fail("a required field was missing");
  const provenance = decodeProvenance(known.value.provenance);
  if (!provenance.ok) return provenance;
  const text = optional(known.value.text, requiredString);
  if (!text.ok) return text;
  return ok({
    knowledge_id: knowledgeId.value,
    label: label.value,
    media_type: mediaType.value,
    character_count: characterCount.value,
    metadata_only: metadataOnly.value,
    is_truncated: truncated.value,
    provenance: provenance.value,
    ...(text.value !== undefined ? { text: text.value } : {}),
  });
};
