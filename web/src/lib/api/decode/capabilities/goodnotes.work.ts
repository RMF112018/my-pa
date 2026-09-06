import { ok } from "../primitives";
import type { Decoder } from "../types";
import { pick, requiredNullableString, requiredString } from "./_read-helpers";
import { requiredSha256 } from "./_mutation-helpers";

export interface GoodNotesWorkResult {
  readonly run_id: string;
  readonly page_version_id: string;
  readonly content_sha256: string;
  readonly logical_page_id: string | null;
  readonly renderer_name: string | null;
  readonly renderer_version: string | null;
  readonly render_profile_version: string | null;
}

const KEYS = [
  "run_id",
  "page_version_id",
  "content_sha256",
  "logical_page_id",
  "renderer_name",
  "renderer_version",
  "render_profile_version",
] as const;

export const decodeGoodNotesWork: Decoder<GoodNotesWorkResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const runId = requiredString(known.value.run_id);
  if (!runId.ok) return runId;
  const pageVersionId = requiredString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const logicalPageId = requiredNullableString(known.value.logical_page_id);
  if (!logicalPageId.ok) return logicalPageId;
  const rendererName = requiredNullableString(known.value.renderer_name);
  if (!rendererName.ok) return rendererName;
  const rendererVersion = requiredNullableString(known.value.renderer_version);
  if (!rendererVersion.ok) return rendererVersion;
  const renderProfileVersion = requiredNullableString(known.value.render_profile_version);
  if (!renderProfileVersion.ok) return renderProfileVersion;
  return ok({
    run_id: runId.value,
    page_version_id: pageVersionId.value,
    content_sha256: digest.value,
    logical_page_id: logicalPageId.value,
    renderer_name: rendererName.value,
    renderer_version: rendererVersion.value,
    render_profile_version: renderProfileVersion.value,
  });
};
