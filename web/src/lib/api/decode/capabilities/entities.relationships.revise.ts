import type { Decoder } from "../types";
import {
  decodeDirectedRelationshipWrite,
  type DirectedRelationshipWriteResult,
} from "./entities.relationships.write";

export type EntitiesRelationshipsReviseResult = DirectedRelationshipWriteResult;

export const decodeEntitiesRelationshipsRevise: Decoder<EntitiesRelationshipsReviseResult> =
  decodeDirectedRelationshipWrite;
