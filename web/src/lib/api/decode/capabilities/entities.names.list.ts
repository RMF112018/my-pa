import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import { decodeEntityNameView, type EntityNameView } from "./_entity-read-helpers";

export type { EntityNameView };

export interface EntitiesNamesListResult {
  readonly entity_id: string;
  readonly names: readonly EntityNameView[];
}

export const decodeEntitiesNamesList: Decoder<EntitiesNamesListResult> = (input) => {
  const known = pick(input, ["entity_id", "names"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.names === undefined) return fail("a required array was omitted");
  const names = decodeItems(known.value.names, decodeEntityNameView);
  if (!names.ok) return names;
  return ok({ entity_id: entityId.value, names: names.value });
};
