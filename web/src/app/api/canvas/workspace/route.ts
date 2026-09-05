/**
 * Canvas workspace overlay — persist one seeded layout.
 *
 * Browser → this BFF → `canvas.workspace.put`. Identity is the session, not
 * the body. A stale `expected_version` is a typed conflict (409), not a
 * silent overwrite.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { invokeGateway } from "@/lib/api/gateway";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import { isFiniteInteger, isRecord } from "@/lib/api/decode/primitives";

const SCOPE = "canvas.workspace";

function refuse(code: string, message: string): NextResponse {
  return NextResponse.json({ error: { errorClass: "validation", code, message } }, { status: 400 });
}

function optionalSeed(value: unknown): string | undefined | "invalid" {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string" || value.trim().length === 0) return "invalid";
  return value.trim();
}

function parsePositions(value: unknown): Record<string, { x: number; y: number }> | null {
  if (!isRecord(value)) return null;
  const positions: Record<string, { x: number; y: number }> = {};
  for (const [entityId, point] of Object.entries(value)) {
    if (typeof entityId !== "string" || entityId.length === 0) return null;
    if (!isRecord(point)) return null;
    const keys = Object.keys(point);
    if (keys.length !== 2 || !keys.includes("x") || !keys.includes("y")) return null;
    if (typeof point.x !== "number" || !Number.isFinite(point.x)) return null;
    if (typeof point.y !== "number" || !Number.isFinite(point.y)) return null;
    positions[entityId] = { x: point.x, y: point.y };
  }
  return positions;
}

export async function POST(request: NextRequest) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked;

  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const focus = optionalSeed(parsed.body["focus_entity_id"]);
  const scope = optionalSeed(parsed.body["scope_entity_id"]);
  if (focus === "invalid") return refuse("invalid_focus_entity_id", "focus_entity_id must be a non-empty string");
  if (scope === "invalid") return refuse("invalid_scope_entity_id", "scope_entity_id must be a non-empty string");
  if (!focus && !scope) {
    return refuse("missing_seed", "at least one of focus_entity_id and scope_entity_id is required");
  }

  const expectedVersion = parsed.body["expected_version"];
  if (!isFiniteInteger(expectedVersion) || expectedVersion < 0) {
    return refuse("invalid_expected_version", "expected_version must be an integer >= 0");
  }

  const positions = parsePositions(parsed.body["positions"]);
  if (positions === null) {
    return refuse("invalid_positions", "positions must be a map of entity_id to {x, y} finite numbers");
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(SCOPE, "Map arrange is not available on the synthetic provider.");
  }

  const payload: Record<string, unknown> = {
    expected_version: expectedVersion,
    positions,
  };
  if (focus) payload.focus_entity_id = focus;
  if (scope) payload.scope_entity_id = scope;

  const outcome = await invokeGateway(guard.principal, "canvas.workspace.put", payload);
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const receipt = outcome.result;
  return NextResponse.json({
    version: receipt.version,
    updated_at: receipt.updated_at,
    positions: receipt.positions,
    focus_entity_id: receipt.focus_entity_id,
    scope_entity_id: receipt.scope_entity_id,
  });
}
