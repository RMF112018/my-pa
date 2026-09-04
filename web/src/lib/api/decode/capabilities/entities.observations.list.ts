import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick } from "./_read-helpers";
import {
  decodeRecordedObservationView,
  type RecordedObservationView,
} from "./_entity-read-helpers";

export type { RecordedObservationView };

export interface EntitiesObservationsListResult {
  readonly observations: readonly RecordedObservationView[];
}

export const decodeEntitiesObservationsList: Decoder<EntitiesObservationsListResult> = (input) => {
  const known = pick(input, ["observations"]);
  if (!known.ok) return known;
  if (known.value.observations === undefined) return fail("a required array was omitted");
  const observations = decodeItems(known.value.observations, decodeRecordedObservationView);
  if (!observations.ok) return observations;
  return ok({ observations: observations.value });
};
