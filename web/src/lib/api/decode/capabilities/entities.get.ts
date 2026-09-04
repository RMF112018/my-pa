import type { Decoder } from "../types";
import { decodeEntityGetResult, type EntityGetResult } from "./_entity-read-helpers";

export type { EntityGetResult, EntityView } from "./_entity-read-helpers";

export const decodeEntitiesGet: Decoder<EntityGetResult> = decodeEntityGetResult;
