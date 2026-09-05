import type { Decoder } from "../types";
import {
  decodeDirectedRelationshipWrite,
  type DirectedRelationshipWriteResult,
} from "./entities.relationships.write";

export type EntitiesRelationshipsCreateResult = DirectedRelationshipWriteResult;

export const decodeEntitiesRelationshipsCreate: Decoder<EntitiesRelationshipsCreateResult> =
  decodeDirectedRelationshipWrite;
