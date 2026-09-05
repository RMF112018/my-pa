export type ApiFailure = Error & { status?: number; code?: string; errorClass?: string; current?: unknown };

function contractFailure(message: string): ApiFailure {
  const error: ApiFailure = new Error(message);
  error.status = 503;
  error.code = "upstream_contract_invalid";
  error.errorClass = "unavailable";
  return error;
}

/** Fail closed when a required BFF collection is missing or the wrong type. */
export function requiredCollection<T>(
  value: readonly T[] | undefined | null,
  name: string,
): readonly T[] {
  if (!Array.isArray(value)) {
    throw contractFailure(`the ${name} collection was missing`);
  }
  return value;
}

export async function workRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    const error: ApiFailure = new Error(
      response.ok
        ? "the route answered with unreadable content"
        : `Request failed (${response.status})`,
    );
    error.status = response.ok ? 503 : response.status;
    error.code = response.ok ? "upstream_contract_invalid" : undefined;
    error.errorClass = response.ok ? "unavailable" : undefined;
    throw error;
  }
  if (!response.ok) {
    const envelope =
      body !== null && typeof body === "object" && !Array.isArray(body)
        ? (body as { error?: { code?: string; message?: string; errorClass?: string }; current?: unknown })
        : {};
    const error: ApiFailure = new Error(envelope.error?.message ?? `Request failed (${response.status})`);
    error.status = response.status;
    error.code = envelope.error?.code;
    error.errorClass = envelope.error?.errorClass;
    error.current = envelope.current;
    throw error;
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    const error: ApiFailure = new Error("the route success was not a contract object");
    error.status = 503;
    error.code = "upstream_contract_invalid";
    error.errorClass = "unavailable";
    throw error;
  }
  return body as T;
}

export async function captureEvidence(note: string, purpose: string, idempotencyKey = mutationKey(purpose)): Promise<string> {
  const result = await workRequest<{ status: string; receipt?: { captureId: string } }>("/api/capture", {
    method: "POST",
    body: JSON.stringify({ text: note, idempotencyKey }),
  });
  if (result.status !== "persisted" || !result.receipt?.captureId) {
    throw new Error("The evidence note was not durably persisted; the Work mutation was not attempted.");
  }
  return result.receipt.captureId;
}

export function mutationKey(prefix: string) { return `${prefix}-${crypto.randomUUID()}`; }

/** One key per material request. Ambiguous failures keep the key; success rotates it. */
export function createAttemptKey(prefix: string) {
  let signature: string | undefined;
  let key: string | undefined;
  return {
    forPayload(payload: unknown) {
      const next = JSON.stringify(payload);
      if (next !== signature || !key) { signature = next; key = mutationKey(prefix); }
      return key;
    },
    succeeded() { signature = undefined; key = undefined; },
  };
}

/** Retryable transport failures may have applied the mutation, so their key is retained. */
export function isDefinitiveAttemptFailure(error: unknown) {
  const status = (error as { status?: number }).status;
  return status !== undefined && ![502, 503, 504].includes(status);
}

export interface BrowserWorkClock {
  readonly timezone: string;
  readonly workDate: string;
}

/** Resolve and validate the browser's IANA zone before it crosses the BFF boundary. */
export function browserWorkClock(now = new Date(), requestedTimezone?: string): BrowserWorkClock {
  const timezone = requestedTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!timezone || timezone.length > 64 || !/^[A-Za-z0-9_+\/-]+$/.test(timezone)) {
    throw new Error("The browser did not provide a usable IANA timezone.");
  }
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(now);
  } catch {
    throw new Error("The browser timezone is not recognized.");
  }
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value;
  const year = part("year");
  const month = part("month");
  const day = part("day");
  if (!year || !month || !day) throw new Error("The browser date could not be resolved.");
  return { timezone, workDate: `${year}-${month}-${day}` };
}
