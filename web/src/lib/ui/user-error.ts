/**
 * Typed Level-1 presentation for BFF/client failures.
 *
 * **WP08-RT-F010.** `diagnostic` used to be a raw transport string — this
 * docstring used to say so — and it was rendered verbatim into the DOM. It is
 * now a `SafeDiagnostic`: a closed record built by
 * `lib/diagnostics/safe-detail.ts`, which is also where the classification that
 * picks the sentence below now lives. The product language is unchanged; only
 * the diagnostic leg changed. Mapping still never produces an empty-record
 * claim: a failed read is still a failed read.
 */
import {
  classifyFailure,
  safeDiagnostic,
  type FailureFields,
  type FailureInput,
  type SafeDiagnostic,
  type SafeDiagnosticKind,
} from "@/lib/diagnostics/safe-detail";

/** The nine answers. Owned by `safe-detail.ts`, which decides which one applies. */
export type UserErrorKind = SafeDiagnosticKind;

export type UserErrorAction = "sign_in" | "retry" | "none";

export interface UserErrorPresentation {
  readonly kind: UserErrorKind;
  readonly title: string;
  readonly message: string;
  readonly action: UserErrorAction;
  /** The closed vocabulary. Never a string, and never upstream prose. */
  readonly diagnostic: SafeDiagnostic;
}

export type UserErrorFields = FailureFields;
export type UserErrorInput = FailureInput;

/** The Level-1 copy for each of the nine. This is product truth, not diagnostics. */
interface UserErrorCopy {
  readonly title: string;
  readonly message: string;
  readonly action: UserErrorAction;
}

const COPY: Record<UserErrorKind, UserErrorCopy> = {
  offline: {
    title: "You appear to be offline",
    message: "You appear to be offline.",
    action: "retry",
  },
  session_ended: {
    title: "Your session has ended",
    message: "Your session has ended. Sign in again.",
    action: "sign_in",
  },
  session_unverified: {
    title: "We couldn't verify your session",
    message: "We couldn't verify your session.",
    action: "retry",
  },
  forbidden: {
    title: "You don't have access",
    message: "You don't have access to this item.",
    action: "none",
  },
  not_found: {
    title: "This item could not be found",
    message: "This item could not be found.",
    action: "none",
  },
  conflict: {
    title: "This was changed elsewhere",
    message: "This was changed elsewhere. Refresh and try again.",
    action: "retry",
  },
  validation: {
    title: "That request was not valid",
    message: "That request was not valid.",
    action: "none",
  },
  internal: {
    title: "This could not be completed",
    message: "This could not be completed. Try again.",
    action: "retry",
  },
  unavailable: {
    title: "This could not be read",
    message: "This could not be read. Try again.",
    action: "retry",
  },
};

/**
 * The sentence, the heading and the affordance for one of the nine.
 *
 * Exported so `SurfaceState` can render Level-1 copy from a `SafeDiagnostic`
 * without being handed the raw failure a second time.
 */
export function userErrorCopy(kind: UserErrorKind): UserErrorCopy {
  return COPY[kind];
}

/**
 * Map a transport/BFF failure to a typed user-facing sentence.
 *
 * Status and `errorClass` win over a generic message. A 403/authorization
 * sentence is used only when those establish a refusal. Offline is never
 * reported as an empty record. The ordering lives in `classifyFailure`.
 */
export function mapUserError(input: UserErrorInput): UserErrorPresentation {
  const kind = classifyFailure(input);
  return { kind, ...COPY[kind], diagnostic: safeDiagnostic(input) };
}
