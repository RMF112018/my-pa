import { ok, optional } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredBoolean,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";
import { requiredSha256 } from "./_mutation-helpers";

export interface GoodNotesPage {
  readonly logical_page_id: string;
  readonly page_version_id: string;
  readonly run_id: string | null;
  readonly content_sha256: string;
  readonly is_latest: boolean;
  readonly updated_at: string;
}

export interface GoodNotesPagesListResult {
  readonly pages: readonly GoodNotesPage[];
  readonly next_cursor?: string;
}

const PAGE_KEYS = [
  "logical_page_id",
  "page_version_id",
  "run_id",
  "content_sha256",
  "is_latest",
  "updated_at",
] as const;

function decodePage(input: unknown) {
  const known = pick(input, PAGE_KEYS);
  if (!known.ok) return known;
  const logicalPageId = requiredString(known.value.logical_page_id);
  if (!logicalPageId.ok) return logicalPageId;
  const pageVersionId = requiredString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const runId = requiredNullableString(known.value.run_id);
  if (!runId.ok) return runId;
  const digest = requiredSha256(known.value.content_sha256);
  if (!digest.ok) return digest;
  const isLatest = requiredBoolean(known.value.is_latest);
  if (!isLatest.ok) return isLatest;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  return ok({
    logical_page_id: logicalPageId.value,
    page_version_id: pageVersionId.value,
    run_id: runId.value,
    content_sha256: digest.value,
    is_latest: isLatest.value,
    updated_at: updatedAt.value,
  });
}

export const decodeGoodNotesPagesList: Decoder<GoodNotesPagesListResult> = (input) => {
  const known = pick(input, ["pages", "next_cursor"]);
  if (!known.ok) return known;
  if (known.value.pages === undefined) return fail("a required array was omitted");
  const pages = decodeItems(known.value.pages, decodePage);
  if (!pages.ok) return pages;
  const cursor = optional(known.value.next_cursor, requiredString);
  if (!cursor.ok) return cursor;
  return ok({
    pages: pages.value,
    ...(cursor.value !== undefined ? { next_cursor: cursor.value } : {}),
  });
};
