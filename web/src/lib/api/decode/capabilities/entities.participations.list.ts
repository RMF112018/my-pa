import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, oneOf, pick, requiredString } from "./_read-helpers";
import {
  decodeParticipationView,
  PARTICIPATION_PERSPECTIVES,
  type ParticipationView,
} from "./_entity-read-helpers";

export type { ParticipationView };

export interface EntitiesParticipationsListResult {
  readonly entity_id: string;
  readonly perspective: (typeof PARTICIPATION_PERSPECTIVES)[number];
  readonly participations: readonly ParticipationView[];
}

export const decodeEntitiesParticipationsList: Decoder<EntitiesParticipationsListResult> = (
  input,
) => {
  const known = pick(input, ["entity_id", "perspective", "participations"]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const perspective = oneOf(known.value.perspective, PARTICIPATION_PERSPECTIVES);
  if (!perspective.ok) return perspective;
  if (known.value.participations === undefined) return fail("a required array was omitted");
  const participations = decodeItems(known.value.participations, decodeParticipationView);
  if (!participations.ok) return participations;
  return ok({
    entity_id: entityId.value,
    perspective: perspective.value,
    participations: participations.value,
  });
};
