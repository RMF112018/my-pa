import { isString, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, oneOf, pick, requiredNullableString, requiredString } from "./_read-helpers";
import { requiredSha256 } from "./_mutation-helpers";

export const GOODNOTES_AUTHORITIES = [
  "source",
  "interpretation",
  "user_confirmed",
  "pending_review",
  "rejected",
  "processing",
  "unavailable",
] as const;

export type GoodNotesAuthority = (typeof GOODNOTES_AUTHORITIES)[number];

const ITEM_KEYS = [
  "proposal_id",
  "review_case_id",
  "occurrence_id",
  "revision_id",
  "analyzer_name",
  "analyzer_version",
  "schema_version",
  "disposition",
  "transcription",
] as const;

export interface GoodNotesInterpretationItem {
  readonly proposal_id?: string | null;
  readonly review_case_id?: string | null;
  readonly occurrence_id?: string | null;
  readonly revision_id?: string | null;
  readonly analyzer_name?: string | null;
  readonly analyzer_version?: string | null;
  readonly schema_version?: string | null;
  readonly disposition?: string | null;
  readonly transcription?: string | null;
}

export interface GoodNotesInterpretation {
  readonly authority: GoodNotesAuthority;
  readonly items: readonly GoodNotesInterpretationItem[];
}

export interface GoodNotesReadProvenance {
  readonly run_id: string;
  readonly page_version_id: string;
  readonly content_sha256: string;
}

export interface GoodNotesReadProcessing {
  readonly run_status: string | null;
  readonly failure_class: string | null;
}

export interface GoodNotesReadResult {
  readonly run_id: string;
  readonly page_version_id: string;
  readonly content_sha256: string;
  readonly exact_render_sha256: string;
  readonly raster_digest: string;
  readonly media_type: string;
  readonly renderer_name: string;
  readonly renderer_version: string;
  readonly render_profile_version: string;
  readonly interpretation: GoodNotesInterpretation;
  readonly provenance: GoodNotesReadProvenance;
  readonly processing: GoodNotesReadProcessing;
}

function optionalNullableString(value: unknown): DecodeResult<string | null | undefined> {
  if (value === undefined) return ok(undefined);
  if (value === null) return ok(null);
  if (!isString(value)) return fail("a required field was not the expected type");
  return ok(value);
}

function decodeItem(input: unknown): DecodeResult<GoodNotesInterpretationItem> {
  const known = pick(input, ITEM_KEYS);
  if (!known.ok) return known;
  const item: {
    -readonly [K in keyof GoodNotesInterpretationItem]?: string | null;
  } = {};
  for (const key of ITEM_KEYS) {
    const decoded = optionalNullableString(known.value[key]);
    if (!decoded.ok) return decoded;
    if (decoded.value !== undefined) item[key] = decoded.value;
  }
  return ok(item);
}

function decodeInterpretation(input: unknown): DecodeResult<GoodNotesInterpretation> {
  const known = pick(input, ["authority", "items"]);
  if (!known.ok) return known;
  const authority = oneOf(known.value.authority, GOODNOTES_AUTHORITIES);
  if (!authority.ok) return authority;
  if (known.value.items === undefined) return fail("a required array was omitted");
  const items = decodeItems(known.value.items, decodeItem);
  if (!items.ok) return items;
  return ok({ authority: authority.value, items: items.value });
}

function decodeProvenance(input: unknown): DecodeResult<GoodNotesReadProvenance> {
  const known = pick(input, ["run_id", "page_version_id", "content_sha256"]);
  if (!known.ok) return known;
  const runId = requiredString(known.value.run_id);
  if (!runId.ok) return runId;
  const pageVersionId = requiredString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  return ok({
    run_id: runId.value,
    page_version_id: pageVersionId.value,
    content_sha256: digest.value,
  });
}

function decodeProcessing(input: unknown): DecodeResult<GoodNotesReadProcessing> {
  const known = pick(input, ["run_status", "failure_class"]);
  if (!known.ok) return known;
  const runStatus = requiredNullableString(known.value.run_status);
  if (!runStatus.ok) return runStatus;
  const failureClass = requiredNullableString(known.value.failure_class);
  if (!failureClass.ok) return failureClass;
  return ok({ run_status: runStatus.value, failure_class: failureClass.value });
}

export const decodeGoodNotesRead: Decoder<GoodNotesReadResult> = (input) => {
  const known = pick(input, [
    "run_id",
    "page_version_id",
    "content_sha256",
    "exact_render_sha256",
    "raster_digest",
    "media_type",
    "renderer_name",
    "renderer_version",
    "render_profile_version",
    "interpretation",
    "provenance",
    "processing",
  ]);
  if (!known.ok) return known;
  const runId = requiredString(known.value.run_id);
  if (!runId.ok) return runId;
  const pageVersionId = requiredString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const exactRender = requiredSha256(known.value.exact_render_sha256);
  if (!exactRender.ok) return exactRender;
  const rasterDigest = requiredSha256(known.value.raster_digest);
  if (!rasterDigest.ok) return rasterDigest;
  const mediaType = requiredString(known.value.media_type);
  if (!mediaType.ok) return mediaType;
  const rendererName = requiredString(known.value.renderer_name);
  if (!rendererName.ok) return rendererName;
  const rendererVersion = requiredString(known.value.renderer_version);
  if (!rendererVersion.ok) return rendererVersion;
  const renderProfileVersion = requiredString(known.value.render_profile_version);
  if (!renderProfileVersion.ok) return renderProfileVersion;
  const interpretation = decodeInterpretation(known.value.interpretation);
  if (!interpretation.ok) return interpretation;
  const provenance = decodeProvenance(known.value.provenance);
  if (!provenance.ok) return provenance;
  const processing = decodeProcessing(known.value.processing);
  if (!processing.ok) return processing;
  return ok({
    run_id: runId.value,
    page_version_id: pageVersionId.value,
    content_sha256: digest.value,
    exact_render_sha256: exactRender.value,
    raster_digest: rasterDigest.value,
    media_type: mediaType.value,
    renderer_name: rendererName.value,
    renderer_version: rendererVersion.value,
    render_profile_version: renderProfileVersion.value,
    interpretation: interpretation.value,
    provenance: provenance.value,
    processing: processing.value,
  });
};
