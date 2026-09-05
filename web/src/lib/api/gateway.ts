/**
 * The BFF's one transport to the Python gateway. **Server-only. Node runtime.**
 *
 * Until this module existed there was no server-side client to the Python
 * application anywhere in this tree: all ten route handlers assembled fixtures
 * and `lib/api/client.ts` was a browser-side wrapper around those routes. The
 * chain the operating brief asks for — `Next.js/PWA -> authenticated BFF/API ->
 * Python application service -> policy/Principal scope -> PostgreSQL` — was
 * missing its middle link. This is that link and nothing more: it speaks
 * `POST /v1/{capability}`, builds the canonical envelope, and maps what comes
 * back into the web tier's existing typed vocabulary.
 *
 * **Identity is filled from the verified session and from nowhere else.** The
 * envelope's `principal_id` is derived — by SHA-256 over a fixed domain-separated
 * string and the session's `tid`/`oid` — from the `PrincipalSession` that
 * `requirePrincipal` resolved out of the signed cookie. It is never read from a
 * body, a query string, or a header, and `rejectCallerSuppliedPrincipal` runs on
 * every payload before it is sent, so a caller that names a principal is refused
 * rather than ignored. The value is a *correlation* identifier on the Python
 * side and is read by nothing there — `RequestMetadata.principal_id` is required
 * by the contract and consulted by no production module, and an architecture
 * guard keeps that a measurement. This module does not change that and must not:
 * the acting Principal is the gateway's to establish, from its own authenticated
 * context, exactly as `docs/specs` section 8.2 requires.
 *
 * **A credential is forwarded or the request is refused; one is never invented.**
 * In `local_operator` mode the gateway acts as its own fixed process principal
 * and no `Authorization` header is sent at all — and because that is true, the
 * disclosure the caller receives says so, through `LOCAL_OPERATOR_LIMITATION`.
 * Claiming session-scoped data in that mode would be false: the gateway serves
 * one principal per process regardless of who is signed in here. In `entra` mode
 * a bearer token is required. Browser Entra/MSAL is retired, so this BFF has no
 * forwardable Entra credential: the honest answer is `unavailable`. Minting a
 * token, sending the session cookie as a bearer, accepting a token from the
 * request, or falling back to unauthenticated mode remain impossible here.
 *
 * **Where the request stops.** Failure is always a typed state, never an empty
 * success: a refused, unreachable, or unparseable gateway produces an
 * `ErrorEnvelope` with one of the eight `errorClass` values the web contract
 * already publishes, and `unavailable`, `not_found`, `conflict` and
 * `policy_denied` stay distinguishable rather than collapsing into "no data".
 */
import contract from "@/contracts/gateway.json";
import { rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";
import { decodeCapability } from "@/lib/api/decode";
import type { CapabilityResults } from "@/lib/api/decode";
import type { DecodedDisclosure } from "@/lib/api/decode/disclosure";
import { decodeEnvelope } from "@/lib/api/decode/envelope";
import {
  httpStatusForProblem,
  PROBLEM_ERROR_CLASS,
  type DecodedProblem,
} from "@/lib/api/decode/problem";
import { gatewayAuthMode, gatewayBaseUrl } from "@/lib/api/gateway-config";
import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";
import type { PrincipalSession } from "@/contracts/identity";

/** A capability name this BFF is allowed to address. */
export type GatewayCapability = keyof typeof contract.capabilities;

/** The disclosure the Python contract emits, after runtime decode. */
export type PythonDisclosure = DecodedDisclosure;

export type GatewayOutcome<T> =
  | { readonly ok: true; readonly result: T; readonly disclosure: PythonDisclosure }
  | { readonly ok: false; readonly status: number; readonly error: ErrorEnvelope };

/**
 * How long the BFF waits for the gateway before calling it unavailable.
 *
 * Bounded rather than open-ended for the reason the Python transport bounds its
 * own body read: an unbounded wait is a route handler that stops answering, and
 * a request nobody is waiting for is still holding a connection.
 */
export const GATEWAY_TIMEOUT_MS = 10_000;

/**
 * The limitation every `local_operator`-mode result carries, and the reason it
 * is not optional.
 *
 * The gateway in that mode serves one principal for the life of the process
 * (`D-30`). A response saying "this is yours" would therefore be a claim this
 * tier cannot support, and the acceptance criterion for this work package is
 * that disclosures remain accurate rather than that they remain reassuring.
 */
export const LOCAL_OPERATOR_LIMITATION =
  "The gateway runs in local_operator mode: results belong to the deployment's single " +
  "local-operator principal and are not partitioned by browser session.";

/** Raised when this module is reached from anywhere but a Node server context. */
export class GatewayIsServerOnlyError extends Error {
  constructor() {
    super(
      "lib/api/gateway is server-only. It resolves a backend address from server " +
        "configuration and speaks to the Python gateway directly; importing it into a " +
        "client component or Edge middleware would either ship that address to a browser " +
        "or run it where the session registry does not exist.",
    );
    this.name = "GatewayIsServerOnlyError";
  }
}

/** The eleven Python error codes, mapped onto the web tier's error vocabulary. */
const ERROR_CLASS = PROBLEM_ERROR_CLASS;

/** The HTTP status each error class is answered with by this tier. */
const ERROR_STATUS: Record<ErrorEnvelope["errorClass"], number> = {
  validation: 400,
  authentication: 401,
  authorization: 403,
  not_found: 404,
  conflict: 409,
  policy_denied: 403,
  unavailable: 503,
  internal: 500,
};

/** The status this tier answers a mapped gateway error with. */
export function statusForErrorClass(errorClass: ErrorEnvelope["errorClass"]): number {
  return ERROR_STATUS[errorClass];
}

function unavailable(code: string, message: string): { status: number; error: ErrorEnvelope } {
  return { status: 503, error: { errorClass: "unavailable", code, message } };
}

/**
 * The correlation identifier the envelope carries, derived from the verified
 * session.
 *
 * Derived rather than passed through, because the web tier's `principalId` is
 * `syn-…`-shaped and the Python contract requires a `prn_` identifier of 8-64
 * alphanumeric characters — and because a *derivation* cannot be influenced by
 * anything the browser sends. The inputs are `tid` and `oid`, which are the only
 * two fields of a session that are identity at all; `upn` and `displayName` are
 * mutable observations and are deliberately not in the digest.
 *
 * This value is correlation input on the far side and authorises nothing. The
 * gateway derives the acting Principal from its own authenticated context.
 */
export async function correlationPrincipalId(principal: PrincipalSession): Promise<string> {
  const material = `my-pa/bff/principal-correlation/v1/${principal.tid}/${principal.oid}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material));
  const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  return `prn_${hex.slice(0, 32)}`;
}

/**
 * The request document for one capability, built from the shared contract.
 *
 * The capability itself is **not** in the document: the Python `normalize` takes
 * it from the routed path and would receive the argument twice, refusing the
 * request. Undefined payload entries are dropped rather than sent as `null`,
 * because several commands distinguish "the caller did not say" from "the caller
 * said nothing" and a `null` would answer the second question.
 */
export async function buildRequestDocument(
  principal: PrincipalSession,
  capability: GatewayCapability,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  rejectCallerSuppliedPrincipal(payload);
  const defined = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  );
  return {
    contract_version: contract.contractVersion,
    request_id: `bff-${crypto.randomUUID()}`,
    purpose: contract.capabilities[capability].purpose,
    principal_id: await correlationPrincipalId(principal),
    requested_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    [contract.payloadKey]: defined,
  };
}

/** Refuse to run anywhere a browser could reach. */
function assertServerContext(): void {
  if (typeof window !== "undefined") throw new GatewayIsServerOnlyError();
}

/**
 * The headers one request carries, or a refusal naming what is missing.
 *
 * In `entra` gateway mode a bearer is required and this BFF has none: browser
 * Entra/MSAL is retired. None is created or accepted from request input here.
 */
function requestHeaders():
  | { ok: true; headers: Record<string, string> }
  | { ok: false; failure: { status: number; error: ErrorEnvelope } } {
  const mode = gatewayAuthMode();
  if (mode === "local_operator") {
    return { ok: true, headers: { "content-type": "application/json" } };
  }
  return {
    ok: false,
    failure: unavailable(
      "no_forwardable_credential",
      "MYPA_GATEWAY_AUTH_MODE is 'entra', so the gateway requires a bearer token, and " +
        "this tier's current server-side session carries none. The request is refused " +
        "rather than sent unauthenticated or with a fabricated token.",
    ),
  };
}

function problemToError(problem: DecodedProblem, fallbackStatus: number): {
  status: number;
  error: ErrorEnvelope;
} {
  const errorClass = ERROR_CLASS[problem.code] ?? "unavailable";
  return {
    status: httpStatusForProblem(problem.code) ?? ERROR_STATUS[errorClass] ?? fallbackStatus,
    error: {
      errorClass,
      code: problem.code,
      message: problem.message,
      ...(problem.correlationId ? { correlationId: problem.correlationId } : {}),
    },
  };
}

function logDecodeFailure(
  capability: GatewayCapability,
  code: string,
  correlationId?: string,
): void {
  console.error({ capability, code, ...(correlationId ? { correlationId } : {}) });
}

/**
 * Transport to the Python gateway: config, fetch, JSON parse, envelope XOR
 * problem. Not generic. Not the authority path for routes or RSC.
 *
 * WP05 mutation admission order lives in routes, not here:
 * Origin → Principal → body. Side effects happen in routes. Decoding happens
 * AFTER upstream returns.
 *
 * Every refusal on the way — a misconfigured deployment, a missing credential, a
 * gateway that did not answer, an answer that was not the contract's shape — is
 * returned as a typed error rather than thrown, so a route handler cannot
 * accidentally turn one into an empty success.
 */
export async function callGateway(
  principal: PrincipalSession,
  capability: GatewayCapability,
  payload: Record<string, unknown> = {},
): Promise<GatewayOutcome<unknown>> {
  assertServerContext();

  let base: string;
  let headers: Record<string, string>;
  try {
    base = gatewayBaseUrl();
    const resolved = requestHeaders();
    if (!resolved.ok) return { ok: false, ...resolved.failure };
    headers = resolved.headers;
  } catch (error) {
    return {
      ok: false,
      ...unavailable(
        "gateway_not_configured",
        error instanceof Error ? error.message : "the gateway is not configured",
      ),
    };
  }

  let document: Record<string, unknown>;
  try {
    document = await buildRequestDocument(principal, capability, payload);
  } catch (error) {
    return {
      ok: false,
      status: 400,
      error: {
        errorClass: "validation",
        code: "caller_supplied_principal",
        message: error instanceof Error ? error.message : "the payload was refused",
      },
    };
  }

  let response: Response;
  try {
    response = await fetch(`${base}/v1/${capability}`, {
      method: "POST",
      headers,
      body: JSON.stringify(document),
      cache: "no-store",
      signal: AbortSignal.timeout(GATEWAY_TIMEOUT_MS),
    });
  } catch {
    // Deliberately no detail from the thrown error: a DNS or connect failure
    // renders the address this deployment was configured with.
    return {
      ok: false,
      ...unavailable("gateway_unreachable", "the application gateway did not answer"),
    };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return {
      ok: false,
      ...unavailable("gateway_response_unreadable", "the gateway answered with unreadable content"),
    };
  }

  const decoded = decodeEnvelope(body);
  if (!decoded.ok) {
    return { ok: false, ...unavailable(decoded.code, decoded.message) };
  }
  if (decoded.value.kind === "problem") {
    return { ok: false, ...problemToError(decoded.value.problem, response.status) };
  }
  return {
    ok: true,
    result: decoded.value.result,
    disclosure: decoded.value.disclosure,
  };
}

/**
 * The only authority path for routes and RSC. Transport plus the capability
 * decoder selected from the registry. The result type is the capability's
 * decoded contract, not a caller-supplied generic.
 *
 * WP05 mutation admission order lives in routes, not here:
 * Origin → Principal → body. Side effects happen in routes. Decoding happens
 * AFTER upstream returns.
 */
export async function invokeGateway<C extends GatewayCapability>(
  principal: PrincipalSession,
  capability: C,
  payload: Record<string, unknown> = {},
): Promise<GatewayOutcome<CapabilityResults[C]>> {
  const outcome = await callGateway(principal, capability, payload);
  if (!outcome.ok) return outcome;
  const decoded = decodeCapability(capability, outcome.result);
  if (!decoded.ok) {
    logDecodeFailure(capability, "upstream_contract_invalid");
    return {
      ok: false,
      status: 503,
      error: {
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
        message: "the gateway result did not match the capability contract",
      },
    };
  }
  return { ok: true, result: decoded.value, disclosure: outcome.disclosure };
}

/** Coverage states the Python contract treats as a genuinely partial answer. */
const PARTIAL_COVERAGE = new Set([
  "partially_processed",
  "quarantined",
  "unsupported",
  "stale",
  "superseded",
]);

/** Trust levels, mapped onto the authority the web disclosure publishes. */
const AUTHORITY = {
  source_original: "accepted",
  source_bound_derived: "derived",
  model_proposed: "proposed",
} as const satisfies Record<PythonDisclosure["trust"]["level"], DisclosureEnvelope["authority"]>;

/**
 * The web disclosure for a real backend answer.
 *
 * Every field is read off what the gateway actually disclosed. Required fields
 * are present after decode; missing coverage or trust cannot reach here and
 * cannot be defaulted to complete or `"derived"`. Nothing here can produce
 * `coverage: "synthetic"` or `authority: "synthetic_fixture"` — those two
 * values belong to `lib/fixtures` and are unreachable from this module, which is
 * what makes "a backend-served route never carries a synthetic disclosure" a
 * structural property rather than a convention.
 */
export function backendDisclosure(
  scope: string,
  disclosure: PythonDisclosure,
  extraLimitations: readonly string[] = [],
): DisclosureEnvelope {
  const state = disclosure.coverage.state;
  const truncated = disclosure.truncation.is_truncated;
  const coverage: DisclosureEnvelope["coverage"] =
    state === "unavailable"
      ? "unavailable"
      : disclosure.partial_result || PARTIAL_COVERAGE.has(state) || truncated
        ? "partial"
        : "complete";
  return {
    scope,
    coverage,
    freshnessAt: disclosure.freshness.observed_at,
    authority: AUTHORITY[disclosure.trust.level],
    limitations: [...disclosure.limitations, ...extraLimitations],
    truncated,
    ...(typeof disclosure.truncation.next_cursor === "string"
      ? { nextCursor: disclosure.truncation.next_cursor }
      : {}),
  };
}

/**
 * The limitations every backend answer carries beyond the gateway's own.
 *
 * One today, and it is the local-operator disclosure. It is computed rather than
 * constant so that a deployment which later forwards a real credential stops
 * carrying a sentence that would then be false.
 */
export function transportLimitations(): readonly string[] {
  try {
    return gatewayAuthMode() === "local_operator" ? [LOCAL_OPERATOR_LIMITATION] : [];
  } catch {
    return [];
  }
}
