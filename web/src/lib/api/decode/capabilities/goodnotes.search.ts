import { ok, optional } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export interface GoodNotesSearchHit {
  readonly kind: string;
  readonly id: string;
  readonly title: string;
  readonly snippet: string;
  readonly notebook_id: string | null;
  readonly logical_page_id: string | null;
  readonly page_version_id: string | null;
  readonly run_id: string | null;
  readonly freshness: string;
}

export interface GoodNotesSearchResult {
  readonly hits: readonly GoodNotesSearchHit[];
  readonly next_cursor?: string;
}

const HIT_KEYS = [
  "kind",
  "id",
  "title",
  "snippet",
  "notebook_id",
  "logical_page_id",
  "page_version_id",
  "run_id",
  "freshness",
] as const;

function decodeHit(input: unknown) {
  const known = pick(input, HIT_KEYS);
  if (!known.ok) return known;
  const kind = requiredString(known.value.kind);
  if (!kind.ok) return kind;
  const id = requiredString(known.value.id);
  if (!id.ok) return id;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const snippet = requiredString(known.value.snippet);
  if (!snippet.ok) return snippet;
  const notebookId = requiredNullableString(known.value.notebook_id);
  if (!notebookId.ok) return notebookId;
  const logicalPageId = requiredNullableString(known.value.logical_page_id);
  if (!logicalPageId.ok) return logicalPageId;
  const pageVersionId = requiredNullableString(known.value.page_version_id);
  if (!pageVersionId.ok) return pageVersionId;
  const runId = requiredNullableString(known.value.run_id);
  if (!runId.ok) return runId;
  const freshness = requiredString(known.value.freshness);
  if (!freshness.ok) return freshness;
  return ok({
    kind: kind.value,
    id: id.value,
    title: title.value,
    snippet: snippet.value,
    notebook_id: notebookId.value,
    logical_page_id: logicalPageId.value,
    page_version_id: pageVersionId.value,
    run_id: runId.value,
    freshness: freshness.value,
  });
}

export const decodeGoodNotesSearch: Decoder<GoodNotesSearchResult> = (input) => {
  const known = pick(input, ["hits", "next_cursor"]);
  if (!known.ok) return known;
  if (known.value.hits === undefined) return fail("a required array was omitted");
  const hits = decodeItems(known.value.hits, decodeHit);
  if (!hits.ok) return hits;
  const cursor = optional(known.value.next_cursor, requiredString);
  if (!cursor.ok) return cursor;
  return ok({
    hits: hits.value,
    ...(cursor.value !== undefined ? { next_cursor: cursor.value } : {}),
  });
};
