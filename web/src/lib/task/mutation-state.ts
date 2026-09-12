/** Shared Task mutation phase / error types for WP-TUX-02. No Redux/XState. */

export type MutationPhase =
  | "idle"
  | "pending"
  | "confirmed"
  | "failed"
  | "conflict"
  | "ambiguous";

export type MutationKind =
  | "create"
  | "status"
  | "due"
  | "update"
  | "close"
  | "cancel"
  | "commentCreate";

/** Short subtypes used by the coordinator; map from HTTP/status/code. */
export type MutationErrorSubtype =
  | "validation"
  | "unauthenticated"
  | "forbidden"
  | "authority"
  | "network"
  | "gateway"
  | "backend"
  | "contract";

export interface MutationError {
  readonly subtype: MutationErrorSubtype;
  readonly message: string;
  readonly status?: number;
  readonly code?: string;
  readonly current?: unknown;
}

export interface MutationState {
  phase: MutationPhase;
  kind?: MutationKind;
  intentId?: string;
  attemptId?: string;
  idempotencyKey?: string;
  expectedVersion?: number;
  error?: MutationError;
  confirmedResult?: unknown;
  conflictCurrent?: unknown;
}

const ALLOWED: Record<MutationPhase, ReadonlySet<MutationPhase>> = {
  idle: new Set(["pending"]),
  pending: new Set(["confirmed", "failed", "conflict", "ambiguous"]),
  confirmed: new Set(["idle"]),
  failed: new Set(["idle", "pending"]),
  conflict: new Set(["idle", "pending"]),
  ambiguous: new Set(["pending", "confirmed", "failed", "conflict"]),
};

export function canTransitionMutationPhase(from: MutationPhase, to: MutationPhase): boolean {
  return ALLOWED[from].has(to);
}

export function transitionMutationPhase(from: MutationPhase, to: MutationPhase): MutationPhase {
  if (!canTransitionMutationPhase(from, to)) {
    throw new Error(`invalid mutation transition ${from} → ${to}`);
  }
  return to;
}

export function idleMutationState(): MutationState {
  return { phase: "idle" };
}

/** Classify transport/HTTP failures for mutation UX (ambiguous vs definitive). */
export function classifyMutationError(error: unknown): MutationError {
  if (error === null || error === undefined) {
    return { subtype: "network", message: "unknown mutation failure" };
  }
  if (typeof error === "object" && "subtype" in error && typeof (error as MutationError).subtype === "string") {
    return error as MutationError;
  }

  const status = (error as { status?: number }).status;
  const code = (error as { code?: string }).code;
  const message =
    error instanceof Error
      ? error.message
      : typeof (error as { message?: string }).message === "string"
        ? (error as { message: string }).message
        : "mutation failed";
  const current = (error as { current?: unknown }).current;

  if (status === undefined && (error instanceof TypeError || /network|fetch|offline|lost/i.test(message))) {
    return { subtype: "network", message, current };
  }
  if (status === 401) return { subtype: "unauthenticated", message, status, code, current };
  if (status === 403) return { subtype: "forbidden", message, status, code, current };
  if (status === 409) return { subtype: "validation", message, status, code, current };
  if (status === 422 || status === 400) return { subtype: "validation", message, status, code, current };
  if (status === 502 || status === 503 || status === 504) {
    if (code === "upstream_contract_invalid") {
      return { subtype: "contract", message, status, code, current };
    }
    return { subtype: "gateway", message, status, code, current };
  }
  if (status !== undefined && status >= 500) {
    return { subtype: "backend", message, status, code, current };
  }
  if (code === "authority_unavailable" || /authority/i.test(String(code ?? ""))) {
    return { subtype: "authority", message, status, code, current };
  }
  return { subtype: "backend", message, status, code, current };
}

/** Ambiguous = may have applied; retain key/request. Network + 502/503/504 (non-contract). */
export function isAmbiguousMutationFailure(error: unknown): boolean {
  const classified = classifyMutationError(error);
  if (classified.subtype === "network") return true;
  if (classified.subtype === "gateway") return true;
  if (classified.subtype === "contract") return false;
  const status = classified.status;
  return status !== undefined && [502, 503, 504].includes(status);
}
