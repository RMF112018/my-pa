/**
 * Shared words for the Issue views (record lineage S3 contract section 7.6).
 *
 * Every state is said in words, never by colour alone, and nothing here counts
 * anything the server did not return. Record links go only to views that exist
 * and need no further context: a Task, a Commitment, a Meeting and an Issue. A
 * Constraint and a note version are named in text.
 */
import Link from "next/link";
import type { LineageCompleteness, RecordRefView } from "@/lib/api/decode/capabilities/records.lineage";

/** The messages of section 7.6. None states a count. */
export const ISSUE_MESSAGES = {
  restricted: "Some related records or evidence are hidden by your access.",
  restart: "Your access changed. Start again.",
  truncated: "Only part of this Issue's lineage is shown.",
  partialTimeline: "Changes to related records are not shown for an earlier point in time.",
  partialLineage: "Some related records could not be shown.",
  partialFields: "Field values were not recorded for this change",
  unavailable: "This Issue is unavailable.",
  notAvailable: "Issues are not available.",
} as const;

export function words(value: string): string {
  return value.replaceAll("_", " ");
}

/** S3.1 section 8: the words for a fact's provenance label, never a colour alone. */
export const PROVENANCE_WORDS = {
  user_confirmed: "user confirmed",
  client_identified: "identified by a connected client (unreviewed)",
  userDirected: "user said they directed it (not verified)",
} as const;

/** A fact's basis in words, with the client's unverified claim when it made one. */
export function basisWords(fact: {
  readonly acceptance_basis: "user_confirmed" | "client_identified";
  readonly user_directed_claim: boolean;
}): string {
  const basis = PROVENANCE_WORDS[fact.acceptance_basis];
  return fact.user_directed_claim ? `${basis}; ${PROVENANCE_WORDS.userDirected}` : basis;
}

export const FAMILY_WORDS: Readonly<Record<RecordRefView["family"], string>> = {
  situation: "an Issue",
  meeting: "a Meeting",
  meeting_note_version: "a Meeting note version",
  task: "a Task",
  commitment: "a Commitment",
  constraint: "a Constraint",
  capture_version: "a Capture version",
};

const FAMILY_NAMES: Readonly<Record<RecordRefView["family"], string>> = {
  situation: "Issue",
  meeting: "Meeting",
  meeting_note_version: "Meeting note version",
  task: "Task",
  commitment: "Commitment",
  constraint: "Constraint",
  capture_version: "Capture version",
};

export function familyName(family: RecordRefView["family"]): string {
  return FAMILY_NAMES[family];
}

/** The view a record opens in, or `null` when it is named in text. */
export function recordHref(ref: RecordRefView): string | null {
  const id = encodeURIComponent(ref.record_id);
  switch (ref.family) {
    case "task": return `/work/tasks/${id}`;
    case "commitment": return `/work/commitments/${id}`;
    case "meeting": return `/work/meetings/${id}`;
    case "situation": return `/work/issues/${id}`;
    default: return null;
  }
}

/** "Task tsk_…" as a link where its view exists, else as text. */
export function RecordName({ value, label }: { readonly value: RecordRefView; readonly label?: string }) {
  const text = label ?? `${familyName(value.family)} ${value.record_id}`;
  const href = recordHref(value);
  return href === null
    ? <span className="break-all">{text}</span>
    : <Link href={href} className="break-all underline underline-offset-2">{text}</Link>;
}

const INSTANT = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium", timeStyle: "short", timeZone: "UTC",
});

/** A server instant, said in UTC so every reader sees one time. */
export function instantWords(value: string): string {
  return `${INSTANT.format(new Date(value))} UTC`;
}

/** The completeness messages of one answer, in precedence order, each once. */
export function completenessMessages(
  qualifiers: readonly LineageCompleteness[],
  partial: string,
): readonly { readonly code: LineageCompleteness; readonly text: string }[] {
  const text: Partial<Record<LineageCompleteness, string>> = {
    scope_changed_restart_required: ISSUE_MESSAGES.restart,
    truncated_budget: ISSUE_MESSAGES.truncated,
    restricted_evidence: ISSUE_MESSAGES.restricted,
    partial_native_history: partial,
  };
  return qualifiers.flatMap((code) => (text[code] === undefined ? [] : [{ code, text: text[code]! }]));
}
