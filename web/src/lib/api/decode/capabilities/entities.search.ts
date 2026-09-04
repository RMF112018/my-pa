import type { Decoder } from "../types";
import {
  decodeEntitySearchResult,
  type EntitySearchResult,
} from "./_entity-read-helpers";

export type { EntitySearchResult, EntitySummary } from "./_entity-read-helpers";

export const decodeEntitiesSearch: Decoder<EntitySearchResult> = decodeEntitySearchResult;
