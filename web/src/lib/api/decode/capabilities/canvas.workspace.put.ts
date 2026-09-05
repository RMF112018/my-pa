import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCanvasPositions,
  type CanvasPositions,
} from "./canvas.workspace.get";
import { pick, requiredInt, requiredNullableString, requiredString } from "./_read-helpers";

export interface CanvasWorkspacePutResult {
  readonly focus_entity_id: string | null;
  readonly scope_entity_id: string | null;
  readonly version: number;
  readonly positions: CanvasPositions;
  readonly updated_at: string;
}

export const decodeCanvasWorkspacePut: Decoder<CanvasWorkspacePutResult> = (input) => {
  const known = pick(input, [
    "focus_entity_id",
    "scope_entity_id",
    "version",
    "positions",
    "updated_at",
  ]);
  if (!known.ok) return known;
  const focus = requiredNullableString(known.value.focus_entity_id);
  if (!focus.ok) return focus;
  const scope = requiredNullableString(known.value.scope_entity_id);
  if (!scope.ok) return scope;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const positions = decodeCanvasPositions(known.value.positions);
  if (!positions.ok) return positions;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  return ok({
    focus_entity_id: focus.value,
    scope_entity_id: scope.value,
    version: version.value,
    positions: positions.value,
    updated_at: updatedAt.value,
  });
};
