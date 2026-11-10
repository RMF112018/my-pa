/**
 * Shared words for the standalone Reports views (WP07 contract U7).
 *
 * Every state is said in words, never by colour alone. A refusal is shown in
 * product language chosen from its status and code; the BFF's own message is
 * never rendered, so no field value or upstream text reaches the page. `held`
 * is shown read-only as "On hold"; there is no hold, retention or deletion
 * control anywhere in these views.
 */
import { Badge } from "@/components/ui/badge";
import type { ReportRefusal } from "@/lib/reports/client";
import { UPLOAD_STATE_UNKNOWN_MESSAGE } from "@/lib/reports/transfer-client";

export const LIFECYCLE_WORDS = {
  active: "Active",
  archived: "Archived",
  trashed: "In Trash",
} as const satisfies Record<string, string>;

export function lifecycleWords(state: string): string {
  return (LIFECYCLE_WORDS as Record<string, string>)[state] ?? state;
}

/** The read-only hold badge: the only hold datum the UI shows. */
export function HeldBadge({ held }: { held: boolean }) {
  return held ? <Badge tone="gold">On hold</Badge> : null;
}

/** A digest in short form (first 12 hex characters). */
export function shortDigest(digest: string): string {
  return digest.slice(0, 12);
}

/** An opaque id in short form: its prefix and the first eight characters after it. */
export function shortId(id: string): string {
  const separator = id.indexOf("_");
  return separator < 0 ? id.slice(0, 8) : `${id.slice(0, separator + 1)}${id.slice(separator + 1, separator + 9)}`;
}

/** An instant in words, in UTC, so a test and a reader see the same text. */
export function instantWords(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })} UTC`;
}

/** A byte count in words. */
export function byteWords(count: number): string {
  if (count < 1024) return `${count} bytes`;
  if (count < 1024 * 1024) return `${(count / 1024).toFixed(1)} KB`;
  return `${(count / (1024 * 1024)).toFixed(1)} MB`;
}

export const REPORT_MESSAGES = {
  unavailable: "Reports are unavailable right now.",
  notFound: "This report was not found.",
  signIn: "Your session has ended. Sign in again to continue.",
  denied: "You are not allowed to do that.",
  invalid: "The request was not accepted.",
  network: "The request could not be sent. Check your connection and try again.",
  unverified: "The content could not be verified, so it is not shown.",
  tooLarge: "The content is larger than 16 MB.",
  uploadStateUnknown: UPLOAD_STATE_UNKNOWN_MESSAGE,
} as const;

/** One refusal in product language. */
export function refusalWords(refused: ReportRefusal): string {
  if (refused.code === "transfer_mismatch") return REPORT_MESSAGES.unverified;
  if (refused.code === "content_too_large") return REPORT_MESSAGES.tooLarge;
  if (refused.code === "transfer_state_unknown") return REPORT_MESSAGES.uploadStateUnknown;
  if (refused.code === "transport_failed") return REPORT_MESSAGES.network;
  if (refused.status === 404 || refused.code === "not_found") return REPORT_MESSAGES.notFound;
  if (refused.status === 401) return REPORT_MESSAGES.signIn;
  if (refused.status === 403) return REPORT_MESSAGES.denied;
  if (refused.status === 400 || refused.status === 422) return REPORT_MESSAGES.invalid;
  return REPORT_MESSAGES.unavailable;
}

export const reportHref = (reportId: string) => `/reports/${encodeURIComponent(reportId)}`;
export const reportEditHref = (reportId: string) => `/reports/${encodeURIComponent(reportId)}/edit`;
export const NEW_REPORT_HREF = "/reports/new";
export const TRASH_HREF = "/reports/trash";
