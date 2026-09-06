/**
 * The words this feature uses for backend values, in one place.
 *
 * Every state a reader must be able to act on has a *word* here, and the word
 * is what carries it. Tone is redundant reinforcement and never the carrier:
 * `CM-FE-AC-142` covers lifecycle, Overdue, Due Soon, Needs Attention and sync,
 * and the way to keep that true is to make it impossible to render one of them
 * without its label, which is what these tables do.
 *
 * Nothing here decides anything. A label is chosen by a value the backend sent;
 * no function in this file inspects a date, a clock or a party name.
 */
import type {
  ConstraintAttentionReason,
  ConstraintFieldKey,
  ConstraintLifecycle,
  ConstraintMutationOperation,
  ConstraintPartyRef,
  ConstraintRecordQuality,
  ConstraintSyncState,
} from "@/contracts/constraints";

type Tone = "neutral" | "green" | "gold" | "coral" | "synthetic";

/**
 * Lifecycle labels, including the one for a stored `null`.
 *
 * A legacy record whose lifecycle the backend permits to be absent renders as
 * "Status unavailable — legacy record", never as IDENTIFIED. Mapping an absent
 * state onto the first real one would be this tier asserting a lifecycle
 * nobody recorded (`CM-FE-AC-099`).
 */
const LIFECYCLE_LABELS: Record<ConstraintLifecycle, string> = {
  DRAFT: "Draft",
  IDENTIFIED: "Identified",
  PENDING: "Pending",
  IN_PROGRESS: "In progress",
  ON_HOLD: "On hold",
  CLOSED: "Closed",
  VOID: "Void",
};

export const LIFECYCLE_UNAVAILABLE_LABEL = "Status unavailable — legacy record";

export function lifecycleLabel(status: ConstraintLifecycle | null): string {
  return status === null ? LIFECYCLE_UNAVAILABLE_LABEL : LIFECYCLE_LABELS[status];
}

/** Closed and Void are both terminal and are never shown as one thing. */
export function lifecycleTone(status: ConstraintLifecycle | null): Tone {
  switch (status) {
    case null:
      return "gold";
    case "DRAFT":
      return "synthetic";
    case "ON_HOLD":
      return "gold";
    case "CLOSED":
      return "green";
    case "VOID":
      return "coral";
    default:
      return "neutral";
  }
}

const SYNC_LABELS: Record<ConstraintSyncState, string> = {
  NEVER_SYNCED: "Never synchronised",
  IN_SYNC: "In sync",
  DB_EXPORT_PENDING: "Excel update pending",
  EXTERNAL_IMPORT_PENDING: "External import pending",
  CONFLICT: "Sync conflict",
  WORKBOOK_UNAVAILABLE: "Workbook unavailable",
  SCHEMA_UNSUPPORTED: "Workbook schema unsupported",
  PARTIAL: "Partially synchronised",
  VERIFICATION_PENDING: "Verification pending",
  VERIFICATION_FAILED: "Verification failed",
};

export function syncLabel(state: ConstraintSyncState): string {
  return SYNC_LABELS[state];
}

/**
 * Whether a sync state is worth a reader's attention in a Register row.
 *
 * `IN_SYNC` is not, and neither is `DB_EXPORT_PENDING` at row level: a pending
 * Excel export says nothing about whether the canonical save succeeded, and
 * putting a warning on every row would teach readers to ignore the column
 * (`CM-FE-AC-031`, `CM-FE-AC-018`).
 */
export function isSyncException(state: ConstraintSyncState): boolean {
  return state !== "IN_SYNC" && state !== "DB_EXPORT_PENDING" && state !== "NEVER_SYNCED";
}

const ATTENTION_REASON_LABELS: Record<ConstraintAttentionReason, string> = {
  LEGACY_INCOMPLETE: "Legacy record imported without every required field",
  OPEN_SYNC_CONFLICT: "An open synchronisation conflict",
  DATA_QUALITY_EXCEPTION: "A data quality exception recorded by the backend",
};

export function attentionReasonLabel(reason: ConstraintAttentionReason): string {
  return ATTENTION_REASON_LABELS[reason];
}

const FIELD_LABELS: Record<ConstraintFieldKey, string> = {
  project_id: "Project",
  category_id: "Category",
  constraint_code: "Constraint Code",
  description: "Description",
  date_identified: "Date Identified",
  due_date: "Due Date",
  bic: "Ball in Court",
};

export function fieldLabel(field: ConstraintFieldKey): string {
  return FIELD_LABELS[field];
}

export const LEGACY_CALLOUT_TITLE = "Legacy record — needs review";

export const LEGACY_CALLOUT_BODY =
  "This record was imported from the legacy Constraints Log and may not contain every field " +
  "required for newly published Constraints.";

export function recordQualityLabel(quality: ConstraintRecordQuality): string {
  return quality === "LEGACY_INCOMPLETE" ? LEGACY_CALLOUT_TITLE : "Current record";
}

const OPERATION_LABELS: Record<ConstraintMutationOperation, string> = {
  CREATE: "Created",
  PUBLISH: "Published",
  UPDATE: "Updated",
  TRANSITION: "Status changed",
  CLOSE: "Closed",
  REOPEN: "Reopened",
  VOID: "Voided",
};

export function operationLabel(operation: ConstraintMutationOperation): string {
  return OPERATION_LABELS[operation];
}

/**
 * What a Draft shows where a Code would be.
 *
 * Never a placeholder, never a prefix plus the next sequence, never anything a
 * reader could mistake for an issued number. The frontend does not create,
 * predict or reserve a Code (`CM-FE-AC-032`).
 */
export const DRAFT_CODE_LABEL = "Draft — no Constraint number yet";

/** The Code as a reader sees it: the stored text, or the Draft wording. */
export function codeLabel(code: string | null): string {
  return code ?? DRAFT_CODE_LABEL;
}

/**
 * A party list as one readable string, plus the count for a screen reader.
 *
 * An empty list is "Not recorded" and never an invented party.
 */
export function partyLabel(parties: readonly ConstraintPartyRef[]): string {
  if (parties.length === 0) return "Not recorded";
  return parties.map((party) => party.displayLabel).join(", ");
}

/** A stored date, shown as stored. Formatting is presentational only. */
export function dateLabel(value: string | null): string {
  return value ?? "Not recorded";
}

/**
 * The urgency words for one row.
 *
 * Read from `isOverdue`/`isDueSoon` and from nothing else. Both may be false,
 * and a row with a past-looking due date and `isOverdue: false` says nothing —
 * which is the correct behaviour, not a gap.
 */
export function urgencyLabels(entry: {
  readonly isOverdue: boolean;
  readonly isDueSoon: boolean;
}): readonly string[] {
  const labels: string[] = [];
  if (entry.isOverdue) labels.push("Overdue");
  if (entry.isDueSoon) labels.push("Due soon");
  return labels;
}
