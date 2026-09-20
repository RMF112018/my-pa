/**
 * What a diagnostic is allowed to *be*, as opposed to when it is allowed to show.
 *
 * **The gap this closes.** WP07 built one policy that decides *whether*
 * engineering detail renders. It never decided *what* that detail contains.
 * `lib/diagnostics/presentation.ts` was a set of pass-through filters
 * (`return enabled ? error : undefined`), `lib/ui/user-error.ts` deliberately
 * put raw transport text in its `diagnostic` field — its own docstring said
 * "Raw transport strings stay in `diagnostic`" — and
 * `components/ui/diagnostics-details.tsx` rendered that string verbatim into the
 * DOM. With diagnostics on, an arbitrary backend string reached the page. That
 * is not a claim that a secret is present in any current runtime error; it is
 * the observation that the boundary was not *safe by construction* against one
 * — a session id, a bearer token, a PEM block, a raw exception, a connection
 * string with a password in it — if one ever appeared upstream.
 *
 * **The shape of the fix.** A diagnostic is no longer a string. It is a closed
 * record, and the only way to obtain one is to call a constructor in this
 * module. Every field is a closed union, an integer constrained to a known
 * range, or a string checked against an explicit allowlist. Nothing that fails
 * a check is passed through: it is dropped, or replaced by a sentinel that says
 * a value was withheld. The display text is rendered *here*, from those fields,
 * so no caller can supply prose and no upstream string can become prose.
 *
 * **Why an allowlist and not a filter.** A deny-list of secret shapes is a
 * statement about the secrets someone thought of. An allowlist is a statement
 * about the values this tier understands, and an unrecognised value degrades to
 * a sentinel rather than leaking. That matters most for `code`: the web
 * `ErrorEnvelope` types it as a plain `string`, `decodeProblem` copies whatever
 * the gateway sent into it, and this tier mints codes of its own beyond the
 * eleven in the Python contract. An incomplete allowlist therefore costs a
 * reader a code name; a missing allowlist would cost them a secret.
 *
 * **`message` is not in the vocabulary at all.** It is the single field with no
 * shape, no schema and no upstream guarantee. `ErrorEnvelope` calls it
 * "human-safe" but nothing enforces that, and it is where a raw exception or a
 * driver's connection string arrives when one arrives. It is dropped. What a
 * reader loses is prose; what they keep is the class, the code, the status and
 * the correlation fact — which is what an engineer actually acts on. The raw
 * message is still written to the server log by `lib/api/gateway.ts`, where it
 * has always belonged.
 *
 * **`correlationId` is deliberately not carried, only acknowledged.**
 * `lib/api/gateway.ts` derives `prn_` plus 32 lowercase hex characters from the
 * verified principal's durable UUID and sends it as the request's
 * `principal_id`; `problemToError` then copies the gateway's returned
 * `correlation_id` straight into the envelope. Rendering that unvalidated puts
 * a principal-identifying value in the DOM, which is precisely the class of
 * value this module exists to keep out — and a reader cannot act on the
 * identifier from the page anyway, because the thing they would correlate it
 * against is the server log that already holds it. So the vocabulary carries
 * the *fact* (`correlated`), not the identifier. A shape check (`prn_[0-9a-f]{32}`)
 * was considered and rejected: it would admit the well-formed case, which is
 * exactly the case that identifies the principal.
 *
 * **Limitations are governed as a whole and stay out of the vocabulary.** The
 * backend's "what is missing from this answer" list is product truth — the
 * reason `SurfaceState` and `DegradedBanner` exist is to say what an answer did
 * not cover, and the set of things an answer can fail to cover is open by
 * nature. A closed vocabulary cannot express it without destroying it, so
 * folding limitations into `SafeDiagnostic` was rejected. They instead keep
 * their existing whole-list policy gate and gain a *positive shape* check:
 * a limitation must look like a short prose sentence, or it is withheld and
 * said to have been withheld. Distinguishing front-end literals (safe by
 * authorship) from backend free text was considered and rejected too — it would
 * rest the guarantee on a callsite's claim about itself rather than on the
 * value, and the front-end literals pass the shape check anyway, so the
 * distinction would buy nothing and cost a bypass.
 */
import type { ErrorEnvelope } from "@/contracts/envelope";
import { ERROR_CODES } from "@/lib/api/decode/problem";

/**
 * Real symbols, not `declare const` phantoms.
 *
 * A type-only brand is erased, so nothing at runtime could answer "has this
 * already been through a constructor?" — and `diagnosticError` would then
 * re-derive a value that was already safe. A symbol key is skipped by
 * `JSON.stringify` and by React's Flight serialiser, so it costs nothing in the
 * payload and buys idempotence and a runtime check.
 */
const SAFE_DIAGNOSTIC: unique symbol = Symbol("SafeDiagnostic");
const SAFE_LIMITATIONS: unique symbol = Symbol("SafeLimitations");

/** The eight `ErrorEnvelope` classes. A closed union in the contract already. */
export type SafeErrorClass = ErrorEnvelope["errorClass"];

const SAFE_ERROR_CLASSES: readonly SafeErrorClass[] = [
  "validation",
  "authentication",
  "authorization",
  "not_found",
  "conflict",
  "policy_denied",
  "unavailable",
  "internal",
];

/**
 * Codes this tier will name in the DOM: the eleven the Python contract defines,
 * plus the ones the web tier mints for envelopes it builds itself.
 *
 * Anything else becomes {@link UNRECOGNISED_CODE}. Adding a code here is a
 * deliberate act with a reviewable diff; forgetting to add one is a legible
 * sentinel in the UI, not a leak.
 */
export const SAFE_ERROR_CODES = [
  ...ERROR_CODES,
  "authority_unavailable",
  "bad_request",
  "caller_supplied_principal",
  "capture_conflict",
  "constraint_not_in_project",
  "coverage_unavailable",
  "cross_site_request",
  "data_provider_not_usable",
  "empty_capture",
  "gateway_unreachable",
  "invalid_expected_version",
  "invalid_identifier",
  "invalid_replay_binding",
  "misconfigured",
  "missing_enrollment",
  "missing_evidence_refs",
  "missing_idempotency_key",
  "missing_subject",
  "no_forwardable_credential",
  "not_implemented",
  "pulse_read_failed",
  "replay_session_changed",
  "request_cancelled",
  "transport_unavailable",
  "unauthenticated",
  "unknown_capture_kind",
  "unsupported_field",
  "upstream_contract_invalid",
  "upstream_error",
] as const;

export type SafeErrorCode = (typeof SAFE_ERROR_CODES)[number];

/** What a code becomes when it is not one this tier recognises. */
export const UNRECOGNISED_CODE = "unrecognised_code";

const CODE_ALLOWLIST: ReadonlySet<string> = new Set(SAFE_ERROR_CODES);

/**
 * The nine answers a failure can be, as product language classifies it.
 *
 * This lives here rather than in `lib/ui/user-error.ts` because it is the
 * closed part: a shape decision over status, class and code that yields one of
 * nine literals. `user-error.ts` keeps what is genuinely its own — the title,
 * the sentence and the affordance each kind is shown with.
 */
export type SafeDiagnosticKind =
  | "session_ended"
  | "session_unverified"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "offline"
  | "unavailable"
  | "validation"
  | "internal";

/**
 * Why a failure was classified, when no envelope field said so.
 *
 * These are conclusions drawn from matching a pattern, never the text that
 * matched. The text does not survive the match.
 */
export type SafeDiagnosticReason =
  | "network_unreachable"
  | "session_authority_unavailable"
  | "client_exception"
  | "unclassified";

/**
 * Prose this tier authored, named by a callsite and rendered from here.
 *
 * Two surfaces state something about their own read that no envelope field can
 * express — that Today's read ran and raised nothing, and that Today's read was
 * incomplete. The sentences are product-authored and were already on the
 * diagnostic prop; naming them keeps them exactly where and as they were while
 * still making "arbitrary caller string" unrepresentable.
 */
export type SafeDiagnosticNote = "today_read_raised_nothing" | "today_read_incomplete";

const NOTE_TEXT: Record<SafeDiagnosticNote, string> = {
  today_read_raised_nothing:
    "Today's Task read ran and returned no Task for this day, and the derivation ran and " +
    "raised no commitment, decision, observation or situation either.",
  today_read_incomplete:
    "The read was incomplete and carried no Task and no other row. A partial read " +
    "does not establish that nothing needs attention.",
};

/**
 * A diagnostic, as a closed record.
 *
 * The brand is not decoration: without it a structurally identical object
 * literal would be assignable, and the point of the type is that the only way
 * to hold one is to have gone through a constructor in this module. A plain
 * `string` is not assignable to it either, which is what makes a raw-string
 * callsite a compile error rather than something review has to notice.
 */
export interface SafeDiagnostic {
  readonly [SAFE_DIAGNOSTIC]: true;
  /** The classification, always present. One of nine. */
  readonly kind: SafeDiagnosticKind;
  /** One of the eight contract classes, or nothing. */
  readonly errorClass: SafeErrorClass | null;
  /** An allowlisted code, the unrecognised sentinel, or nothing. */
  readonly code: SafeErrorCode | typeof UNRECOGNISED_CODE | null;
  /** An integer HTTP status in [100, 599], or nothing. */
  readonly status: number | null;
  /** Why, when no envelope field said. */
  readonly reason: SafeDiagnosticReason | null;
  /** Whether the gateway returned a correlation id. Never the id itself. */
  readonly correlated: boolean;
  /** A note this tier authored, rendered from {@link NOTE_TEXT}. */
  readonly note: SafeDiagnosticNote | null;
}

/** The fields a failure is read down to before anything is decided about it. */
export interface FailureFields {
  readonly status?: number | null;
  readonly errorClass?: string | null;
  readonly code?: string | null;
  readonly message?: string | null;
  readonly offline?: boolean | null;
  readonly correlationId?: string | null;
}

/** Anything a callsite might have caught, thrown, decoded or been handed. */
export type FailureInput = FailureFields | ErrorEnvelope | Error | string | null | undefined | unknown;

const SESSION_AUTHORITY = /session authority unavailable/i;
const OFFLINE_TEXT =
  /failed to fetch|networkerror|load failed|you appear to be offline|the network is unavailable/i;

/**
 * Read an arbitrary caught value down to the fields this tier understands.
 *
 * Moved here from `user-error.ts` so that normalisation, classification and
 * safe construction are one thing in one place; `user-error.ts` imports it back
 * rather than keeping a second copy that could drift.
 */
export function failureFields(input: FailureInput): FailureFields {
  if (input == null) return {};
  if (typeof input === "string") return { message: input };
  if (typeof input !== "object") return { message: String(input) };
  if (input instanceof Error) {
    const failure = input as Error & FailureFields;
    return {
      status: typeof failure.status === "number" ? failure.status : null,
      errorClass: typeof failure.errorClass === "string" ? failure.errorClass : null,
      code: typeof failure.code === "string" ? failure.code : null,
      message: input.message,
      offline: failure.offline ?? null,
    };
  }
  return input as FailureFields;
}

/**
 * Which of the nine a failure is.
 *
 * Status and `errorClass` win over a generic message; a 403 sentence is used
 * only when one of those establishes a refusal; offline is never reported as an
 * empty record. This is the order `mapUserError` has always applied, unchanged.
 */
export function classifyFailure(input: FailureInput): SafeDiagnosticKind {
  const fields = failureFields(input);
  const status = fields.status ?? null;
  const errorClass = fields.errorClass ?? "";
  const code = fields.code ?? "";
  const message = fields.message ?? "";

  if (fields.offline === true || OFFLINE_TEXT.test(message)) return "offline";
  if (status === 401 || errorClass === "authentication") return "session_ended";
  if (SESSION_AUTHORITY.test(message) || code === "authority_unavailable") {
    return "session_unverified";
  }
  if (status === 403 || errorClass === "authorization" || errorClass === "policy_denied") {
    return "forbidden";
  }
  if (status === 404 || errorClass === "not_found") return "not_found";
  if (status === 409 || errorClass === "conflict") return "conflict";
  if (status === 400 || status === 422 || errorClass === "validation") return "validation";
  if (errorClass === "internal" || status === 500) return "internal";
  return "unavailable";
}

function safeErrorClass(value: string | null | undefined): SafeErrorClass | null {
  if (typeof value !== "string") return null;
  return SAFE_ERROR_CLASSES.includes(value as SafeErrorClass) ? (value as SafeErrorClass) : null;
}

function safeCode(value: string | null | undefined): SafeErrorCode | typeof UNRECOGNISED_CODE | null {
  if (typeof value !== "string" || value === "") return null;
  return CODE_ALLOWLIST.has(value) ? (value as SafeErrorCode) : UNRECOGNISED_CODE;
}

/**
 * An HTTP status, or nothing.
 *
 * Constrained to the range HTTP defines rather than to the eight this tier
 * emits, because an upstream status this tier has not seen is still a number
 * and a number carries nothing. `constraint-live.ts` uses `0` for "the plane
 * was never reached", which is not a status and is dropped.
 */
function safeStatus(value: number | null | undefined): number | null {
  if (typeof value !== "number" || !Number.isInteger(value)) return null;
  return value >= 100 && value <= 599 ? value : null;
}

function safeReason(fields: FailureFields, kind: SafeDiagnosticKind): SafeDiagnosticReason | null {
  const message = fields.message ?? "";
  if (kind === "offline") return "network_unreachable";
  if (kind === "session_unverified" && SESSION_AUTHORITY.test(message)) {
    return "session_authority_unavailable";
  }
  if (safeErrorClass(fields.errorClass) || safeStatus(fields.status) || fields.code) return null;
  return message ? "client_exception" : "unclassified";
}

function build(parts: Omit<SafeDiagnostic, typeof SAFE_DIAGNOSTIC>): SafeDiagnostic {
  return { ...parts, [SAFE_DIAGNOSTIC]: true } as SafeDiagnostic;
}

/** Whether a value has already been through a constructor in this module. */
export function isSafeDiagnostic(value: unknown): value is SafeDiagnostic {
  return typeof value === "object" && value !== null && SAFE_DIAGNOSTIC in value;
}

/**
 * The one way to turn a failure into something renderable.
 *
 * Everything that was a free string on the way in is either validated into the
 * closed vocabulary or discarded here. Nothing crosses unchecked.
 */
export function safeDiagnostic(input: FailureInput): SafeDiagnostic {
  // Idempotent: a value the owning page already governed is handed on by the
  // panels below it, and re-deriving it would read its own closed fields back
  // as if they were an upstream envelope.
  if (isSafeDiagnostic(input)) return input;
  const fields = failureFields(input);
  const kind = classifyFailure(input);
  return build({
    kind,
    errorClass: safeErrorClass(fields.errorClass),
    code: safeCode(fields.code),
    status: safeStatus(fields.status),
    reason: safeReason(fields, kind),
    correlated: typeof fields.correlationId === "string" && fields.correlationId.length > 0,
    note: null,
  });
}

/** A diagnostic that is one of this module's own sentences, named by a callsite. */
export function safeDiagnosticNote(note: SafeDiagnosticNote): SafeDiagnostic {
  return build({
    kind: "unavailable",
    errorClass: null,
    code: null,
    status: null,
    reason: null,
    correlated: false,
    note,
  });
}

const KIND_TEXT: Record<SafeDiagnosticKind, string> = {
  session_ended: "the session had ended",
  session_unverified: "the session could not be verified",
  forbidden: "the request was refused",
  not_found: "the record was not found",
  conflict: "the record had changed",
  offline: "the network could not be reached",
  unavailable: "the read did not complete",
  validation: "the request was not valid",
  internal: "the backend failed internally",
};

const REASON_TEXT: Record<SafeDiagnosticReason, string> = {
  network_unreachable: "no response was received from this device's network",
  session_authority_unavailable: "the session authority did not answer",
  client_exception: "the failure was an exception in this tier, not an answer from the backend",
  unclassified: "nothing in the failure identified what went wrong",
};

/**
 * The display text, rendered here and nowhere else.
 *
 * A caller cannot pass prose in, so a caller cannot pass a secret in. The
 * ordering is what an engineer reads first: the classification, then the
 * machine code, then the status, then whatever else is known.
 */
export function describeSafeDiagnostic(diagnostic: SafeDiagnostic): string {
  if (diagnostic.note) return NOTE_TEXT[diagnostic.note];
  const parts: string[] = [KIND_TEXT[diagnostic.kind]];
  if (diagnostic.errorClass) parts.push(`class ${diagnostic.errorClass}`);
  if (diagnostic.code === UNRECOGNISED_CODE) {
    parts.push("code withheld: the backend sent a code this build does not recognise");
  } else if (diagnostic.code) {
    parts.push(`code ${diagnostic.code}`);
  }
  if (diagnostic.status !== null) parts.push(`HTTP ${diagnostic.status}`);
  if (diagnostic.reason) parts.push(REASON_TEXT[diagnostic.reason]);
  if (diagnostic.correlated) {
    parts.push("a correlation id was returned and is in the server log, not on this page");
  }
  return `${parts.join(" · ")}.`;
}

/**
 * The backend's own "what is missing" list, after the shape check.
 *
 * Branded for the same reason `SafeDiagnostic` is: a bare `readonly string[]`
 * at the prop must not compile.
 */
export interface SafeLimitations {
  readonly [SAFE_LIMITATIONS]: true;
  readonly items: readonly string[];
}

/**
 * What a limitation is allowed to look like.
 *
 * A positive shape, not a deny-list: short, single-line, ordinary prose
 * punctuation, and no unbroken run long enough to be a token. A bearer token, a
 * base64 key body and a hex session id all fail the run-length rule; a
 * connection string fails on `@` and `//`; a stack trace fails on the newline
 * and on `<`. `LOCAL_OPERATOR_LIMITATION` and every front-end literal in the
 * tree pass unchanged.
 */
const LIMITATION_SHAPE = /^[A-Za-z0-9 ,.'’:;()/_-]{1,280}$/;
const LONGEST_WORD = 32;

/** What a limitation becomes when it does not look like one. */
export const WITHHELD_LIMITATION =
  "A limitation was withheld because its text did not match the safe-disclosure shape.";

function limitationIsSafe(limitation: string): boolean {
  if (!LIMITATION_SHAPE.test(limitation)) return false;
  return !limitation.split(" ").some((word) => word.length > LONGEST_WORD);
}

/**
 * Check a limitation list and brand it.
 *
 * Failing entries are replaced rather than dropped, because a reader being told
 * that something is missing and unprintable is true, and a reader being told
 * nothing is missing would not be.
 */
export function safeLimitations(limitations: readonly string[] | undefined): SafeLimitations {
  const items = (limitations ?? []).map((limitation) =>
    limitationIsSafe(limitation) ? limitation : WITHHELD_LIMITATION,
  );
  return { items, [SAFE_LIMITATIONS]: true } as SafeLimitations;
}

/** The empty list, for the gate's off branch and for callers with nothing. */
export const NO_LIMITATIONS: SafeLimitations = safeLimitations([]);
