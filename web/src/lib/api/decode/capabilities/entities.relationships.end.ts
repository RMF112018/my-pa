import type { Decoder } from "../types";
import {
  decodeDirectedRelationshipWrite,
  type DirectedRelationshipWriteResult,
} from "./entities.relationships.write";

export type EntitiesRelationshipsEndResult = DirectedRelationshipWriteResult;

export const decodeEntitiesRelationshipsEnd: Decoder<EntitiesRelationshipsEndResult> =
  decodeDirectedRelationshipWrite;
