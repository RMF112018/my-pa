/**
 * Shared Intelligence BFF dispatch. Session Principal only; synthetic is
 * notImplemented rather than a fabricated report plane.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayCapability,
} from "@/lib/api/gateway";
import { requirePrincipal } from "@/lib/api/guard";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";

export const INTELLIGENCE_SCOPE = "intelligence";

const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

export function invalidIdentifier(field: string): NextResponse {
  return NextResponse.json(
    {
      error: {
        errorClass: "validation",
        code: "invalid_identifier",
        message: `${field} must be an opaque identifier of the form prefix_suffix`,
      },
    },
    { status: 400 },
  );
}

export function invalidField(message: string): NextResponse {
  return NextResponse.json(
    {
      error: {
        errorClass: "validation",
        code: "invalid_request",
        message,
      },
    },
    { status: 400 },
  );
}

export function optionalIdentifier(
  value: string | null,
  field: string,
): string | NextResponse | undefined {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) return undefined;
  if (!IDENTIFIER.test(trimmed)) return invalidIdentifier(field);
  return trimmed;
}

export function optionalString(value: string | null): string | undefined {
  const trimmed = value?.trim() ?? "";
  return trimmed ? trimmed : undefined;
}

export function optionalInteger(
  value: string | null,
  field: string,
): number | NextResponse | undefined {
  if (value === null || value === "") return undefined;
  if (!/^(0|[1-9]\d*)$/.test(value)) return invalidField(`${field} must be an integer`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) return invalidField(`${field} must be an integer`);
  return parsed;
}

export function optionalBoolean(
  value: string | null,
  field: string,
): boolean | NextResponse | undefined {
  if (value === null || value === "") return undefined;
  if (value === "true") return true;
  if (value === "false") return false;
  return invalidField(`${field} must be true or false`);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function publicResult(result: Record<string, unknown>) {
  return JSON.parse(
    JSON.stringify(result, (key, value) =>
      key === "principal_id" || key === "principalId" ? undefined : value,
    ),
  ) as Record<string, unknown>;
}

export async function intelligenceGet(
  request: NextRequest,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
): Promise<NextResponse> {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(
      INTELLIGENCE_SCOPE,
      "The synthetic provider has no report fixture. Report reads require the executable Python Intelligence plane.",
    );
  }

  const outcome = await invokeGateway(guard.principal, capability, payload);
  if (!outcome.ok) {
    return gatewayRefusal(`${INTELLIGENCE_SCOPE}:${capability}`, outcome.status, outcome.error);
  }
  if (!isRecord(outcome.result)) {
    return gatewayRefusal(`${INTELLIGENCE_SCOPE}:${capability}`, 503, {
      errorClass: "unavailable",
      code: "upstream_contract_invalid",
      message: "the gateway result did not match the capability contract",
    });
  }
  const disclosure = backendDisclosure(
    `${INTELLIGENCE_SCOPE}:${capability}`,
    outcome.disclosure,
    transportLimitations(),
  );
  return NextResponse.json({
    shape: "backend",
    state: disclosure.coverage === "unavailable" ? "unavailable" : "results",
    result: publicResult(outcome.result),
    disclosure,
  });
}
