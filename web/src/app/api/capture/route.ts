/**
 * Capture route — WP-03.
 *
 * The principal comes from the verified session only, the idempotency key
 * is scoped to that principal, and a replay returns the original receipt
 * with `created = false` — mirroring the Python capture plane's
 * `UNIQUE (principal_id, idempotency_key)` contract at revision
 * `e7f3a9c2d514` (ADR-005, PKL-MYPA-D-WP03-001). Persistence into the
 * Python pipeline is not yet wired; the disclosure says so on every
 * response. Capture text never appears in the receipt.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { captureAdmissions } from "@/lib/capture/idempotency";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function POST(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const text = parsed.body["text"];
  if (typeof text !== "string" || text.trim().length === 0) {
    return NextResponse.json(
      { error: { code: "empty_capture", message: "capture text must be non-empty" } },
      { status: 400 },
    );
  }

  const idempotencyKey = parsed.body["idempotencyKey"];
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim().length === 0) {
    return NextResponse.json(
      {
        error: {
          code: "missing_idempotency_key",
          message: "capture submissions must carry an idempotencyKey",
        },
      },
      { status: 400 },
    );
  }

  const outcome = captureAdmissions.admit(
    guard.principal.principalId,
    idempotencyKey.trim(),
    text.trim(),
  );
  if (!outcome.ok) {
    return NextResponse.json(
      {
        error: {
          code: "capture_conflict",
          message: "this idempotency key was already used with different content",
        },
      },
      { status: 409 },
    );
  }

  return NextResponse.json({
    receiptId: outcome.receipt.receiptId,
    created: outcome.receipt.created,
    status: "acknowledged_not_persisted",
    disclosure: syntheticDisclosure("capture"),
  });
}
