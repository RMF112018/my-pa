/**
 * Canonical object envelope, error envelope, evidence spans, receipts and
 * disclosure — parity with the v4.0 domain model and the Python
 * `my_pa.contracts.v1` package.
 *
 * Every durable object is principal-bound. Stable opaque IDs; immutable
 * source versions; unknown is represented, never guessed.
 */

/** Stable opaque identifier. Never a UPN, email, or display name. */
export type OpaqueId = string;

/** ISO-8601 timestamp with offset. */
export type IsoTimestamp = string;

/** The canonical object envelope every domain record travels in. */
export interface CanonicalEnvelope<T> {
  readonly id: OpaqueId;
  /** Mandatory principal binding — no record is legible across principals. */
  readonly principalId: OpaqueId;
  readonly kind: string;
  readonly version: number;
  readonly createdAt: IsoTimestamp;
  readonly body: T;
}

/** Safe error envelope. Never carries content, tokens, or another principal's data. */
export interface ErrorEnvelope {
  readonly errorClass:
    | "validation"
    | "authentication"
    | "authorization"
    | "not_found"
    | "conflict"
    | "policy_denied"
    | "unavailable"
    | "internal";
  /** Stable machine code, e.g. `principal_context_missing`. */
  readonly code: string;
  /** Human-safe message. No message bodies, tokens, or subject confirmation. */
  readonly message: string;
  readonly correlationId?: OpaqueId;
}

/** Exact character range in an immutable source version. */
export interface SourceSpan {
  readonly sourceVersionId: OpaqueId;
  readonly startOffset: number;
  readonly endOffset: number;
  /** Exact original surface text of the span. */
  readonly surfaceText: string;
}

/** Exact rectangular region of a rendered source page (e.g. PDF). */
export interface SourceRegion {
  readonly sourceVersionId: OpaqueId;
  readonly pageIndex: number;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Immutable evidence of an acceptance or transition under exact authority. */
export interface Receipt {
  readonly receiptId: OpaqueId;
  readonly principalId: OpaqueId;
  readonly subjectKind: string;
  readonly subjectId: OpaqueId;
  readonly transition: string;
  readonly policyVersion: string;
  readonly issuedAt: IsoTimestamp;
  /** What authority produced the transition (review disposition, user action…). */
  readonly authority: string;
}

/**
 * Disclosure envelope accompanying every derived answer: what was covered,
 * what was not, and under which authority.
 */
export interface DisclosureEnvelope {
  readonly scope: string;
  readonly coverage: "complete" | "partial" | "unavailable" | "synthetic";
  readonly freshnessAt: IsoTimestamp | null;
  readonly authority: "accepted" | "proposed" | "derived" | "synthetic_fixture";
  readonly limitations: readonly string[];
  readonly truncated: boolean;
}
