import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";
import { decodeEntityAddressView, type EntityAddressView } from "./_entity-read-helpers";

export type { EntityAddressView };

export interface EntitiesAddressesListResult {
  readonly entity_id: string;
  readonly addresses: readonly EntityAddressView[];
}

export const decodeEntitiesAddressesList: Decoder<EntitiesAddressesListResult> = (input) => {
  const known = pick(input, ["entity_id", "addresses"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.addresses === undefined) return fail("a required array was omitted");
  const addresses = decodeItems(known.value.addresses, decodeEntityAddressView);
  if (!addresses.ok) return addresses;
  return ok({ entity_id: entityId.value, addresses: addresses.value });
};
