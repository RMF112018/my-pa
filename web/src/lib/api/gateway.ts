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
 * a bearer token is required, and **this tier holds none** — the web session
 * envelope carries `principalId`, `tid`, `oid`, `upn` and `displayName`, and
 * deliberately no credential, while `POST /api/session` implements no real
 * sign-in and refuses outright when `MYPA_AUTH_MODE` is `entra`. So the honest
 * answer in that mode is `unavailable` naming the missing piece. Minting a token,
 * or quietly falling back to the unauthenticated mode, are the two failures this
 * paragraph exists to rule out.
 *
 * **Where the request stops.** Failure is always a typed state, never an empty
 * success: a refused, unreachable, or unparseable gateway produces an
 * `ErrorEnvelope` with one of the eight `errorClass` values the web contract
 * already publishes, and `unavailable`, `not_found`, `conflict` and
 * `policy_denied` stay distinguishable rather than collapsing into "no data".
 */
import contract from "@/contracts/gateway.json";
import { rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";
import { gatewayAuthMode, gatewayBaseUrl } from "@/lib/api/gateway-config";
import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";
import type { PrincipalSession } from "@/contracts/identity";

/** A capability name this BFF is allowed to address. */
export type GatewayCapability = keyof typeof contract.capabilities;

/** The disclosure the Python contract emits, in the shape it emits it. */
export interface PythonDisclosure {
  readonly coverage: { readonly state: string };
  readonly freshness: { readonly observed_at: string; readonly state: string };
  readonly trust: { readonly level: string; readonly basis: readonly string[] };
  readonly truncation: { readonly is_truncated: boolean };
  readonly limitations: readonly string[];
  readonly partial_result: boolean;
}

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
const ERROR_CLASS: Record<string, ErrorEnvelope["errorClass"]> = {
  invalid_request: "validation",
  ambiguous_request: "validation",
  denied: "authorization",
  quarantined: "policy_denied",
  not_found: "not_found",
  conflict: "conflict",
  cancelled: "conflict",
  rate_limited: "unavailable",
  unsupported: "unavailable",
  unavailable: "unavailable",
  internal_error: "internal",
};

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
 * `entra` mode has no third branch on purpose. There is no token to forward and
 * none is created here; see the module docstring.
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
        "this tier's session carries none — no real Entra sign-in is implemented here. " +
        "The request is refused rather than sent unauthenticated or with a fabricated token.",
    ),
  };
}

function problemToError(problem: unknown, fallbackStatus: number): {
  status: number;
  error: ErrorEnvelope;
} {
  const detail = problem as {
    code?: unknown;
    message?: unknown;
    correlation_id?: unknown;
  } | null;
  const code = typeof detail?.code === "string" ? detail.code : "unavailable";
  const errorClass = ERROR_CLASS[code] ?? "unavailable";
  return {
    status: ERROR_STATUS[errorClass] ?? fallbackStatus,
    error: {
      errorClass,
      code,
      message:
        typeof detail?.message === "string" ? detail.message : "the gateway refused the request",
      ...(typeof detail?.correlation_id === "string"
        ? { correlationId: detail.correlation_id }
        : {}),
    },
  };
}

/**
 * Call one capability on the Python gateway.
 *
 * Every refusal on the way — a misconfigured deployment, a missing credential, a
 * gateway that did not answer, an answer that was not the contract's shape — is
 * returned as a typed error rather than thrown, so a route handler cannot
 * accidentally turn one into an empty success.
 */
export async function callGateway<T = Record<string, unknown>>(
  principal: PrincipalSession,
  capability: GatewayCapability,
  payload: Record<string, unknown> = {},
): Promise<GatewayOutcome<T>> {
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

  const envelope = body as {
    result?: unknown;
    disclosure?: unknown;
    error?: unknown;
    code?: unknown;
  } | null;

  // A `ProblemDetail` alone: the request never became one the application could
  // answer, so there is no envelope around it. The Python transport documents
  // this as its second response shape.
  if (envelope && envelope.error === undefined && typeof envelope.code === "string") {
    return { ok: false, ...problemToError(envelope, response.status) };
  }
  if (envelope?.error) {
    return { ok: false, ...problemToError(envelope.error, response.status) };
  }
  if (!envelope || envelope.disclosure === undefined || envelope.disclosure === null) {
    return {
      ok: false,
      ...unavailable(
        "gateway_response_uncontracted",
        "the gateway answered without the mandatory disclosure envelope",
      ),
    };
  }
  return {
    ok: true,
    result: (envelope.result ?? {}) as T,
    disclosure: envelope.disclosure as PythonDisclosure,
  };
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
const AUTHORITY: Record<string, DisclosureEnvelope["authority"]> = {
  source_original: "accepted",
  source_bound_derived: "derived",
  model_proposed: "proposed",
};

/**
 * The web disclosure for a real backend answer.
 *
 * Every field is read off what the gateway actually disclosed. Nothing here can
 * produce `coverage: "synthetic"` or `authority: "synthetic_fixture"` — those two
 * values belong to `lib/fixtures` and are unreachable from this module, which is
 * what makes "a backend-served route never carries a synthetic disclosure" a
 * structural property rather than a convention.
 */
export function backendDisclosure(
  scope: string,
  disclosure: PythonDisclosure,
  extraLimitations: readonly string[] = [],
): DisclosureEnvelope {
  const state = disclosure.coverage?.state ?? "unknown";
  const truncated = disclosure.truncation?.is_truncated === true;
  const coverage: DisclosureEnvelope["coverage"] =
    state === "unavailable"
      ? "unavailable"
      : disclosure.partial_result === true || PARTIAL_COVERAGE.has(state) || truncated
        ? "partial"
        : "complete";
  return {
    scope,
    coverage,
    freshnessAt: disclosure.freshness?.observed_at ?? null,
    authority: AUTHORITY[disclosure.trust?.level ?? ""] ?? "derived",
    limitations: [...(disclosure.limitations ?? []), ...extraLimitations],
    truncated,
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
