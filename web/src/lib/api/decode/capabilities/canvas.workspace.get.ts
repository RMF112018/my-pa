import { isRecord, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  fail,
  pick,
  requiredInt,
  requiredNullableString,
  requiredRecord,
} from "./_read-helpers";

export interface CanvasPoint {
  readonly x: number;
  readonly y: number;
}

export type CanvasPositions = Readonly<Record<string, CanvasPoint>>;

export interface CanvasWorkspaceGetResult {
  readonly focus_entity_id: string | null;
  readonly scope_entity_id: string | null;
  readonly version: number;
  readonly positions: CanvasPositions;
  readonly updated_at: string | null;
}

function requiredFiniteNumber(value: unknown): DecodeResult<number> {
  if (value === undefined) return fail("a required field was missing");
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail("a required field was not the expected type");
  }
  return ok(value);
}

export function decodeCanvasPoint(input: unknown): DecodeResult<CanvasPoint> {
  const record = requiredRecord(input);
  if (!record.ok) return record;
  for (const key of Object.keys(record.value)) {
    if (key !== "x" && key !== "y") {
      return fail("an unexpected field was present");
    }
  }
  const x = requiredFiniteNumber(record.value.x);
  if (!x.ok) return x;
  const y = requiredFiniteNumber(record.value.y);
  if (!y.ok) return y;
  return ok({ x: x.value, y: y.value });
}

export function decodeCanvasPositions(value: unknown): DecodeResult<CanvasPositions> {
  if (value === undefined) return fail("a required field was missing");
  if (!isRecord(value)) return fail("a required field was not the expected type");
  const positions: Record<string, CanvasPoint> = {};
  for (const [entityId, point] of Object.entries(value)) {
    const decoded = decodeCanvasPoint(point);
    if (!decoded.ok) return decoded;
    positions[entityId] = decoded.value;
  }
  return ok(positions);
}

export const decodeCanvasWorkspaceGet: Decoder<CanvasWorkspaceGetResult> = (input) => {
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
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  return ok({
    focus_entity_id: focus.value,
    scope_entity_id: scope.value,
    version: version.value,
    positions: positions.value,
    updated_at: updatedAt.value,
  });
};
