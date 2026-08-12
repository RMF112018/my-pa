/**
 * Principal-bound API client.
 *
 * Every call to a my-pa API route goes through this wrapper. It refuses to
 * fire without an established session context, never attaches identity
 * fields to payloads (the session cookie is the only identity carrier),
 * and rejects payloads that try to smuggle identity fields in.
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
}

/**
 * POST JSON to an app API route. Throws `NoSessionError` when called
 * without a session context; throws `CallerSuppliedPrincipalError` when
 * the payload carries identity fields.
 */
export async function apiPost<T>(
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
export async function apiGet<T>(ctx: ApiClientContext, path: string): Promise<ApiResult<T>> {
  if (!ctx.hasSession) throw new NoSessionError();
  const response = await fetch(path, { method: "GET", credentials: "same-origin" });
  return toResult<T>(response);
}

async function toResult<T>(response: Response): Promise<ApiResult<T>> {
  let data: T | null = null;
  let error: string | null = null;
  let errorClass: ErrorEnvelope["errorClass"] | null = null;
  try {
    const body = (await response.json()) as unknown;
    if (response.ok) {
      data = body as T;
    } else {
      const maybe = body as { error?: { message?: string; errorClass?: string } };
      error = maybe?.error?.message ?? `request failed with status ${response.status}`;
      errorClass = KNOWN_ERROR_CLASSES.has(maybe?.error?.errorClass ?? "")
        ? (maybe!.error!.errorClass as ErrorEnvelope["errorClass"])
        : null;
    }
  } catch {
    error = response.ok ? "response was not valid JSON" : `request failed with status ${response.status}`;
  }
  return { ok: response.ok, status: response.status, data, error, errorClass };
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
