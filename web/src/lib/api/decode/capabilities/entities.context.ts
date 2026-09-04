import type { Decoder } from "../types";
import { decodeEntityContextResult, type EntityContextResult } from "./_entity-read-helpers";

export type { EntityContextResult, EntityContextCard } from "./_entity-read-helpers";

export const decodeEntitiesContext: Decoder<EntityContextResult> = decodeEntityContextResult;
