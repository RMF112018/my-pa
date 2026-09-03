import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, oneOf, pick, requiredString } from "./_read-helpers";

export const KNOWLEDGE_RANKS = ["strong", "moderate", "weak"] as const;

export type KnowledgeRank = (typeof KNOWLEDGE_RANKS)[number];

export interface KnowledgeSearchMatch {
  readonly knowledge_id: string;
  readonly label: string;
  readonly snippet: string;
  readonly rank: KnowledgeRank;
  readonly source_id: string;
  readonly source_object_id: string;
  readonly version_id: string;
}

export interface KnowledgeSearchResult {
  readonly matches: readonly KnowledgeSearchMatch[];
}

const MATCH_KEYS = [
  "knowledge_id",
  "label",
  "snippet",
  "rank",
  "source_id",
  "source_object_id",
  "version_id",
] as const;

function decodeMatch(input: unknown): DecodeResult<KnowledgeSearchMatch> {
  const known = pick(input, MATCH_KEYS);
  if (!known.ok) return known;
  const knowledgeId = requiredString(known.value.knowledge_id);
  if (!knowledgeId.ok) return knowledgeId;
  const label = requiredString(known.value.label);
  if (!label.ok) return label;
  const snippet = requiredString(known.value.snippet);
  if (!snippet.ok) return snippet;
  const rank = oneOf(known.value.rank, KNOWLEDGE_RANKS);
  if (!rank.ok) return rank;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const sourceObjectId = requiredString(known.value.source_object_id);
  if (!sourceObjectId.ok) return sourceObjectId;
  const versionId = requiredString(known.value.version_id);
  if (!versionId.ok) return versionId;
  return ok({
    knowledge_id: knowledgeId.value,
    label: label.value,
    snippet: snippet.value,
    rank: rank.value,
    source_id: sourceId.value,
    source_object_id: sourceObjectId.value,
    version_id: versionId.value,
  });
}

export const decodeKnowledgeSearch: Decoder<KnowledgeSearchResult> = (input) => {
  const known = pick(input, ["matches"]);
  if (!known.ok) return known;
  if (known.value.matches === undefined) return fail("a required array was omitted");
  const matches = decodeItems(known.value.matches, decodeMatch);
  if (!matches.ok) return matches;
  return ok({ matches: matches.value });
};
