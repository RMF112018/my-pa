import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import {
  decodeLifecycleIdentifierView,
  type LifecycleIdentifierView,
} from "./_entity-read-helpers";

export type { LifecycleIdentifierView };

export interface EntitiesIdentifiersListResult {
  readonly entity_id: string;
  readonly identifiers: readonly LifecycleIdentifierView[];
}

export const decodeEntitiesIdentifiersList: Decoder<EntitiesIdentifiersListResult> = (input) => {
  const known = pick(input, ["entity_id", "identifiers"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.identifiers === undefined) return fail("a required array was omitted");
  const identifiers = decodeItems(known.value.identifiers, decodeLifecycleIdentifierView);
  if (!identifiers.ok) return identifiers;
  return ok({ entity_id: entityId.value, identifiers: identifiers.value });
};
