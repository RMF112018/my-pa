import { ok, optional } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredString,
} from "./_read-helpers";

export const GOODNOTES_LIVENESS = ["unknown"] as const;

export type GoodNotesLiveness = (typeof GOODNOTES_LIVENESS)[number];

export interface GoodNotesNotebook {
  readonly notebook_id: string;
  readonly title: string;
  readonly updated_at: string;
  readonly page_count: number;
  readonly liveness: GoodNotesLiveness;
}

export interface GoodNotesNotebooksListResult {
  readonly notebooks: readonly GoodNotesNotebook[];
  readonly next_cursor?: string;
}

const NOTEBOOK_KEYS = ["notebook_id", "title", "updated_at", "page_count", "liveness"] as const;

function decodeNotebook(input: unknown) {
  const known = pick(input, NOTEBOOK_KEYS);
  if (!known.ok) return known;
  const notebookId = requiredString(known.value.notebook_id);
  if (!notebookId.ok) return notebookId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const pageCount = requiredInt(known.value.page_count);
  if (!pageCount.ok) return pageCount;
  if (pageCount.value < 0) return fail("a required integer was out of range");
  const liveness = oneOf(known.value.liveness, GOODNOTES_LIVENESS);
  if (!liveness.ok) return liveness;
  return ok({
    notebook_id: notebookId.value,
    title: title.value,
    updated_at: updatedAt.value,
    page_count: pageCount.value,
    liveness: liveness.value,
  });
}

export const decodeGoodNotesNotebooksList: Decoder<GoodNotesNotebooksListResult> = (input) => {
  const known = pick(input, ["notebooks", "next_cursor"]);
  if (!known.ok) return known;
  if (known.value.notebooks === undefined) return fail("a required array was omitted");
  const notebooks = decodeItems(known.value.notebooks, decodeNotebook);
  if (!notebooks.ok) return notebooks;
  const cursor = optional(known.value.next_cursor, requiredString);
  if (!cursor.ok) return cursor;
  return ok({
    notebooks: notebooks.value,
    ...(cursor.value !== undefined ? { next_cursor: cursor.value } : {}),
  });
};
