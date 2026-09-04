import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick } from "./_read-helpers";
import {
  decodeRelationshipView,
  type RelationshipView,
} from "./_entity-read-helpers";

export type { RelationshipView };

export interface EntitiesRelationshipsResult {
  readonly relationships: readonly RelationshipView[];
}

export const decodeEntitiesRelationships: Decoder<EntitiesRelationshipsResult> = (input) => {
  const known = pick(input, ["relationships"]);
  if (!known.ok) return known;
  if (known.value.relationships === undefined) return fail("a required array was omitted");
  const relationships = decodeItems(known.value.relationships, decodeRelationshipView);
  if (!relationships.ok) return relationships;
  return ok({ relationships: relationships.value });
};
