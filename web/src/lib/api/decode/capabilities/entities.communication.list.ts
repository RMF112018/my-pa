import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import {
  decodeCommunicationMethodView,
  type CommunicationMethodView,
} from "./_entity-read-helpers";

export type { CommunicationMethodView };

export interface EntitiesCommunicationListResult {
  readonly entity_id: string;
  readonly communication_methods: readonly CommunicationMethodView[];
}

export const decodeEntitiesCommunicationList: Decoder<EntitiesCommunicationListResult> = (
  input,
) => {
  const known = pick(input, ["entity_id", "communication_methods"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.communication_methods === undefined) {
    return fail("a required array was omitted");
  }
  const methods = decodeItems(known.value.communication_methods, decodeCommunicationMethodView);
  if (!methods.ok) return methods;
  return ok({ entity_id: entityId.value, communication_methods: methods.value });
};
