/**
 * Principal-bound API client.
 *
 * Every call to a my-pa API route goes through this wrapper. It refuses to
 * fire without an established session context, never attaches identity
 * fields to payloads (the session cookie is the only identity carrier),
 * and rejects payloads that try to smuggle identity fields in.
 */
import { rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";

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
  try {
    const body = (await response.json()) as unknown;
    if (response.ok) {
      data = body as T;
    } else {
      const maybe = body as { error?: { message?: string } };
      error = maybe?.error?.message ?? `request failed with status ${response.status}`;
    }
  } catch {
    error = response.ok ? "response was not valid JSON" : `request failed with status ${response.status}`;
  }
  return { ok: response.ok, status: response.status, data, error };
}
