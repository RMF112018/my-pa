export type ApiFailure = Error & { status?: number; code?: string; errorClass?: string; current?: unknown };

export async function workRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...init, headers: { "content-type": "application/json", ...init?.headers } });
  const body = (await response.json().catch(() => ({}))) as { error?: { code?: string; message?: string; errorClass?: string }; current?: unknown };
  if (!response.ok) {
    const error: ApiFailure = new Error(body.error?.message ?? `Request failed (${response.status})`);
    error.status = response.status; error.code = body.error?.code; error.errorClass = body.error?.errorClass; error.current = body.current; throw error;
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
