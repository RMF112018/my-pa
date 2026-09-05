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
 *
 * **The kind is a default, not a precondition.** `captureKind` is optional and
 * resolves to `quick_note`; `conversation_log` is the other value the Python
 * `CaptureKind` admits, and an explicit conversation log is what seeds a skeletal
 * Conversation in the save transaction. Anything else is refused rather than
 * silently defaulted, because a caller that misspelled the kind asked for
 * something and would otherwise be given something else without being told.
 *
 * **What this route cannot report, and does not pretend to.** The receipt says
 * the note is durable. It says nothing about whether the asynchronous pipeline
 * later enriched it, because no capability this tier can call exposes the job's
 * state — the twenty-six-name capability contract has no job-status read and none answers
 * "how did processing go". So the answer distinguishes *durable* from *refused*
 * and stops there; a third state invented here would be a claim with nothing
 * behind it.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { captureAdmissions } from "@/lib/capture/idempotency";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import { SESSION_COOKIE_NAME, sessionReplayBinding } from "@/lib/auth/session";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";

const SCOPE = "capture";

/** The two kinds the Python `CaptureKind` admits, and the one a caller gets by default. */
const CAPTURE_KINDS = ["quick_note", "conversation_log"] as const;
type CaptureKind = (typeof CAPTURE_KINDS)[number];
const DEFAULT_CAPTURE_KIND: CaptureKind = "quick_note";

export async function POST(request: NextRequest) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked;

  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  // Checked before `readCleanBody`: a cookie transition must be refused before
  // the BFF parses queued plaintext, not merely before the gateway write.
  const replayBinding = request.headers.get("x-my-pa-replay-binding");
  if (replayBinding !== null) {
    if (replayBinding.length !== 64) {
      return NextResponse.json(
        { error: { errorClass: "validation", code: "invalid_replay_binding", message: "replay binding is invalid" } },
        { status: 400 },
      );
    }
    const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
    if (!token || replayBinding !== (await sessionReplayBinding(token))) {
      return NextResponse.json(
        {
          error: {
            errorClass: "authentication",
            code: "replay_session_changed",
            message: "the authenticated session changed before replay admission",
          },
        },
        { status: 409 },
      );
    }
  }

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

  const requestedKind = parsed.body["captureKind"];
  const captureKind: CaptureKind =
    requestedKind === undefined || requestedKind === null
      ? DEFAULT_CAPTURE_KIND
      : (requestedKind as CaptureKind);
  if (!CAPTURE_KINDS.includes(captureKind)) {
    return NextResponse.json(
      {
        error: {
          errorClass: "validation",
          code: "unknown_capture_kind",
          message: `captureKind must be one of ${CAPTURE_KINDS.join(", ")}`,
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
      captureKind,
      status: "acknowledged_not_persisted",
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "capture.create", {
    text: text.trim(),
    idempotency_key: idempotencyKey.trim(),
    capture_kind: captureKind,
  });
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const receipt = outcome.result;
  return NextResponse.json({
    shape: "backend",
    status: "persisted",
    captureKind,
    receipt: {
      receiptId: receipt.receipt_id,
      captureId: receipt.capture_id,
      versionId: receipt.version_id,
      versionNumber: receipt.version_number,
      idempotencyKey: receipt.idempotency_key,
      contentSha256: receipt.content_sha256,
      // This value is derived from the same authenticated guard that authorized
      // the gateway call. It is never echoed from queue metadata or request JSON.
      principalId: guard.principal.principalId,
      issuedAt: receipt.issued_at,
    },
    created: receipt.created,
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
