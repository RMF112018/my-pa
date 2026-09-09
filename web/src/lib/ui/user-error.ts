/**
 * Typed Level-1 presentation for BFF/client failures.
 *
 * Raw transport strings stay in `diagnostic` so a surface can keep them in
 * Details without putting gateway vocabulary in the first sentence. Mapping
 * never produces an empty-record claim: a failed read is still a failed read.
 */
import type { ErrorEnvelope } from "@/contracts/envelope";

export type UserErrorKind =
  | "session_ended"
  | "session_unverified"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "offline"
  | "unavailable"
  | "validation"
  | "internal";

export type UserErrorAction = "sign_in" | "retry" | "none";

export interface UserErrorPresentation {
  readonly kind: UserErrorKind;
  readonly title: string;
  readonly message: string;
  readonly action: UserErrorAction;
  readonly diagnostic: string;
}

export interface UserErrorFields {
  readonly status?: number | null;
  readonly errorClass?: string | null;
  readonly code?: string | null;
  readonly message?: string | null;
  readonly offline?: boolean | null;
}

export type UserErrorInput = UserErrorFields | ErrorEnvelope | Error | string | null | undefined | unknown;

const SESSION_AUTHORITY = /session authority unavailable/i;
const OFFLINE_TEXT = /failed to fetch|networkerror|load failed|you appear to be offline|the network is unavailable/i;

function fieldsFrom(input: UserErrorInput): UserErrorFields {
  if (input == null) return {};
  if (typeof input === "string") return { message: input };
  if (typeof input !== "object") return { message: String(input) };
  if (input instanceof Error) {
    const failure = input as Error & UserErrorFields;
    return {
      status: typeof failure.status === "number" ? failure.status : null,
      errorClass: typeof failure.errorClass === "string" ? failure.errorClass : null,
      code: typeof failure.code === "string" ? failure.code : null,
      message: input.message,
      offline: failure.offline ?? null,
    };
  }
  return input;
}

function present(
  kind: UserErrorKind,
  title: string,
  message: string,
  action: UserErrorAction,
  diagnostic: string,
): UserErrorPresentation {
  return { kind, title, message, action, diagnostic };
}

/**
 * Map a transport/BFF failure to a typed user-facing sentence.
 *
 * Status and `errorClass` win over a generic message. A 403/authorization
 * sentence is used only when those establish a refusal. Offline is never
 * reported as an empty record.
 */
export function mapUserError(input: UserErrorInput): UserErrorPresentation {
  const fields = fieldsFrom(input);
  const diagnostic =
    (typeof fields.message === "string" && fields.message.trim()) ||
    (fields.code ? fields.code : "") ||
    (fields.errorClass ? fields.errorClass : "") ||
    (typeof fields.status === "number" ? `request failed with status ${fields.status}` : "unavailable");
  const status = fields.status ?? null;
  const errorClass = fields.errorClass ?? "";
  const code = fields.code ?? "";
  const message = fields.message ?? "";

  if (fields.offline === true || OFFLINE_TEXT.test(message)) {
    return present(
      "offline",
      "You appear to be offline",
      "You appear to be offline.",
      "retry",
      diagnostic,
    );
  }

  if (status === 401 || errorClass === "authentication") {
    return present(
      "session_ended",
      "Your session has ended",
      "Your session has ended. Sign in again.",
      "sign_in",
      diagnostic,
    );
  }

  if (SESSION_AUTHORITY.test(message) || code === "authority_unavailable") {
    return present(
      "session_unverified",
      "We couldn't verify your session",
      "We couldn't verify your session.",
      "retry",
      diagnostic,
    );
  }

  if (status === 403 || errorClass === "authorization" || errorClass === "policy_denied") {
    return present(
      "forbidden",
      "You don't have access",
      "You don't have access to this item.",
      "none",
      diagnostic,
    );
  }

  if (status === 404 || errorClass === "not_found") {
    return present(
      "not_found",
      "This item could not be found",
      "This item could not be found.",
      "none",
      diagnostic,
    );
  }

  if (status === 409 || errorClass === "conflict") {
    return present(
      "conflict",
      "This was changed elsewhere",
      "This was changed elsewhere. Refresh and try again.",
      "retry",
      diagnostic,
    );
  }

  if (status === 400 || status === 422 || errorClass === "validation") {
    return present(
      "validation",
      "That request was not valid",
      "That request was not valid.",
      "none",
      diagnostic,
    );
  }

  if (errorClass === "internal" || status === 500) {
    return present(
      "internal",
      "This could not be completed",
      "This could not be completed. Try again.",
      "retry",
      diagnostic,
    );
  }

  return present(
    "unavailable",
    "This could not be read",
    "This could not be read. Try again.",
    "retry",
    diagnostic,
  );
}
