import type { Decoder } from "../types";
import { decodeEntityProfileResult, type EntityProfileResult } from "./_entity-read-helpers";

export type { EntityProfileResult, EntityProfileView } from "./_entity-read-helpers";

export const decodeEntitiesProfile: Decoder<EntityProfileResult> = decodeEntityProfileResult;
