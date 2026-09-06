import { NextResponse, type NextRequest } from "next/server";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayCapability,
} from "@/lib/api/gateway";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";

const SYNTHETIC_REASON =
  "The synthetic provider has no GoodNotes fixture. GoodNotes reads the Python GoodNotes " +
  "plane; run against the gateway to see it.";

export function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

export function goodnotesInvalid(message: string) {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
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

export function optionalPageSize(params: URLSearchParams): number | undefined | "invalid" {
  const raw = params.get("pageSize");
  if (raw === null || raw.trim() === "") return undefined;
  if (!/^(0|[1-9]\d*)$/.test(raw)) return "invalid";
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < 1) return "invalid";
  return parsed;
}

export function optionalQuery(params: URLSearchParams, name: string): string | undefined {
  const value = params.get(name)?.trim() ?? "";
  return value.length > 0 ? value : undefined;
}

export function requiredQuery(params: URLSearchParams, name: string): string | null {
  const value = params.get(name)?.trim() ?? "";
  return value.length > 0 ? value : null;
}

async function dispatch(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") return notImplemented(scope, SYNTHETIC_REASON);
  const outcome = await invokeGateway(guard.principal, capability, payload);
  if (!outcome.ok) return gatewayRefusal(scope, outcome.status, outcome.error);
  if (!isRecord(outcome.result)) {
    return gatewayRefusal(scope, 503, {
      errorClass: "unavailable",
      code: "upstream_contract_invalid",
      message: "the gateway result did not match the capability contract",
    });
  }
  return NextResponse.json({
    shape: "backend",
    ...publicResult(outcome.result),
    disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
  });
}

export async function goodnotesGet(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  return noStore(await dispatch(request, scope, capability, payload));
}

export async function goodnotesRaster(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const runId = requiredQuery(params, "runId");
  const pageVersionId = requiredQuery(params, "pageVersionId");
  const contentSha256 = requiredQuery(params, "contentSha256");
  if (runId === null || pageVersionId === null || contentSha256 === null) {
    return noStore(
      goodnotesInvalid("raster requires runId, pageVersionId, and contentSha256"),
    );
  }
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);
  const serving = resolveServing();
  if (serving.kind === "refused") return noStore(serving.response);
  if (serving.kind === "synthetic") {
    return noStore(notImplemented("goodnotes:goodnotes.content", SYNTHETIC_REASON));
  }
  const outcome = await invokeGateway(guard.principal, "goodnotes.content", {
    run_id: runId,
    page_version_id: pageVersionId,
    content_sha256: contentSha256,
  });
  if (!outcome.ok) return noStore(gatewayRefusal("goodnotes:goodnotes.content", outcome.status, outcome.error));
  const bytes = Buffer.from(outcome.result.content_base64, "base64");
  if (bytes.byteLength === 0 || bytes.byteLength !== outcome.result.byte_length) {
    return noStore(
      gatewayRefusal("goodnotes:goodnotes.content", 503, {
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
        message: "the gateway result did not match the capability contract",
      }),
    );
  }
  return new NextResponse(bytes, {
    status: 200,
    headers: {
      "content-type": "image/png",
      "cache-control": "private, no-store",
    },
  });
}

export async function goodnotesCorrect(request: NextRequest) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return noStore(blocked as NextResponse);
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);
  const parsed = await readCleanBody(request);
  if (!parsed.ok) return noStore(parsed.response);
  const occurrenceId = parsed.body.occurrenceId;
  const transcription = parsed.body.transcription;
  if (typeof occurrenceId !== "string" || occurrenceId.trim().length === 0) {
    return noStore(goodnotesInvalid("occurrenceId must be a non-empty string"));
  }
  if (typeof transcription !== "string" || transcription.length === 0) {
    return noStore(goodnotesInvalid("transcription must be a non-empty string"));
  }
  const serving = resolveServing();
  if (serving.kind === "refused") return noStore(serving.response);
  if (serving.kind === "synthetic") {
    return noStore(notImplemented("goodnotes:goodnotes.correct", SYNTHETIC_REASON));
  }
  const outcome = await invokeGateway(guard.principal, "goodnotes.correct", {
    occurrence_id: occurrenceId.trim(),
    transcription,
  });
  if (!outcome.ok) {
    return noStore(gatewayRefusal("goodnotes:goodnotes.correct", outcome.status, outcome.error));
  }
  if (!isRecord(outcome.result)) {
    return noStore(
      gatewayRefusal("goodnotes:goodnotes.correct", 503, {
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
        message: "the gateway result did not match the capability contract",
      }),
    );
  }
  return noStore(
    NextResponse.json({
      shape: "backend",
      ...publicResult(outcome.result),
      disclosure: backendDisclosure(
        "goodnotes:goodnotes.correct",
        outcome.disclosure,
        transportLimitations(),
      ),
    }),
  );
}
