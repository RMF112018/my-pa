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
 * **Limitations are allowlisted, like `code`.** The backend's "what is missing
 * from this answer" list is product truth, and it stays out of `SafeDiagnostic`
 * for the reason it always did: it is a list, not a field, and it keeps its own
 * whole-list policy gate. What changed is the instrument. It was governed by a
 * prose-shape check, on the stated premise that "the set of things an answer
 * can fail to cover is open by nature". That premise was false:
 * `application/disclosure.py` publishes `class Limitation(StrEnum)`, a closed
 * vocabulary of unbroken snake_case tokens rendered verbatim here, and the
 * shape check's run-length rule withheld eight of its thirteen tokens because
 * each token is one long "word". The field is now governed by an allowlist of
 * the values that can actually reach it — see {@link BACKEND_LIMITATIONS} — which
 * restores the disclosure and is genuinely closed, which the shape check never
 * was. This is not the rejected "trust the callsite" design: it checks the
 * value that arrived against a set of values, and asserts nothing about who
 * sent it.
 */
import type { ErrorEnvelope } from "@/contracts/envelope";
import { ERROR_CODES } from "@/lib/api/decode/problem";

/**
 * Phantom brands: `declare const`, with no runtime footprint.
 *
 * These were real `Symbol()` values until the RSC boundary disproved the premise
 * they rested on. The claim was that React's Flight serialiser skips symbol keys
 * the way `JSON.stringify` does. It does not: Flight *rejects* them, and every
 * server-rendered surface that passed a branded record to a client component
 * logged `Objects with symbol properties like SafeLimitations are not
 * supported`. The brand has to be erased to cross that boundary.
 *
 * Erasing it costs nothing the type system was providing. A `declare const`
 * phantom is still a `unique symbol` at compile time, so a plain `string` is
 * still not assignable (`TS2322`) and a structural object literal is still
 * missing a property it cannot name (`TS2741`) — the two edits the brand exists
 * to make impossible. What is lost is the *runtime* answer to "has this been
 * through a constructor?", which {@link isSafeDiagnostic} needs for idempotence.
 * That is replaced by {@link SAFE_MARKER} plus full re-validation of every
 * field, which is strictly stronger than the symbol test was: the symbol test
 * asked only whether a key was present and trusted whatever was under it,
 * whereas a value that survives the new guard is inside the closed vocabulary
 * whatever minted it.
 */
declare const SAFE_DIAGNOSTIC: unique symbol;
declare const SAFE_LIMITATIONS: unique symbol;

/**
 * The plain, serialisable answer to "has this been through a constructor?".
 *
 * A string, so it crosses RSC. It is forgeable in a way a symbol was not, which
 * is why {@link isSafeDiagnostic} does not stop at it: it re-checks every field
 * against the same allowlists the constructors apply. A forged record therefore
 * either fails the guard and is re-derived, or is already indistinguishable from
 * one this module built — which is the guarantee, not a hole in it.
 */
const SAFE_MARKER = "safe_diagnostic";

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
  /** The runtime constructor mark. Plain, so it crosses the RSC boundary. */
  readonly marker: typeof SAFE_MARKER;
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

function build(parts: Omit<SafeDiagnostic, typeof SAFE_DIAGNOSTIC | "marker">): SafeDiagnostic {
  return { ...parts, marker: SAFE_MARKER } as unknown as SafeDiagnostic;
}

/**
 * Whether a value is already a member of the closed vocabulary.
 *
 * Not "does it carry the mark" but "is every field one this module would have
 * produced". The mark is the cheap first test; the field checks are what make
 * the predicate true rather than merely trusted, now that the mark is a string
 * a payload could in principle carry. Anything that fails falls through to
 * {@link safeDiagnostic}, which derives a safe record from it.
 */
export function isSafeDiagnostic(value: unknown): value is SafeDiagnostic {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.marker !== SAFE_MARKER) return false;
  if (typeof candidate.kind !== "string" || !(candidate.kind in KIND_TEXT)) return false;
  if (candidate.errorClass !== null && safeErrorClass(candidate.errorClass as string) === null) {
    return false;
  }
  if (
    candidate.code !== null &&
    candidate.code !== UNRECOGNISED_CODE &&
    !(typeof candidate.code === "string" && CODE_ALLOWLIST.has(candidate.code))
  ) {
    return false;
  }
  if (candidate.status !== null && safeStatus(candidate.status as number) === null) return false;
  if (
    candidate.reason !== null &&
    !(typeof candidate.reason === "string" && candidate.reason in REASON_TEXT)
  ) {
    return false;
  }
  if (typeof candidate.correlated !== "boolean") return false;
  return (
    candidate.note === null || (typeof candidate.note === "string" && candidate.note in NOTE_TEXT)
  );
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
 * The backend's own "what is missing" list, after the allowlist.
 *
 * Branded for the same reason `SafeDiagnostic` is: a bare `readonly string[]`
 * at the prop must not compile. The brand is a phantom, so the record that
 * crosses the RSC boundary is `{ items }` and nothing else.
 */
export interface SafeLimitations {
  readonly [SAFE_LIMITATIONS]: true;
  readonly items: readonly string[];
}

/**
 * Which limitations may render, by allowlist — the same instrument as `code`.
 *
 * **What was here before, and why it was wrong.** This field was governed by a
 * prose-shape check: an ordinary-punctuation character class, a 280-character
 * ceiling, and no space-delimited run longer than 32. That rule was designed on
 * the premise that a backend limitation is free prose, and the premise is
 * false. `application/disclosure.py` defines `class Limitation(StrEnum)` — a
 * closed vocabulary of unbroken snake_case tokens rendered verbatim by this
 * tier, with no token-to-prose translation anywhere in between. Each token is
 * therefore one "word", and the run-length rule withheld every token longer
 * than 32 characters: eight of the thirteen, including
 * `corpus_totals_are_sums_of_per_enrollment_statements` (51) and
 * `evidence_spans_carry_offsets_and_digests_only` (45). With diagnostics on,
 * "what is missing from this answer" said a limitation had been withheld
 * instead of saying what was missing — a product-truth regression, on the
 * majority of the vocabulary.
 *
 * **Why an allowlist is the better instrument, not merely a wider one.** The
 * shape check was never closed: it was a statement about punctuation, so its
 * admitted set was unbounded and every value in it was a value nobody had
 * reviewed. It also could not be tuned out of its own problem — lowering the
 * run-length bound withheld more real tokens, and raising it admitted longer
 * unreviewed runs. An allowlist is closed by construction, so it removes the
 * regression and closes the residual-leak question at once: a 32-character hex
 * session id, `AKIAIOSFODNN7EXAMPLE`, `sk_live_4eC39HqLyjWDarjt`,
 * `db-prod-01.internal.example.com` and `/var/lib/mypa/secrets/app.key` are not
 * withheld because of a threshold, they are withheld because they are not in
 * the set. No threshold is left to tune.
 *
 * **Why this is not the callsite-trust bypass that was rejected.** The earlier
 * design rejected "distinguish front-end literals from backend free text",
 * because that rests the guarantee on a callsite's claim about itself. This
 * does not: it is a set of *values*, checked against the value that arrived. A
 * callsite gains nothing by asserting anything.
 *
 * The three admitted families:
 *
 * 1. {@link BACKEND_LIMITATIONS} — the Python `Limitation` StrEnum, verbatim.
 * 2. {@link AGGREGATE_LIMITATION_REASONS} joined to an integer count, the shape
 *    `AggregateLimitation.disclosure` builds in
 *    `domain/extraction/coverage.py`. An allowlisted reason, one colon, digits.
 * 3. {@link WEB_LIMITATIONS} plus the two closed token vocabularies this tier
 *    decodes for itself — sentences and tokens authored *in this repository*,
 *    defined here so that the allowlist is their definition site and cannot
 *    drift from their callsites.
 *
 * Drift against the Python enum is the one risk an allowlist carries that a
 * shape check did not: a token added upstream and not added here is withheld.
 * `limitation-allowlist.test.ts` parses `application/disclosure.py` and
 * `domain/extraction/coverage.py` and fails the suite on any divergence, so the
 * risk is a red test rather than a silently degraded disclosure.
 */
export const BACKEND_LIMITATIONS = [
  "listing_has_no_continuation_cursor",
  "text_truncated_to_requested_maximum",
  "content_truncated_at_fetch_limit",
  "no_extracted_text_in_scope",
  "scope_not_fully_extracted",
  "result_label_is_media_type_only",
  "capture_search_matches_words_as_written",
  "capture_search_covers_current_versions_only",
  "evidence_spans_carry_offsets_and_digests_only",
  "corpus_totals_are_sums_of_per_enrollment_statements",
  "corpus_covers_only_sources_this_principal_enrolled",
  "search_does_not_span_this_principals_corpus",
  "evidence_scope_was_not_searched",
] as const;

/** `LimitationReason` in `domain/extraction/coverage.py`. */
export const AGGREGATE_LIMITATION_REASONS = ["objects_omitted_containment_unproven"] as const;

/**
 * The closed token vocabularies this tier decodes for itself.
 *
 * `CONTEXT_CARD_LIMITATIONS` and `PROFILE_LIMITATIONS` in
 * `lib/api/decode/capabilities/_entity-read-helpers.ts` are already closed —
 * `decodeClosedStringArray` refuses anything outside them — and the People
 * surfaces render them through this gate. Repeated here rather than imported so
 * that a client component does not pull the entity decoder into its bundle;
 * `limitation-allowlist.test.ts` pins the two lists against each other.
 */
const WEB_DECODED_LIMITATIONS = [
  "more_aliases_than_this_card_carries",
  "more_identifiers_than_this_card_carries",
  "more_assignments_than_this_card_carries",
  "more_relationships_than_this_card_carries",
  "more_observations_than_this_card_carries",
  "no_source_has_been_observed",
  "coverage_counted_a_bounded_sample",
  "more_memories_than_this_card_carries",
  "memories_were_withheld_by_classification",
  "no_memory_has_been_recorded",
  "the_memory_plane_is_unavailable",
  "more_names_than_this_profile_carries",
  "more_addresses_than_this_profile_carries",
  "more_communication_methods_than_this_profile_carries",
  "more_participations_as_project_than_this_profile_carries",
  "more_participations_as_participant_than_this_profile_carries",
  "more_affiliations_as_person_than_this_profile_carries",
  "more_affiliations_as_organization_than_this_profile_carries",
] as const;

/**
 * Limitation sentences this tier authored, defined where they are allowlisted.
 *
 * Every one of these was previously written out at its callsite and admitted by
 * the shape check. They are defined here instead, and the callsites import
 * them, so the allowlist cannot fall out of step with the strings that reach
 * it — the failure mode the shape check made invisible and an allowlist would
 * otherwise make loud.
 *
 * `LOCAL_OPERATOR_LIMITATION` is re-exported by `lib/api/gateway.ts` under its
 * established name; it is defined here because `gateway.ts` is server-only and
 * this module is not, so the dependency can only run in this direction.
 */
export const WEB_LIMITATIONS = {
  /** `lib/api/gateway.ts` — the local_operator mode disclosure. */
  localOperator:
    "The gateway runs in local_operator mode: results belong to the deployment's single " +
    "local-operator principal and are not partitioned by browser session.",
  /** `components/people/related-records.tsx` — a truncated identity ledger page. */
  ledgerPageIsNotWholeHistory: "This page of the ledger is not the whole history.",
  /**
   * `lib/api/surface-answer.ts` and `lib/api/serving.ts` — a read that failed.
   *
   * The honest answer to "what is missing from this answer" when the read did
   * not succeed is *all of it*, and that is a sentence this tier can author
   * from what it knows. Both callsites previously put the upstream
   * `ErrorEnvelope.message` here instead — the same string the diagnostic
   * vocabulary drops, arriving on a second channel — which named a cause this
   * tier cannot establish and, once the allowlist governed the channel, turned
   * the commonest failure into the withheld notice. Neither restates the error
   * nor names a gateway: the diagnostic leg still does that, precisely, in the
   * closed vocabulary.
   */
  nothingInScopeWasRead:
    "Everything this scope would have carried. No part of it was read, so nothing here is covered.",
  /** `app/(app)/people/[entityId]` — the three companion reads that can fail alone. */
  assignmentsUnreadable: "Assignments could not be read.",
  relationshipsUnreadable: "Relationships could not be read.",
  identityHistoryUnreadable: "Identity history could not be read.",
  /** `lib/fixtures/*` — the synthetic provider labelling itself. */
  syntheticFixtureData: "Synthetic fixture data. No live sources are connected.",
  /** The synthetic provider's "this build has no capability here" reasons. */
  syntheticNoCanvasArrange: "Map arrange is not available on the synthetic provider.",
  syntheticNoRelationshipEditing:
    "Relationship editing is not available on the synthetic provider.",
  syntheticNoLibrary:
    "The synthetic provider has no Library fixture. Library reads the Python knowledge " +
    "and capture planes; run against the gateway to see it.",
  syntheticNoGoodnotes:
    "The synthetic provider has no GoodNotes fixture. GoodNotes reads the Python GoodNotes " +
    "plane; run against the gateway to see it.",
  syntheticNoReport:
    "The synthetic provider has no report fixture. Report reads require the executable Python Intelligence plane.",
  syntheticNoSearch:
    "The synthetic provider has no federated search fixture. Federated search requires the executable Python search capabilities.",
  syntheticNoPeople:
    "People reads the Python entity plane; synthetic fixtures are not canonical entity state.",
  syntheticNoWork:
    "Work mutations and reads require the executable Python Work plane; synthetic fixtures are not canonical Task or Commitment state.",
} as const;

const LIMITATION_ALLOWLIST: ReadonlySet<string> = new Set<string>([
  ...BACKEND_LIMITATIONS,
  ...WEB_DECODED_LIMITATIONS,
  ...Object.values(WEB_LIMITATIONS),
]);

/**
 * The one parameterised family: an allowlisted reason, a colon, a count.
 *
 * Built from the reason list rather than written as a free pattern, so adding a
 * reason is the same reviewable act as adding a token. `\d+` and nothing else
 * after the colon: the count is an integer in the backend dataclass, and a
 * looser tail would make this the free-text channel the rest of the module
 * exists to close.
 */
const AGGREGATE_LIMITATION = new RegExp(
  `^(?:${AGGREGATE_LIMITATION_REASONS.join("|")}):\\d+$`,
);

/** What a limitation becomes when it is not one this build recognises. */
export const WITHHELD_LIMITATION =
  "A limitation was withheld because its text did not match the safe-disclosure shape.";

function limitationIsSafe(limitation: string): boolean {
  return LIMITATION_ALLOWLIST.has(limitation) || AGGREGATE_LIMITATION.test(limitation);
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
  return { items } as unknown as SafeLimitations;
}

/** The empty list, for the gate's off branch and for callers with nothing. */
export const NO_LIMITATIONS: SafeLimitations = safeLimitations([]);
