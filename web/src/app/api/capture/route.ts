/**
 * Quick Capture — one user-authored note, stored durably.
 *
 * Backed by the Python `capture.create`, which writes the capture, its first
 * version, its receipt, its submission and its queued processing job on one
 * connection inside one transaction, and returns the receipt that write issued:
 * `receipt_id`, `capture_id`, `version_id`, `version_number`, `idempotency_key`,
 * `content_sha256`, `issued_at`, and whether this call created the capture or
 * replayed an existing one.
 *
 * **`acknowledged_not_persisted` is gone from the backend path.** It was true
 * while the receipt was minted by an in-process `Map` in `lib/capture/idempotency`
 * that a restart emptied. It is not true of the row `capture.create` commits, so
 * continuing to say it would understate what happened — and a caller that has
 * been told its note was not persisted has been told to keep it somewhere else.
 * The literal survives only on the explicitly-enabled synthetic path, where it
 * is still exactly accurate.
 *
 * **Idempotency is the backend's.** `UNIQUE (principal_id, idempotency_key)`
 * enforces it in PostgreSQL, a replay with identical content returns the original
 * receipt with `created = false`, and the same key bound to different content is
 * `conflict`. The web-tier admission map is no longer consulted on this path: two
 * idempotency ledgers for one key is the divergence this repository has been bitten
 * by before, and the durable one is the one that decides.
 *
 * **Capture text never appears in the response.** The receipt carries a content
 * digest, which is what makes a replay checkable without echoing the content.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { captureAdmissions } from "@/lib/capture/idempotency";
import { backendDisclosure, callGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const SCOPE = "capture";

interface PythonReceipt {
  readonly receipt_id: string;
  readonly capture_id: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly idempotency_key: string;
  readonly content_sha256: string;
  readonly issued_at: string;
  readonly created: boolean;
}

export async function POST(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const text = parsed.body["text"];
  if (typeof text !== "string" || text.trim().length === 0) {
    return NextResponse.json(
      { error: { errorClass: "validation", code: "empty_capture", message: "capture text must be non-empty" } },
      { status: 400 },
    );
  }

  const idempotencyKey = parsed.body["idempotencyKey"];
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim().length === 0) {
    return NextResponse.json(
      {
        error: {
          errorClass: "validation",
          code: "missing_idempotency_key",
          message: "capture submissions must carry an idempotencyKey",
        },
      },
      { status: 400 },
    );
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    const outcome = captureAdmissions.admit(
      guard.principal.principalId,
      idempotencyKey.trim(),
      text.trim(),
    );
    if (!outcome.ok) {
      return NextResponse.json(
        {
          error: {
            errorClass: "conflict",
            code: "capture_conflict",
            message: "this idempotency key was already used with different content",
          },
        },
        { status: 409 },
      );
    }
    return NextResponse.json({
      shape: "synthetic",
      receiptId: outcome.receipt.receiptId,
      created: outcome.receipt.created,
      status: "acknowledged_not_persisted",
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await callGateway<PythonReceipt>(guard.principal, "capture.create", {
    text: text.trim(),
    idempotency_key: idempotencyKey.trim(),
  });
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);

  return NextResponse.json({
    shape: "backend",
    status: "persisted",
    receipt: {
      receiptId: outcome.result.receipt_id,
      captureId: outcome.result.capture_id,
      versionId: outcome.result.version_id,
      versionNumber: outcome.result.version_number,
      idempotencyKey: outcome.result.idempotency_key,
      contentSha256: outcome.result.content_sha256,
      issuedAt: outcome.result.issued_at,
    },
    created: outcome.result.created,
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
