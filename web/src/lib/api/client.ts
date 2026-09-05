/**
 * Principal-bound API client.
 *
 * Every call to a my-pa API route goes through this wrapper. It refuses to
 * fire without an established session context, never attaches identity
 * fields to payloads (the session cookie is the only identity carrier),
 * and rejects payloads that try to smuggle identity fields in.
 *
 * Success JSON is accepted only as a non-null object. A 2xx primitive, array,
 * empty body, or unreadable payload is not treated as typed domain data.
 */
import { rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";
import type { ErrorEnvelope } from "@/contracts/envelope";

export class NoSessionError extends Error {
  constructor() {
    super("api client refused: no signed-in principal context");
  }
}

export interface ApiClientContext {
  /** True once the shell has confirmed a signed-in principal. */
  readonly hasSession: boolean;
}

export interface ApiResult<T> {
  readonly ok: boolean;
  readonly status: number;
  readonly data: T | null;
  readonly error: string | null;
  /**
   * Which *kind* of failure this was, when the route said so.
   *
   * Carried beside the message because a surface has to tell a refusal from an
   * outage before it can tell a person what to do next — "this was rejected and
   * nothing was stored" and "the backend could not be reached" call for opposite
   * actions, and a build that renders one string for both has conflated them.
   * `null` when the response carried no envelope to read it from; never guessed
   * from the status code, which is a mapping this tier owns in one place already.
   */
  readonly errorClass: ErrorEnvelope["errorClass"] | null;
  /** Stable machine code from the BFF error envelope, e.g. `rate_limited`. */
  readonly code: string | null;
}

/**
 * POST JSON to an app API route. Throws `NoSessionError` when called
 * without a session context; throws `CallerSuppliedPrincipalError` when
 * the payload carries identity fields.
 */
export async function apiPost<T = Record<string, unknown>>(
  ctx: ApiClientContext,
  path: string,
  payload: Record<string, unknown>,
): Promise<ApiResult<T>> {
  if (!ctx.hasSession) throw new NoSessionError();
  rejectCallerSuppliedPrincipal(payload);
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
  return toResult<T>(response);
}

/** GET JSON from an app API route. Same session refusal rule as `apiPost`. */
export async function apiGet<T = Record<string, unknown>>(
  ctx: ApiClientContext,
  path: string,
): Promise<ApiResult<T>> {
  if (!ctx.hasSession) throw new NoSessionError();
  const response = await fetch(path, { method: "GET", credentials: "same-origin" });
  return toResult<T>(response);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readErrorEnvelope(body: unknown): {
  message: string | undefined;
  errorClass: ErrorEnvelope["errorClass"] | null;
  code: string | null;
} {
  if (!isRecord(body) || !isRecord(body.error)) {
    return { message: undefined, errorClass: null, code: null };
  }
  const message = typeof body.error.message === "string" ? body.error.message : undefined;
  const rawClass = typeof body.error.errorClass === "string" ? body.error.errorClass : "";
  const errorClass = KNOWN_ERROR_CLASSES.has(rawClass)
    ? (rawClass as ErrorEnvelope["errorClass"])
    : null;
  const code = typeof body.error.code === "string" ? body.error.code : null;
  return { message, errorClass, code };
}

async function toResult<T>(
  response: Response,
): Promise<ApiResult<T>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return {
      ok: false,
      status: response.status,
      data: null,
      error: response.ok
        ? "the route answered with unreadable content"
        : `request failed with status ${response.status}`,
      errorClass: response.ok ? "unavailable" : null,
      code: response.ok ? "upstream_contract_invalid" : null,
    };
  }
  if (response.ok) {
    if (!isRecord(body)) {
      return {
        ok: false,
        status: 503,
        data: null,
        error: "the route success was not a contract object",
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
      };
    }
    return {
      ok: true,
      status: response.status,
      data: body as T,
      error: null,
      errorClass: null,
      code: null,
    };
  }
  const parsed = readErrorEnvelope(body);
  return {
    ok: false,
    status: response.status,
    data: null,
    error: parsed.message ?? `request failed with status ${response.status}`,
    errorClass: parsed.errorClass,
    code: parsed.code,
  };
}

/**
 * The eight classes the web contract publishes, as a membership test.
 *
 * A value not in this set is reported as `null` rather than passed through: a
 * surface branching on an unrecognised class would fall into whichever arm its
 * `else` happens to be, and here that arm decides whether a person is told their
 * note was stored.
 */
const KNOWN_ERROR_CLASSES: ReadonlySet<string> = new Set<ErrorEnvelope["errorClass"]>([
  "validation",
  "authentication",
  "authorization",
  "not_found",
  "conflict",
  "policy_denied",
  "unavailable",
  "internal",
]);
