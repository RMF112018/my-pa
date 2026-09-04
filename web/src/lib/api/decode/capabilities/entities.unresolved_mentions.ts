import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick } from "./_read-helpers";
import {
  decodeUnresolvedMentionView,
  type UnresolvedMentionView,
} from "./_entity-read-helpers";

export type { UnresolvedMentionView };

export interface EntitiesUnresolvedMentionsResult {
  readonly mentions: readonly UnresolvedMentionView[];
}

export const decodeEntitiesUnresolvedMentions: Decoder<EntitiesUnresolvedMentionsResult> = (
  input,
) => {
  const known = pick(input, ["mentions"]);
  if (!known.ok) return known;
  if (known.value.mentions === undefined) return fail("a required array was omitted");
  const mentions = decodeItems(known.value.mentions, decodeUnresolvedMentionView);
  if (!mentions.ok) return mentions;
  return ok({ mentions: mentions.value });
};
