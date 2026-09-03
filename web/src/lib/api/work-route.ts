import { NextResponse, type NextRequest } from "next/server";
import { backendDisclosure, invokeGateway, transportLimitations, type GatewayCapability } from "@/lib/api/gateway";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import type { PrincipalSession } from "@/contracts/identity";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";

export type WorkField = {
  readonly gateway: string;
  readonly type: "string" | "integer" | "boolean" | "string-array" | "mutation-array";
  readonly maxItems?: number;
};
type FieldMap = Readonly<Record<string, WorkField>>;
type InputKind = "query" | "body";

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

function invalid(message: string) {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown, maximum: number): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every((item) => typeof item === "string")
  );
}

const BULK_UPDATE_VALUES: Readonly<Record<string, "string" | "boolean">> = {
  title: "string",
  description: "string",
  priority: "string",
  due_at: "string",
  scheduled_at: "string",
  deferred_until: "string",
  commitment_id: "string",
  role: "string",
  archived: "boolean",
};
const BULK_CLEAR_FIELDS = new Set([
  "description",
  "priority",
  "due_at",
  "scheduled_at",
  "deferred_until",
  "commitment_id",
  "role",
]);

function isBoundedMutationArray(value: unknown, maximum: number): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > maximum) return false;
  return value.every((item) => {
    if (!isRecord(item)) return false;
    if (
      typeof item.kind !== "string" ||
      typeof item.task_id !== "string" ||
      typeof item.expected_version !== "number" ||
      !Number.isSafeInteger(item.expected_version) ||
      item.expected_version < 1
    ) {
      return false;
    }
    if (item.kind === "update") {
      const keys = Object.keys(item);
      if (
        keys.some(
          (key) =>
            !["kind", "task_id", "expected_version", "values", "clear_fields"].includes(key),
        ) ||
        !isRecord(item.values) ||
        !isStringArray(item.clear_fields, BULK_CLEAR_FIELDS.size)
      ) {
        return false;
      }
      if (
        item.clear_fields.some((name) => !BULK_CLEAR_FIELDS.has(name)) ||
        new Set(item.clear_fields).size !== item.clear_fields.length
      ) {
        return false;
      }
      const valueEntries = Object.entries(item.values);
      if (valueEntries.length < 1 && item.clear_fields.length < 1) return false;
      return valueEntries.every(([name, entry]) => {
        const expected = BULK_UPDATE_VALUES[name];
        return expected !== undefined && typeof entry === expected;
      });
    }
    if (item.kind === "transition") {
      if (
        Object.keys(item).some(
          (key) =>
            ![
              "kind",
              "task_id",
              "expected_version",
              "to_state",
              "closure_evidence_ref",
            ].includes(key),
        ) ||
        typeof item.to_state !== "string"
      ) {
        return false;
      }
      return (
        item.closure_evidence_ref === undefined ||
        typeof item.closure_evidence_ref === "string"
      );
    }
    return false;
  });
}

function parseField(browserName: string, value: unknown, field: WorkField, input: InputKind):
  | { readonly ok: true; readonly gateway: string; readonly value: unknown }
  | { readonly ok: false; readonly response: NextResponse } {
  const { gateway, type } = field;
  if (type === "string") {
    if (typeof value === "string") return { ok: true, gateway, value };
    return { ok: false, response: invalid(`${browserName} must be a string`) };
  }
  if (type === "integer") {
    if (typeof value === "number" && Number.isSafeInteger(value)) {
      return { ok: true, gateway, value };
    }
    if (input === "query" && typeof value === "string" && /^(0|[1-9]\d*)$/.test(value)) {
      const parsed = Number(value);
      if (Number.isSafeInteger(parsed)) return { ok: true, gateway, value: parsed };
    }
    return { ok: false, response: invalid(`${browserName} must be an integer`) };
  }
  if (type === "boolean") {
    if (typeof value === "boolean") return { ok: true, gateway, value };
    if (input === "query" && value === "true") return { ok: true, gateway, value: true };
    if (input === "query" && value === "false") return { ok: true, gateway, value: false };
    return { ok: false, response: invalid(`${browserName} must be true or false`) };
  }
  const maximum = field.maxItems ?? (type === "mutation-array" ? 100 : 32);
  if (type === "string-array") {
    if (isStringArray(value, maximum)) return { ok: true, gateway, value };
    return {
      ok: false,
      response: invalid(`${browserName} must be an array of at most ${maximum} strings`),
    };
  }
  if (isBoundedMutationArray(value, maximum)) return { ok: true, gateway, value };
  return {
    ok: false,
    response: invalid(`${browserName} must contain between 1 and ${maximum} valid mutations`),
  };
}

function mapped(source: Record<string, unknown>, fields: FieldMap, input: InputKind) {
  const unknown = Object.keys(source).filter((key) => !(key in fields));
  if (unknown.length > 0) return { ok: false as const, response: invalid(`unknown fields: ${unknown.join(", ")}`) };
  const payload: Record<string, unknown> = {};
  for (const [browserName, field] of Object.entries(fields)) {
    const value = source[browserName];
    if (value === undefined) continue;
    const parsed = parseField(browserName, value, field, input);
    if (!parsed.ok) return { ok: false as const, response: parsed.response };
    payload[parsed.gateway] = parsed.value;
  }
  return {
    ok: true as const,
    payload,
  };
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
    return notImplemented(scope, "Work mutations and reads require the executable Python Work plane; synthetic fixtures are not canonical Task or Commitment state.");
  }
  const outcome = await invokeGateway(principal, capability, payload);
  if (!outcome.ok) {
    const identifier = typeof payload.task_id === "string" ? { capability: "tasks.read" as const, payload: { task_id: payload.task_id }, key: "task" }
      : typeof payload.commitment_id === "string" ? { capability: "commitments.read" as const, payload: { commitment_id: payload.commitment_id }, key: "commitment" }
      : undefined;
    if (outcome.status === 409 && identifier) {
      const current = await invokeGateway(principal, identifier.capability, identifier.payload);
      if (current.ok && isRecord(current.result)) {
        const record = current.result[identifier.key];
        if (!isRecord(record)) {
          return gatewayRefusal(scope, outcome.status, outcome.error);
        }
        const refusal = await gatewayRefusal(scope, outcome.status, outcome.error).json();
        return NextResponse.json({ ...refusal, current: publicResult(record) }, { status: 409 });
      }
    }
    return gatewayRefusal(scope, outcome.status, outcome.error);
  }
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

async function serve(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  return dispatch(guard.principal, scope, capability, payload);
}

export async function workGet(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
) {
  const query = Object.fromEntries(request.nextUrl.searchParams.entries());
  const result = mapped(query, fields, "query");
  if (!result.ok) return noStore(result.response);
  return noStore(await serve(request, scope, capability, { ...result.payload, ...fixed }));
}

export async function workPost(
  request: NextRequest,
  scope: string,
  capability: GatewayCapability,
  fields: FieldMap,
  fixed: Record<string, unknown> = {},
) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return noStore(blocked as NextResponse);
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);
  const parsed = await readCleanBody(request);
  if (!parsed.ok) return noStore(parsed.response);
  const result = mapped(parsed.body, fields, "body");
  if (!result.ok) return noStore(result.response);
  return noStore(await dispatch(guard.principal, scope, capability, { ...result.payload, ...fixed }));
}
