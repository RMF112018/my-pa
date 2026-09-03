/**
 * Library — the browsable record, read from the Python knowledge and capture
 * planes.
 *
 * Four capabilities behind one surface, selected by what the caller asked for
 * and never by a fallback:
 *
 * * `?knowledgeId=&enrollmentId=` -> `knowledge.read` — one stored record and
 *   its provenance, inside the stated grant.
 * * `?q=&enrollmentId=` -> `knowledge.search` — lexical search inside one
 *   enrollment's grant.
 * * `?q=` -> `capture.search` — exact lexical search over the principal's own
 *   captures, which belong to no enrollment and need none.
 * * nothing -> `capture.list` — one page of stored captures, newest first.
 *
 * **An enrollment identifier is not identity and is not trusted as authority.**
 * It names a grant, and the Python authorization resolves it against the acting
 * Principal's own enrollments: one belonging to another Principal is refused
 * there, not here. What this route refuses is shape — an `enr_`-prefixed opaque
 * identifier — so a malformed value fails before a request is built.
 *
 * **An unavailable scope is not an empty page.** The response carries a `state`
 * discriminator beside the result, read off the coverage the gateway disclosed:
 * a scope the backend reports `unavailable` was not searched, and returning its
 * empty `result` without saying so would be the claim `INV-PKL-007` prohibits.
 * The discriminator is a pass-through of the backend's own answer, never a
 * measurement of how many rows came back.
 *
 * **There is no synthetic Library fixture and none is invented.** With the
 * synthetic provider on, this surface answers `not_implemented` rather than
 * fabricating records, because a fixture written now would be a second thing to
 * keep true about a plane that is already real.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayCapability,
} from "@/lib/api/gateway";
import { gatewayRefusal, notImplemented, resolveServing } from "@/lib/api/serving";

const SCOPE = "library";

/** The opaque-identifier shape the Python domain enforces, restated for early refusal. */
const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

function invalid(field: string): NextResponse {
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

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "synthetic") {
    return notImplemented(
      SCOPE,
      "The synthetic provider has no Library fixture. Library reads the Python knowledge " +
        "and capture planes; run against the gateway to see it.",
    );
  }

  const params = request.nextUrl.searchParams;
  const query = params.get("q")?.trim() ?? "";
  const enrollmentId = params.get("enrollmentId")?.trim() ?? "";
  const knowledgeId = params.get("knowledgeId")?.trim() ?? "";
  const requestedPage = Number.parseInt(params.get("pageSize") ?? "", 10);
  const pageSize = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : undefined;

  if (enrollmentId && !IDENTIFIER.test(enrollmentId)) return invalid("enrollmentId");
  if (knowledgeId && !IDENTIFIER.test(knowledgeId)) return invalid("knowledgeId");

  let capability: GatewayCapability;
  let payload: Record<string, unknown>;
  if (knowledgeId) {
    if (!enrollmentId) {
      return NextResponse.json(
        {
          error: {
            errorClass: "validation",
            code: "missing_enrollment",
            message:
              "reading a knowledge record requires the enrollmentId whose grant it was " +
              "stored under; a record written under one grant is not readable through another",
          },
        },
        { status: 400 },
      );
    }
    capability = "knowledge.read";
    payload = { knowledge_id: knowledgeId, enrollment_id: enrollmentId };
  } else if (query && enrollmentId) {
    capability = "knowledge.search";
    payload = { enrollment_id: enrollmentId, query, page_size: pageSize };
  } else if (query) {
    capability = "capture.search";
    payload = { query, page_size: pageSize };
  } else {
    capability = "capture.list";
    payload = { page_size: pageSize };
  }

  const outcome = await invokeGateway(guard.principal, capability, payload);
  if (!outcome.ok) return gatewayRefusal(`${SCOPE}:${capability}`, outcome.status, outcome.error);

  const disclosure = backendDisclosure(
    `${SCOPE}:${capability}`,
    outcome.disclosure,
    transportLimitations(),
  );
  return NextResponse.json({
    capability,
    // **Read off the backend's own coverage, never off the result's length.**
    // A scope the gateway reports `unavailable` was not searched — `INV-PKL-007`
    // forbids reporting that as empty — and a caller that counted `result` would
    // show "nothing here" for it. The discriminator exists so a renderer does not
    // have to know that `coverage` carries the distinction, and so a future one
    // that stops reading `disclosure` cannot lose it.
    state: disclosure.coverage === "unavailable" ? "unavailable" : "results",
    result: outcome.result,
    disclosure,
  });
}
