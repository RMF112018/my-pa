/**
 * Which provider a route serves from, and the honest answers when it serves
 * from neither.
 *
 * There are exactly three outcomes and no fourth, because the fourth is the one
 * this work package removed: a route that could not reach the backend used to
 * fall through to fixtures, so "the gateway is down" and "here is your data"
 * were the same response. They are separate here. `synthetic` requires the
 * explicit switch; `backend` is what a default build does; `refused` is a
 * misconfiguration, and it is answered `500` rather than `401` for the reason
 * `POST /api/session` answers a missing `MYPA_AUTH_MODE` that way — the visitor's
 * request is not what is wrong, and hiding a deployment fault behind a login
 * screen or an empty list keeps it hidden.
 *
 * `notImplemented` is the other honest answer, and it is a different one on
 * purpose. `unavailable` says the backend could not answer; `not_implemented`
 * says there is nothing on the backend to ask. Today, Situations and Reveal are
 * in the second state — no capability exposes a Pulse, Situation, or Reveal read
 * model through `POST /v1/{capability}` — and reporting that as `unavailable`
 * would imply a retry could succeed.
 */
import { NextResponse } from "next/server";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { statusForErrorClass } from "@/lib/api/gateway";
import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";

export type Serving =
  | { readonly kind: "synthetic" }
  | { readonly kind: "backend" }
  | { readonly kind: "refused"; readonly response: NextResponse };

/** Which provider this build serves from, or the operator-facing refusal. */
export function resolveServing(): Serving {
  try {
    return syntheticDataEnabled() ? { kind: "synthetic" } : { kind: "backend" };
  } catch (error) {
    return {
      kind: "refused",
      response: NextResponse.json(
        {
          error: {
            errorClass: "internal",
            code: "data_provider_not_usable",
            message: error instanceof Error ? error.message : "MYPA_DATA_PROVIDER is not usable",
          } satisfies ErrorEnvelope,
        },
        { status: 500 },
      ),
    };
  }
}

/**
 * A disclosure for an answer that carries no data and claims none.
 *
 * Never `coverage: "synthetic"`: nothing was fabricated, so labelling it as
 * fixture data would be as inaccurate as labelling fixture data real. The
 * limitations say what is missing, in the caller's own terms.
 */
export function statedDisclosure(
  scope: string,
  coverage: DisclosureEnvelope["coverage"],
  limitations: readonly string[],
): DisclosureEnvelope {
  return {
    scope,
    coverage,
    freshnessAt: null,
    authority: "derived",
    limitations: [...limitations],
    truncated: false,
  };
}

/** `501`: this build has no backend capability behind the surface being asked for. */
export function notImplemented(scope: string, reason: string): NextResponse {
  return NextResponse.json(
    {
      state: "not_implemented",
      error: {
        errorClass: "unavailable",
        code: "not_implemented",
        message: reason,
      } satisfies ErrorEnvelope,
      disclosure: statedDisclosure(scope, "unavailable", [reason]),
    },
    { status: 501 },
  );
}

/** The typed refusal a gateway error becomes, with a disclosure that says so. */
export function gatewayRefusal(
  scope: string,
  status: number,
  error: ErrorEnvelope,
): NextResponse {
  return NextResponse.json(
    {
      state: error.errorClass === "unavailable" ? "unavailable" : "denied",
      error,
      disclosure: statedDisclosure(scope, "unavailable", [error.message]),
    },
    { status: status || statusForErrorClass(error.errorClass) },
  );
}
