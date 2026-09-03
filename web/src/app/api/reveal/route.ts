/**
 * Reveal — **backend-backed, and the three answers stay three answers.**
 *
 * This route answered `501 not_implemented` until WP-09, and the reason it gave
 * was accurate at the time: no member of the v1 capability set took a subject
 * identifier and returned its derivation. `knowledge.reveal` is that member now.
 * It returns the evidence spans behind a subject, the versions their offsets are
 * counted in, and the derivation trace from proposal through review case and
 * decision to assertion and promotion receipt.
 *
 * **What this route must not flatten.** The backend distinguishes three
 * outcomes, and a BFF that mapped them onto "some data or an error" would undo
 * the whole point of the capability:
 *
 * * `evidence` — spans were found;
 * * `no_evidence` — the scope was searched to completion and holds none;
 * * `unavailable` — the scope **could not be searched**, because the subject
 *   kind is outside this build's evidence model or a version's derivation has
 *   not completed. It carries no rows, exactly like `no_evidence`, and is a
 *   different answer.
 *
 * So `state` is passed through unchanged and the disclosure is built from the
 * backend's own envelope, where an unavailable reveal already carries
 * `coverage: "unavailable"` and `partial_result`. Nothing here derives a state
 * by counting the arrays — that is the mistake the backend's typed outcome
 * exists to make impossible, and repeating it here would reintroduce it one tier
 * up.
 *
 * **A subject nobody owns is `404`, and so is a subject somebody else owns.**
 * The gateway answers `not_found` for both, deliberately, so this route sees one
 * status and cannot tell them apart either.
 *
 * The synthetic path still says plainly that the subject is a fixture. In a
 * default build there is no synthetic path and no explanation is manufactured.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import type { KnowledgeRevealResult } from "@/lib/api/decode/capabilities/knowledge.reveal";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const SCOPE = "reveal";

/** The opaque-identifier shape the Python domain enforces, restated for early refusal. */
const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

export async function POST(request: NextRequest) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked;

  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const subjectId = parsed.body["subjectId"];
  if (typeof subjectId !== "string" || subjectId.length === 0) {
    return NextResponse.json(
      { error: { errorClass: "validation", code: "missing_subject", message: "subjectId is required" } },
      { status: 400 },
    );
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      state: "unavailable",
      reason:
        "This item is a synthetic fixture created to exercise the shell. Its evidence was not " +
        "searched, because there is none to search.",
      disclosure: syntheticDisclosure(`${SCOPE}:${subjectId}`),
    });
  }

  if (!IDENTIFIER.test(subjectId)) {
    return NextResponse.json(
      {
        error: {
          errorClass: "validation",
          code: "invalid_identifier",
          message: "subjectId must be an opaque identifier of the form prefix_suffix",
        },
      },
      { status: 400 },
    );
  }

  const outcome = await invokeGateway(guard.principal, "knowledge.reveal", {
    subject_id: subjectId,
  });
  if (!outcome.ok) return gatewayRefusal(`${SCOPE}:knowledge.reveal`, outcome.status, outcome.error);
  const revealed = outcome.result as KnowledgeRevealResult;

  return NextResponse.json({
    shape: "backend",
    // Passed through, never recomputed. See the module docstring.
    state: revealed.state,
    result: revealed,
    disclosure: backendDisclosure(
      `${SCOPE}:knowledge.reveal`,
      outcome.disclosure,
      transportLimitations(),
    ),
  });
}
