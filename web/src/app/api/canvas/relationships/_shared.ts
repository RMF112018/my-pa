/**
 * Shared admission and body guards for the three canvas relationship writes.
 *
 * Browser → this BFF → `entities.relationships.{create,revise,end}`. Identity
 * is the session, not the body. Entity and relationship clocks are not the
 * canvas overlay version.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";
import { isFiniteInteger } from "@/lib/api/decode/primitives";
import type { DirectedRelationshipWriteResult } from "@/lib/api/decode/capabilities/entities.relationships.write";
import type { PrincipalSession } from "@/contracts/identity";
import type { ErrorEnvelope } from "@/contracts/envelope";

export const SCOPE = "canvas.relationships";

export const SYNTHETIC_UNAVAILABLE =
  "Relationship editing is not available on the synthetic provider.";

export type AdmittedWrite = {
  readonly principal: PrincipalSession;
  readonly body: Record<string, unknown>;
};

export function refuse(code: string, message: string): NextResponse {
  return NextResponse.json({ error: { errorClass: "validation", code, message } }, { status: 400 });
}

export async function admitRelationshipWrite(
  request: NextRequest,
): Promise<{ ok: true; value: AdmittedWrite } | { ok: false; response: Response }> {
  const blocked = admitBrowserMutation(request);
  if (blocked) return { ok: false, response: blocked };
  const guard = await requirePrincipal(request);
  if (!guard.ok) return { ok: false, response: guard.response };
  const parsed = await readCleanBody(request);
  if (!parsed.ok) return { ok: false, response: parsed.response };
  return { ok: true, value: { principal: guard.principal, body: parsed.body } };
}

export function refuseUnknownKeys(
  body: Record<string, unknown>,
  allowed: readonly string[],
): NextResponse | null {
  const admitted = new Set(allowed);
  for (const key of Object.keys(body)) {
    if (!admitted.has(key)) {
      return refuse("unexpected_field", "request body contained an unexpected field");
    }
  }
  return null;
}

export function requiredNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string" || value.trim().length === 0) return null;
  return value.trim();
}

/** Entity/relationship clocks start at 1. Not canvas.workspace overlay 0. */
export function requiredVersion(value: unknown): number | null {
  if (!isFiniteInteger(value) || value < 1) return null;
  return value;
}

export function optionalNonEmptyString(value: unknown): string | undefined | "invalid" {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string" || value.trim().length === 0) return "invalid";
  return value.trim();
}

export function optionalEvidenceRefs(value: unknown): readonly string[] | undefined | "invalid" {
  if (value === undefined || value === null) return undefined;
  if (!Array.isArray(value)) return "invalid";
  const refs: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || item.trim().length === 0) return "invalid";
    refs.push(item.trim());
  }
  return refs;
}

export function backendOrRefuse(): NextResponse | null {
  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(SCOPE, SYNTHETIC_UNAVAILABLE);
  }
  return null;
}

export function refusedGateway(status: number, error: ErrorEnvelope): NextResponse {
  return gatewayRefusal(SCOPE, status, error);
}

export function writeReceiptJson(receipt: DirectedRelationshipWriteResult): NextResponse {
  return NextResponse.json({
    record_id: receipt.record_id,
    record_family: receipt.record_family,
    prior_version: receipt.prior_version,
    version: receipt.version,
    state: receipt.state,
    receipt_id: receipt.receipt_id,
    audit_id: receipt.audit_id,
    idempotency_key: receipt.idempotency_key,
    superseded_id: receipt.superseded_id,
    evidence_refs: receipt.evidence_refs,
    replayed: receipt.replayed,
    issued_at: receipt.issued_at,
  });
}
