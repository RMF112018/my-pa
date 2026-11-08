"use client";

/**
 * The lifecycle actions of one standalone report, by state (WP07 contract U7):
 * active -> Edit, Archive, Move to Trash; archived -> Restore, Move to Trash;
 * trashed -> Restore. Each action asks for confirmation in a dialog (reason
 * optional) and is sent once with its intent's idempotency key and the
 * lifecycle revision that was loaded. The outcome is shown as a receipt.
 *
 * Conflicts (U5, Amendment A2): never retried or overwritten. A 409 whose
 * `current` revision differs from the one submitted says the report's state
 * changed (with its lifecycle state now); any other 409 says the request
 * conflicted. An ambiguous answer (lost, or 502/503/504) keeps the dialog and
 * its reason as they were, so confirming again sends the same intent with the
 * same key. Both conflicts
 * offer "Review latest", which reloads the report so the user decides again;
 * the next submission carries a NEW key (`reportIntent` rotates after a
 * definitive answer).
 */
import Link from "next/link";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { StandaloneReportReadResult } from "@/lib/api/decode/capabilities/reports.standalone";
import {
  CONFLICT_MESSAGE,
  LIFECYCLE_STALE_MESSAGE,
  changeReportLifecycle,
  classifyConflict,
  isAmbiguous,
  reportIntent,
  type LifecycleOperation,
} from "@/lib/reports/client";
import { lifecycleWords, refusalWords, reportEditHref, shortId } from "./presentation";

export const ACTION_LABELS: { readonly [O in LifecycleOperation]: string } = {
  archive: "Archive",
  delete: "Move to Trash",
  restore: "Restore",
};

const CONFIRM_TITLES: { readonly [O in LifecycleOperation]: string } = {
  archive: "Archive this report?",
  delete: "Move this report to Trash?",
  restore: "Restore this report?",
};

const CONFIRM_TEXT: { readonly [O in LifecycleOperation]: string } = {
  archive: "An archived report leaves the active list. You can restore it later.",
  delete: "The report moves to Trash. You can restore it from Trash later.",
  restore: "The report returns to the active list.",
};

/** The lifecycle actions a state offers, in order. */
export function actionsFor(state: string): readonly LifecycleOperation[] {
  if (state === "active") return ["archive", "delete"];
  if (state === "archived") return ["restore", "delete"];
  if (state === "trashed") return ["restore"];
  return [];
}

type Feedback =
  | { readonly kind: "receipt"; readonly text: string }
  | { readonly kind: "conflict"; readonly text: string }
  | { readonly kind: "error"; readonly text: string };

export function ReportLifecycleActions({
  report,
  onChanged,
}: {
  readonly report: StandaloneReportReadResult;
  /** Reload the report from the server (after a receipt, or "Review latest"). */
  readonly onChanged: () => void;
}) {
  const reasonId = useId();
  const intents = useRef({
    archive: reportIntent("report-archive"),
    delete: reportIntent("report-delete"),
    restore: reportIntent("report-restore"),
  });
  const [confirming, setConfirming] = useState<LifecycleOperation | null>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  async function submit(operation: LifecycleOperation) {
    const expectedLifecycleRevision = report.lifecycle_revision;
    const trimmed = reason.trim();
    const intent = intents.current[operation];
    const idempotencyKey = intent.keyFor({ reportId: report.report_id, operation, expectedLifecycleRevision, reason: trimmed });
    setPending(true);
    const outcome = await changeReportLifecycle(report.report_id, operation, {
      expectedLifecycleRevision,
      idempotencyKey,
      ...(trimmed ? { reason: trimmed } : {}),
    });
    intent.settle(outcome);
    setPending(false);
    if (!outcome.ok && isAmbiguous(outcome)) {
      // Kept as typed: confirming again is the same intent, so the same key.
      setFeedback({ kind: "error", text: refusalWords(outcome) });
      return;
    }
    setConfirming(null);
    setReason("");
    if (outcome.ok) {
      const result = outcome.value;
      setFeedback({
        kind: "receipt",
        text: `${ACTION_LABELS[operation]}: ${result.outcome === "no_op" ? "no change" : "done"}. Now ${lifecycleWords(result.lifecycle_state)} (lifecycle revision ${result.lifecycle_revision}). Receipt ${shortId(result.receipt.receipt_id)}${result.replayed ? " (replayed)" : ""}.`,
      });
      onChanged();
      return;
    }
    const conflict = classifyConflict(outcome, { expectedLifecycleRevision });
    if (conflict.kind === "stale") setFeedback({ kind: "conflict", text: LIFECYCLE_STALE_MESSAGE(conflict.current.lifecycleState) });
    else if (conflict.kind === "conflict") setFeedback({ kind: "conflict", text: CONFLICT_MESSAGE });
    else setFeedback({ kind: "error", text: refusalWords(outcome) });
  }

  const operations = actionsFor(report.lifecycle_state);
  return (
    <section aria-label="Report actions" className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {report.lifecycle_state === "active" ? (
          <Link
            href={reportEditHref(report.report_id)}
            className="inline-flex min-h-[var(--control-height)] items-center rounded-[var(--radius-md)] border border-interactive px-3 text-sm font-medium text-interactive"
          >
            Edit
          </Link>
        ) : null}
        {operations.map((operation) => (
          <Button
            key={operation}
            size="sm"
            variant={operation === "delete" ? "danger" : "secondary"}
            disabled={pending}
            onClick={() => { setFeedback(null); setReason(""); setConfirming(operation); }}
          >
            {ACTION_LABELS[operation]}
          </Button>
        ))}
      </div>
      {feedback && confirming === null ? (
        <div role={feedback.kind === "receipt" ? "status" : "alert"} data-testid="report-action-feedback" className="grid gap-2 text-sm">
          <p>{feedback.text}</p>
          {feedback.kind === "conflict" ? (
            <div>
              <Button size="sm" variant="secondary" onClick={() => { setFeedback(null); onChanged(); }}>Review latest</Button>
            </div>
          ) : null}
        </div>
      ) : null}
      <Dialog open={confirming !== null} onClose={() => { if (!pending) setConfirming(null); }} title={confirming ? CONFIRM_TITLES[confirming] : "Confirm"}>
        {confirming ? (
          <form
            className="grid gap-3"
            onSubmit={(event) => { event.preventDefault(); void submit(confirming); }}
          >
            <p className="text-sm">{CONFIRM_TEXT[confirming]}</p>
            <label htmlFor={reasonId} className="text-sm font-medium">Reason (optional)</label>
            <Input id={reasonId} value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} />
            {feedback?.kind === "error" ? (
              <p role="alert" data-testid="report-action-dialog-error" className="text-sm text-destructive">{feedback.text}</p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" disabled={pending} onClick={() => setConfirming(null)}>Cancel</Button>
              <Button size="sm" type="submit" variant={confirming === "delete" ? "danger" : "primary"} pending={pending}>
                {ACTION_LABELS[confirming]}
              </Button>
            </div>
          </form>
        ) : null}
      </Dialog>
    </section>
  );
}
