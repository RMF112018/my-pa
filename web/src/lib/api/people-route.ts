import { NextResponse, type NextRequest } from "next/server";
import { backendDisclosure, invokeGateway, transportLimitations, type GatewayCapability } from "@/lib/api/gateway";
import { requirePrincipal } from "@/lib/api/guard";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import type { PrincipalSession } from "@/contracts/identity";

export type PeopleField = {
  readonly gateway: string;
  readonly type: "string" | "integer" | "boolean" | "string-list";
};
type FieldMap = Readonly<Record<string, PeopleField>>;

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

export function peopleInvalid(message: string) {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseField(
  browserName: string,
  value: unknown,
  field: PeopleField,
):
  | { readonly ok: true; readonly gateway: string; readonly value: unknown }
  | { readonly ok: false; readonly response: NextResponse } {
  const { gateway, type } = field;
  if (type === "string") {
    if (typeof value === "string") return { ok: true, gateway, value };
    return { ok: false, response: peopleInvalid(`${browserName} must be a string`) };
  }
  if (type === "integer") {
    if (typeof value === "number" && Number.isSafeInteger(value)) {
      return { ok: true, gateway, value };
    }
    if (typeof value === "string" && /^(0|[1-9]\d*)$/.test(value)) {
      const parsed = Number(value);
      if (Number.isSafeInteger(parsed)) return { ok: true, gateway, value: parsed };
    }
    return { ok: false, response: peopleInvalid(`${browserName} must be an integer`) };
  }
  if (type === "string-list") {
    if (typeof value !== "string") {
      return { ok: false, response: peopleInvalid(`${browserName} must be a string`) };
    }
    return {
      ok: true,
      gateway,
      value: value
        .split(",")
        .map((item) => item.trim())
        .filter((item) => item.length > 0),
    };
  }
  if (typeof value === "boolean") return { ok: true, gateway, value };
  if (value === "true") return { ok: true, gateway, value: true };
  if (value === "false") return { ok: true, gateway, value: false };
  return { ok: false, response: peopleInvalid(`${browserName} must be true or false`) };
}

function mapped(source: Record<string, unknown>, fields: FieldMap) {
  const unknown = Object.keys(source).filter((key) => !(key in fields));
  if (unknown.length > 0) {
    return { ok: false as const, response: peopleInvalid(`unknown fields: ${unknown.join(", ")}`) };
  }
  const payload: Record<string, unknown> = {};
  for (const [browserName, field] of Object.entries(fields)) {
    const value = source[browserName];
    if (value === undefined) continue;
    const parsed = parseField(browserName, value, field);
    if (!parsed.ok) return { ok: false as const, response: parsed.response };
    payload[parsed.gateway] = parsed.value;
  }
  return { ok: true as const, payload };
}

function publicResult(result: Record<string, unknown>) {
  return JSON.parse(
    JSON.stringify(result, (key, value) =>
      key === "principal_id" || key === "principalId" ? undefined : value,
    ),
  ) as Record<string, unknown>;
}

async function dispatch(
  principal: PrincipalSession,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(
      scope,
      "People reads the Python entity plane; synthetic fixtures are not canonical entity state.",
    );
  }
  const outcome = await invokeGateway(principal, capability, payload);
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

export async function peopleServe(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  return dispatch(guard.principal, scope, capability, payload);
}

export async function peopleGet(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
) {
  const query = Object.fromEntries(request.nextUrl.searchParams.entries());
  const result = mapped(query, fields);
  if (!result.ok) return noStore(result.response);
  return noStore(await peopleServe(request, scope, capability, { ...result.payload, ...fixed }));
}

export const PEOPLE_PAGE_FIELDS = {
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
} as const;
