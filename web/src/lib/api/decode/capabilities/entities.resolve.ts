import type { Decoder } from "../types";
import { decodeEntityResolveResult, type EntityResolveResult } from "./_entity-read-helpers";

export type { EntityResolveResult, EntityResolutionView, ResolutionOutcome } from "./_entity-read-helpers";

export const decodeEntitiesResolve: Decoder<EntityResolveResult> = decodeEntityResolveResult;
