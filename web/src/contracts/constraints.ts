/**
 * Constraint Management — the frontend-facing canonical projections.
 *
 * These types are a *transcription* of two authorities and an invention of
 * neither: the accepted frontend package (`12_FRONTEND_CONTRACT_TYPES`) fixes
 * the wire vocabulary the browser may consume, and the landed backend read
 * plane (`my_pa.domain.project_controls.read_models`) fixes what a read can
 * truthfully carry. Where the two differ in reach — the frontend vocabulary
 * names ten synchronisation states and the read plane can derive four — the
 * wider set is typed and the narrower set is what any fixture is allowed to
 * produce, so nothing here lets a read assert a state no read could establish.
 *
 * Three rules are load-bearing and are the reason this file exists at all
 * rather than the shapes being inlined at their use sites:
 *
 * 1. **The derived booleans are fields, never expressions.** `isOverdue`,
 *    `isDueSoon` and `inMyCourt` are computed on the Project's own calendar by
 *    the backend. A browser that recomputed them from `dueDate` and its own
 *    clock would produce a second, disagreeing answer, and the reader would
 *    have no way to tell which one the Register's counts came from. They are
 *    required booleans here so that a payload missing one is a decoding
 *    failure rather than a silent `false`.
 * 2. **`averageOpenAgeBusinessDays` and `syncHealth` are the canonical names.**
 *    `averageOpenAge` and `synchronizationHealth` are not accepted aliases, are
 *    not optional members, and are not mapped. A payload carrying only those is
 *    malformed, and `CM-FE-AC-019` is the reason.
 * 3. **`constraintCode` is text and is nullable exactly where a Draft makes it
 *    so.** It is never a number, never parsed as one, and never synthesised by
 *    this tier. `"1.10"` and `"1.1"` are two different Codes.
 */

/**
 * The seven stored lifecycle states.
 *
 * `REOPEN` is deliberately absent: it is an operation that moves a record out
 * of `CLOSED`, not a state a record can be found in.
 */
export type ConstraintLifecycle =
  | "DRAFT"
  | "IDENTIFIED"
  | "PENDING"
  | "IN_PROGRESS"
  | "ON_HOLD"
  | "CLOSED"
  | "VOID";

/** The two terminal states. `Closed` scope is both, presented distinctly. */
export const TERMINAL_CONSTRAINT_LIFECYCLES: readonly ConstraintLifecycle[] = [
  "CLOSED",
  "VOID",
] as const;

/** The four states the `open` scope admits. */
export const OPEN_CONSTRAINT_LIFECYCLES: readonly ConstraintLifecycle[] = [
  "IDENTIFIED",
  "PENDING",
  "IN_PROGRESS",
  "ON_HOLD",
] as const;

/** The three ways a Constraint party can be named. Exactly three. */
export type ConstraintPartyKind = "PRINCIPAL" | "ENTITY" | "UNRESOLVED";

/** Data quality of the record. Never a lifecycle state. */
export type ConstraintRecordQuality = "NORMAL" | "LEGACY_INCOMPLETE";

/** Why the backend says a record needs attention. Vocabulary, not derivation. */
export type ConstraintAttentionReason =
  | "LEGACY_INCOMPLETE"
  | "OPEN_SYNC_CONFLICT"
  | "DATA_QUALITY_EXCEPTION";

/**
 * The fields a normal Publish requires, as values a reader can name.
 *
 * The browser consumes these; it never infers which fields a legacy record is
 * missing by looking for nulls, because a null it can see and a field the
 * backend calls missing are not the same claim (`CM-FE-AC-098`).
 */
export type ConstraintFieldKey =
  | "project_id"
  | "category_id"
  | "constraint_code"
  | "description"
  | "date_identified"
  | "due_date"
  | "bic";

/**
 * The synchronisation vocabulary the frontend recognises.
 *
 * Ten names, of which the landed read plane can derive four — `NEVER_SYNCED`,
 * `IN_SYNC`, `DB_EXPORT_PENDING`, `CONFLICT`. The remaining six each require a
 * connector call or a live workbook comparison, which is later work; they are
 * typed so a future payload decodes, and `SYNC_STATES_READABLE_AT_THIS_HEAD`
 * below is what any fixture in this build is permitted to produce.
 */
export type ConstraintSyncState =
  | "NEVER_SYNCED"
  | "IN_SYNC"
  | "DB_EXPORT_PENDING"
  | "EXTERNAL_IMPORT_PENDING"
  | "CONFLICT"
  | "WORKBOOK_UNAVAILABLE"
  | "SCHEMA_UNSUPPORTED"
  | "PARTIAL"
  | "VERIFICATION_PENDING"
  | "VERIFICATION_FAILED";

/** The four states a read of persisted rows alone can establish at this head. */
export const SYNC_STATES_READABLE_AT_THIS_HEAD: readonly ConstraintSyncState[] = [
  "NEVER_SYNCED",
  "IN_SYNC",
  "DB_EXPORT_PENDING",
  "CONFLICT",
] as const;

/** Where a Category sits. A Category is never published or closed. */
export type ConstraintCategoryState = "ACTIVE" | "INACTIVE" | "ARCHIVED";

/**
 * One BIC or Responsible party as a reader sees it.
 *
 * `partyRefId` is filter identity; `displayLabel` is presentation text, and the
 * two are never interchanged. A `PRINCIPAL` party's identity is the closed
 * token `"principal"` — never a raw principal identifier, which this tier has
 * no business carrying. An `ENTITY` party's is its persisted `ent_` id. An
 * `UNRESOLVED` party has *no* identity, so `partyRefId` is `null` and it is
 * filterable only as the whole `"unresolved"` bucket: it has no stable
 * reference to filter by, and matching its label would be string identity
 * (`CM-FE-AC-009`).
 */
export interface ConstraintPartyRef {
  readonly kind: ConstraintPartyKind;
  readonly partyRefId: string | null;
  readonly displayLabel: string;
  readonly entityId?: string | null;
}

/** The closed identity token every PRINCIPAL party shares. Not an id. */
export const PRINCIPAL_PARTY_REF_ID = "principal";

/** The bucket an UNRESOLVED party is filterable as, having no identity of its own. */
export const UNRESOLVED_PARTY_FILTER_BUCKET = "unresolved";

/** The Category a Constraint belongs to, as much of it as a row needs. */
export interface ConstraintCategoryRef {
  readonly categoryId: string;
  readonly prefix: string;
  readonly title: string;
}

/** One Constraint Category, with the flags a safe mutation UX needs. */
export interface ConstraintCategory {
  readonly categoryId: string;
  readonly projectId: string;
  readonly prefix: string;
  readonly title: string;
  readonly description: string | null;
  readonly displayOrder: number;
  readonly state: ConstraintCategoryState;
  readonly nextSequence: number;
  readonly issuedCount: number;
  readonly version: number;
  /** Backend-published. Never inferred from whether a Register row exists. */
  readonly prefixLocked: boolean;
}

/** The Project-level synchronisation roll-up the Overview shows. */
export interface ConstraintSyncHealth {
  readonly state: ConstraintSyncState;
  readonly openConflictCount: number;
  readonly lastVerifiedAt: string | null;
}

/** What is known about one Constraint's synchronisation, from stored rows only. */
export interface ConstraintSyncSummary {
  readonly state: ConstraintSyncState;
  readonly lastVerifiedAt: string | null;
  readonly conflictCount: number;
}

/**
 * One Register row: the stored fields plus every backend-derived flag.
 *
 * `groupKeys` is this row's membership under the grouping the page was asked
 * for — one key for Category or Status, zero or many for the two party
 * groupings — and is never a reason to render the row twice.
 */
export interface ConstraintListEntry {
  readonly constraintId: string;
  readonly projectId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly category: ConstraintCategoryRef | null;
  readonly status: ConstraintLifecycle | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly bic: readonly ConstraintPartyRef[];
  readonly responsible: readonly ConstraintPartyRef[];
  readonly reference: string | null;
  readonly daysElapsed: number | null;
  readonly version: number;
  readonly updatedAt: string;
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly recordQuality: ConstraintRecordQuality;
  readonly needsAttention: boolean;
  readonly syncState: ConstraintSyncState;
  readonly groupKeys: readonly string[];
}

/** How a CLOSED Constraint was closed. Both stay null for a legacy row. */
export interface ConstraintCompletion {
  readonly completionDate: string | null;
  readonly closureCommentary: string | null;
}

/** How a VOID Constraint was voided. */
export interface ConstraintVoid {
  readonly voidedDate: string | null;
  readonly voidReason: string | null;
}

/** What this build normalised a Constraint mutation request into. */
export type ConstraintMutationOperation =
  | "CLOSE"
  | "CREATE"
  | "PUBLISH"
  | "REOPEN"
  | "TRANSITION"
  | "UPDATE"
  | "VOID";

/** Who or what asked for the mutation. */
export type ConstraintMutationActor = "PRINCIPAL" | "ASSISTANT" | "SYSTEM";

/** What became of the mutation once the backend finished interpreting it. */
export type ConstraintMutationOutcome = "APPLIED" | "NO_OP" | "REJECTED";

/**
 * One mutation receipt, projected to what a reader may see.
 *
 * Request digests, idempotency keys and correlation identifiers are stored and
 * are deliberately not members: a history entry tells a reader that a mutation
 * happened and what became of it, not what the caller sent (`CM-FE-AC-094` —
 * raw audit structure is not the primary experience).
 */
export interface ConstraintHistoryEntry {
  readonly historyId: string;
  readonly operation: ConstraintMutationOperation;
  readonly actor: ConstraintMutationActor;
  readonly outcome: ConstraintMutationOutcome;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly revisionId: string | null;
  readonly safeFailureReason: string | null;
  /**
   * Human-readable provenance, present only when the backend supplied it.
   * Never composed here from the operation and a timestamp.
   */
  readonly provenance: string | null;
}

/** Which end of a Constraint relationship the read subject is. */
export type ConstraintRelationshipDirection = "OUTGOING" | "INCOMING";

/**
 * One relationship, from the read subject's end.
 *
 * Navigation uses `relatedConstraintId` — backend relationship identity — and
 * never a match on Description or Category (`CM-FE-AC-096`).
 */
export interface ConstraintRelationship {
  readonly relationshipId: string;
  readonly relationshipType: string;
  readonly direction: ConstraintRelationshipDirection;
  readonly relatedConstraintId: string;
  readonly relatedConstraintCode: string | null;
  readonly relatedStatus: ConstraintLifecycle | null;
}

/**
 * One cited piece of evidence, as a validated reference and never as content.
 *
 * No provider payload and no workbook cell coordinate has a field here.
 */
export interface ConstraintEvidenceLink {
  readonly evidenceLinkId: string;
  readonly evidenceKind: string;
  readonly evidenceRef: string;
  readonly role: string;
  /** Whether the backend validated this reference as a safe absolute URL. */
  readonly isSafeUrl: boolean;
}

/** One Constraint in full: every list field, plus what only a detail read shows. */
export interface ConstraintView {
  readonly constraintId: string;
  readonly projectId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly category: ConstraintCategoryRef | null;
  readonly status: ConstraintLifecycle | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly bic: readonly ConstraintPartyRef[];
  readonly responsible: readonly ConstraintPartyRef[];
  readonly reference: string | null;
  readonly daysElapsed: number | null;
  readonly version: number;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly recordQuality: ConstraintRecordQuality;
  readonly needsAttention: boolean;
  readonly needsAttentionReasons: readonly ConstraintAttentionReason[];
  readonly missingFields: readonly ConstraintFieldKey[];
  readonly isPublished: boolean;
  readonly publishedAt: string | null;
  readonly currentUpdate: string | null;
  readonly completion: ConstraintCompletion | null;
  readonly void: ConstraintVoid | null;
  readonly sync: ConstraintSyncSummary;
  readonly relationships: readonly ConstraintRelationship[];
  readonly evidenceLinks: readonly ConstraintEvidenceLink[];
}

/**
 * The Project's Constraint position at one instant, on the Project's calendar.
 *
 * `averageOpenAgeBusinessDays` is `null` — never `0` — when nothing qualifies,
 * because an average of nothing is not zero. Every count here is the backend's;
 * none of them is reconstructible from a Register page, which may be partial.
 */
export interface ConstraintOverview {
  readonly projectId: string;
  readonly projectToday: string;
  readonly projectTimezone: string;
  readonly totalOpen: number;
  readonly overdue: number;
  readonly dueSoon: number;
  readonly dueSoonThrough: string;
  readonly averageOpenAgeBusinessDays: number | null;
  readonly inMyCourt: number;
  readonly onHold: number;
  readonly recentlyChanged: number;
  readonly recentlyClosed: number;
  readonly draft: number;
  readonly needsAttention: number;
  readonly syncHealth: ConstraintSyncHealth;
  readonly asOf: string;
}

/** Open counts per Category, as the backend grouped them. Not a client tally. */
export interface ConstraintCategoryOpenCount {
  readonly categoryId: string;
  readonly prefix: string;
  readonly title: string;
  readonly openCount: number;
}

/**
 * One bounded page of Register rows.
 *
 * `isTruncated` and `nextCursor` come from the backend. `totalCount` is present
 * only when the backend supplies a total; it is never inferred from the number
 * of rows loaded so far (`19` of the frontend contract package).
 */
export interface ConstraintListPage {
  readonly entries: readonly ConstraintListEntry[];
  readonly isTruncated: boolean;
  readonly nextCursor: string | null;
  readonly totalCount: number | null;
}

/** One bounded page of mutation receipts, newest first. */
export interface ConstraintHistoryPage {
  readonly entries: readonly ConstraintHistoryEntry[];
  readonly isTruncated: boolean;
  readonly nextCursor: string | null;
}

/** The four lifecycle scopes a Register page can be asked for. */
export type ConstraintListScope = "open" | "closed" | "all" | "draft";

/** How a reader wants the page grouped. */
export type ConstraintGrouping = "none" | "category" | "status" | "bic" | "responsible";

/**
 * The five orders a Register page can be asked for.
 *
 * The URL vocabulary of `02_INFORMATION_ARCHITECTURE_AND_ROUTING` §5, which
 * names `daysOpen` and `due` where the backend enum says `days_elapsed` and
 * `due_date`. The mapping is one table in the feature's URL module, not a
 * silent rename here.
 */
export type ConstraintSort = "code" | "dateIdentified" | "daysOpen" | "due" | "updated";

/** Ascending or descending. Both are supported for every sort. */
export type ConstraintSortDirection = "asc" | "desc";
