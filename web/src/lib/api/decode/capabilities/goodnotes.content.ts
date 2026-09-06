import { isString, ok } from "../primitives";
import type { Decoder } from "../types";
import { fail, pick, requiredInt, requiredString } from "./_read-helpers";
import { requiredSha256 } from "./_mutation-helpers";

export const GOODNOTES_CONTENT_MEDIA_TYPE = "image/png";

export interface GoodNotesContentResult {
  readonly run_id: string;
  readonly page_version_id: string;
  readonly content_sha256: string;
  readonly exact_render_sha256: string;
  readonly media_type: typeof GOODNOTES_CONTENT_MEDIA_TYPE;
  readonly byte_length: number;
  readonly digest: string;
  readonly content_base64: string;
  readonly renderer_name: string;
  readonly renderer_version: string;
  readonly render_profile_version: string;
}

const KEYS = [
  "run_id",
  "page_version_id",
  "content_sha256",
  "exact_render_sha256",
  "media_type",
  "byte_length",
  "digest",
  "content_base64",
  "renderer_name",
  "renderer_version",
  "render_profile_version",
] as const;

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

function requiredBase64(value: unknown) {
  if (value === undefined) return fail("a required field was missing");
  if (!isString(value) || value.length === 0 || value.length % 4 !== 0 || !BASE64.test(value)) {
    return fail("a required field was not the expected type");
  }
  return ok(value);
}

export const decodeGoodNotesContent: Decoder<GoodNotesContentResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const runId = requiredString(known.value.run_id);
  if (!runId.ok) return runId;
  const pageVersionId = requiredString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const exactRender = requiredSha256(known.value.exact_render_sha256);
  if (!exactRender.ok) return exactRender;
  const mediaType = requiredString(known.value.media_type);
  if (!mediaType.ok) return mediaType;
  if (mediaType.value !== GOODNOTES_CONTENT_MEDIA_TYPE) {
    return fail("a required field was not an allowed value");
  }
  const byteLength = requiredInt(known.value.byte_length);
  if (!byteLength.ok) return byteLength;
  if (byteLength.value <= 0) return fail("a required integer was out of range");
  const pngDigest = requiredSha256(known.value.digest);
  if (!pngDigest.ok) return pngDigest;
  const content = requiredBase64(known.value.content_base64);
  if (!content.ok) return content;
  const rendererName = requiredString(known.value.renderer_name);
  if (!rendererName.ok) return rendererName;
  const rendererVersion = requiredString(known.value.renderer_version);
  if (!rendererVersion.ok) return rendererVersion;
  const renderProfileVersion = requiredString(known.value.render_profile_version);
  if (!renderProfileVersion.ok) return renderProfileVersion;
  return ok({
    run_id: runId.value,
    page_version_id: pageVersionId.value,
    content_sha256: digest.value,
    exact_render_sha256: exactRender.value,
    media_type: GOODNOTES_CONTENT_MEDIA_TYPE,
    byte_length: byteLength.value,
    digest: pngDigest.value,
    content_base64: content.value,
    renderer_name: rendererName.value,
    renderer_version: rendererVersion.value,
    render_profile_version: renderProfileVersion.value,
  });
};
