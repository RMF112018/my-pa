import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import { decodeLifecycleAliasView, type LifecycleAliasView } from "./_entity-read-helpers";

export type { LifecycleAliasView };

export interface EntitiesAliasesListResult {
  readonly entity_id: string;
  readonly aliases: readonly LifecycleAliasView[];
}

export const decodeEntitiesAliasesList: Decoder<EntitiesAliasesListResult> = (input) => {
  const known = pick(input, ["entity_id", "aliases"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.aliases === undefined) return fail("a required array was omitted");
  const aliases = decodeItems(known.value.aliases, decodeLifecycleAliasView);
  if (!aliases.ok) return aliases;
  return ok({ entity_id: entityId.value, aliases: aliases.value });
};
