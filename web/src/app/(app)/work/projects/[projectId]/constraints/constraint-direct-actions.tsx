"use client";

/**
 * `ConstraintDirectActions` — direct lifecycle-action operations.
 *
 * Transition, Close, Close + Follow-up, Void and Reopen. Not Publish and not
 * Edit — those are `constraint-authoring.tsx`'s (`PC-CM-UX-AC-012`: distinct
 * workflows, not one form with a mode flag).
 *
 * **Never optimistic (`PC-CM-FE-AC-066`/`074`).** This is a modal: nothing in
 * the Register or the Inspector changes while it is open, and it only closes
 * — handing control back to the caller to refresh — once the mutation has
 * actually confirmed. There is no local "assume it worked" branch anywhere in
 * this file.
 *
 * **Close is a dedicated guarded workflow, not a free-text form
 * (`PC-CM-FE-AC-064`).** Its two body fields are optional — the minimum a
 * Close ever sends is `expectedVersion` and `idempotencyKey`
 * (`PC-CM-FE-AC-065`); a completion date left blank is the backend's own
 * server date, never one this tier invents.
 *
 * **Void requires both a date and a reason, and reads as a distinct, guarded
 * action (`PC-CM-FE-AC-073`).** Reopen requires a terminal source, a named
 * active target, a reason and the record's version
 * (`PC-CM-FE-AC-075`) — the record must already be `CLOSED` or `VOID`, or this
 * dialog does not offer Reopen at all.
 *
 * **A conflict is never blindly retried (`PC-CM-FE-AC-077`).** A `409` closes
 * this dialog with a conflict notice; the caller's own re-read is what a
 * reader must look at before trying again — there is no "retry with the same
 * body" control here.
 */
import { useEffect, useState } from "react";
import type { ConstraintLifecycle, ConstraintListEntry } from "@/contracts/constraints";
import { TERMINAL_CONSTRAINT_LIFECYCLES } from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { constraintLockKey } from "@/lib/constraint/mutation-coordinator";
import type { ConstraintMutationKind } from "@/lib/constraint/mutation-coordinator";
import { codeLabel, lifecycleLabel } from "./presentation";
import { multilineCommitHandler } from "./constraint-lifecycle";
import type { ConstraintLifecycleAction } from "./constraint-inspector";
import {
  closeConstraint,
  closeFollowUpConstraint,
  mintIdempotencyKey,
  reopenConstraint,
  transitionConstraint,
  voidConstraint,
  type LiveMutationFailure,
} from "./constraint-live";

/** The five direct actions this surface owns (`edit`/`publish` belong to authoring). */
export type DirectAction = Exclude<ConstraintLifecycleAction, "edit" | "publish">;

const ACTIVE_STATES = ["identified", "pending", "in_progress", "on_hold"] as const;
type ActiveState = (typeof ACTIVE_STATES)[number];

const ACTION_TITLES: Record<DirectAction, string> = {
  transition: "Change status",
  close: "Close Constraint",
  closeWithFollowUp: "Close with a follow-up Constraint",
  void: "Void Constraint",
  reopen: "Reopen Constraint",
};

const ACTION_KIND: Record<DirectAction, ConstraintMutationKind> = {
  transition: "constraintTransition",
  close: "constraintClose",
  closeWithFollowUp: "constraintFollowUp",
  void: "constraintVoid",
  reopen: "constraintReopen",
};

export interface ConstraintDirectActionsProps {
  readonly action: DirectAction | null;
  readonly projectId: string;
  readonly entry: ConstraintListEntry | null;
  readonly expectedVersion?: number;
  readonly onClose: () => void;
  /** Called once the action confirms. `successorId` is set only by Close + Follow-up. */
  readonly onCompleted: (result: { readonly successorId?: string }) => void;
}

export function ConstraintDirectActions({
  action,
  projectId,
  entry,
  expectedVersion,
  onClose,
  onCompleted,
}: ConstraintDirectActionsProps) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const [surfaceId] = useState(() => `constraint-direct-actions:${crypto.randomUUID()}`);

  const [toState, setToState] = useState<ActiveState>("identified");
  const [reason, setReason] = useState("");
  const [completionDate, setCompletionDate] = useState("");
  const [voidedDate, setVoidedDate] = useState("");
  const [successorDescription, setSuccessorDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A fresh dialog per action/record: nothing carries over from the last one
  // this instance showed. Derived during render (tracking the prior
  // action/record identity) rather than a `useEffect` setState cascade.
  const [tracked, setTracked] = useState<{ readonly action: DirectAction | null; readonly constraintId: string | undefined }>({
    action,
    constraintId: entry?.constraintId,
  });
  if (tracked.action !== action || tracked.constraintId !== entry?.constraintId) {
    setTracked({ action, constraintId: entry?.constraintId });
    setToState("identified");
    setReason("");
    setCompletionDate("");
    setVoidedDate("");
    setSuccessorDescription("");
    setError(null);
  }

  useEffect(() => {
    const coordinator = runtime.mutationCoordinator;
    return () => coordinator.clearDirtyState(surfaceId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = reason.trim().length > 0 || completionDate.length > 0 || voidedDate.length > 0 || successorDescription.trim().length > 0;

  useEffect(() => {
    runtime.mutationCoordinator.reportDirtyState(surfaceId, dirty);
  }, [dirty, runtime, surfaceId]);

  if (action === null || entry === null) return null;
  // Narrowed once, and used from here on (including inside `submit`'s nested
  // closures, which TS does not otherwise narrow `entry` through).
  const record = entry;

  const reopenEligible = record.status !== null && TERMINAL_CONSTRAINT_LIFECYCLES.includes(record.status);
  const canSubmit =
    action === "void"
      ? voidedDate.length > 0 && reason.trim().length > 0
      : action === "reopen"
        ? reopenEligible && reason.trim().length > 0
        : true;

  async function submit() {
    if (pending || !canSubmit) return;
    setPending(true);
    setError(null);
    const invoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusToken = runtime.focusReturn.capture({ origin: invoker });
    const idempotencyKey = mintIdempotencyKey();

    const request: Record<string, unknown> =
      action === "transition"
        ? { toState }
        : action === "close"
          ? {
              completionDate: completionDate || undefined,
              closureCommentary: reason.trim().length > 0 ? reason : undefined,
            }
          : action === "closeWithFollowUp"
            ? {
                completionDate: completionDate || undefined,
                closureCommentary: reason.trim().length > 0 ? reason : undefined,
                successorDescription: successorDescription.trim().length > 0 ? successorDescription : undefined,
              }
            : action === "void"
              ? { voidReason: reason, voidedDate }
              : { toState, reason };

    const outcome = await runtime.mutationCoordinator.mutate({
      kind: ACTION_KIND[action as DirectAction],
      lockRequest: { kind: "constraint-record", key: constraintLockKey(record.constraintId) },
      idempotencyKey,
      expectedVersion: expectedVersion ?? record.version,
      request,
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      baseSnapshot: record,
      dispatch: async ({ request: dispatchRequest, idempotencyKey: key, expectedVersion: version }) => {
        const body: Record<string, unknown> = {
          ...(dispatchRequest as Record<string, unknown>),
          idempotencyKey: key,
          expectedVersion: version,
        };
        if (action === "transition") return transitionConstraint(projectId, record.constraintId, body);
        if (action === "close") return closeConstraint(projectId, record.constraintId, body);
        if (action === "closeWithFollowUp") return closeFollowUpConstraint(projectId, record.constraintId, body);
        if (action === "void") return voidConstraint(projectId, record.constraintId, body);
        return reopenConstraint(projectId, record.constraintId, body);
      },
      hooks: {
        feedback: async (_result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({
              eventId: `constraint-direct-${idempotencyKey}`,
              kind: "success",
              message: `${ACTION_TITLES[action as DirectAction]} completed.`,
            });
          } else if (phase === "failed") {
            feedback.publish({
              eventId: `constraint-direct-${idempotencyKey}-failed`,
              kind: "error",
              message: "The write did not complete. The record is unchanged.",
            });
          } else if (phase === "conflict") {
            feedback.publish({
              eventId: `constraint-direct-${idempotencyKey}-conflict`,
              kind: "conflict",
              message: "This record changed since it was read. Re-read it before trying again.",
            });
          } else if (phase === "ambiguous") {
            feedback.publish({
              eventId: `constraint-direct-${idempotencyKey}-ambiguous`,
              kind: "error",
              message: "The write's outcome could not be confirmed. Re-read the record before retrying.",
            });
          }
        },
        resolveFocus: () => {
          runtime.focusReturn.resolve(focusToken.tokenId);
        },
      },
    });

    setPending(false);
    if (outcome.refused) {
      setError("This record is already being written to. Wait for that write to finish.");
      return;
    }
    if (outcome.state.phase === "confirmed") {
      runtime.mutationCoordinator.clearDirtyState(surfaceId);
      const successorId =
        action === "closeWithFollowUp"
          ? (outcome.result as { successor: { constraintId: string } }).successor.constraintId
          : undefined;
      onCompleted({ successorId });
      onClose();
      return;
    }
    if (outcome.state.phase === "conflict") {
      setError(
        "This record changed since it was read. This terminal action requires a fresh review — close this dialog and reopen it against the current record.",
      );
      return;
    }
    if (outcome.state.phase === "ambiguous") {
      setError("The write's outcome could not be confirmed. Check the record before retrying.");
      return;
    }
    const failure = outcome.state.error as LiveMutationFailure | undefined;
    setError(failure?.message ?? "The write failed. The record is unchanged.");
  }

  return (
    <Dialog open onClose={onClose} title={ACTION_TITLES[action]}>
      <div className="grid gap-3">
        <p className="text-sm text-moss-slate" data-testid="direct-action-subject">
          {codeLabel(record.constraintCode)} — {lifecycleLabel(record.status)}
        </p>
        {action === "transition" ? (
          <label className="grid gap-1 text-sm">
            New status
            <Select value={toState} data-testid="direct-action-to-state" onChange={(event) => setToState(event.target.value as ActiveState)}>
              {ACTIVE_STATES.filter((state) => state.toUpperCase() !== record.status).map((state) => (
                <option key={state} value={state}>
                  {lifecycleLabel(state.toUpperCase() as ConstraintLifecycle)}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        {action === "close" || action === "closeWithFollowUp" ? (
          <>
            <label className="grid gap-1 text-sm">
              Completion date
              <Input type="date" value={completionDate} data-testid="direct-action-completion-date" onChange={(event) => setCompletionDate(event.target.value)} />
              <span className="text-xs text-muted">Leave blank to use the server&rsquo;s own date.</span>
            </label>
            <label className="grid gap-1 text-sm">
              Closure commentary
              <Textarea
                value={reason}
                data-testid="direct-action-commentary"
                onChange={(event) => setReason(event.target.value)}
                onKeyDown={multilineCommitHandler(() => void submit())}
              />
            </label>
          </>
        ) : null}
        {action === "closeWithFollowUp" ? (
          <label className="grid gap-1 text-sm">
            Follow-up description
            <Textarea
              value={successorDescription}
              data-testid="direct-action-successor-description"
              onChange={(event) => setSuccessorDescription(event.target.value)}
            />
            <span className="text-xs text-muted">
              The closed predecessor, the published successor and the relationship between them are
              all issued by the backend in one atomic operation.
            </span>
          </label>
        ) : null}
        {action === "void" ? (
          <div className="rounded-md border border-moss-coral-strong/40 bg-moss-coral-strong/5 p-2" data-testid="direct-action-void-warning">
            <p className="text-sm font-medium text-moss-coral-strong">Voiding withdraws this Constraint.</p>
            <label className="mt-2 grid gap-1 text-sm">
              Void date
              <Input type="date" value={voidedDate} data-testid="direct-action-void-date" onChange={(event) => setVoidedDate(event.target.value)} />
            </label>
            <label className="mt-2 grid gap-1 text-sm">
              Void reason
              <Textarea
                value={reason}
                data-testid="direct-action-void-reason"
                onChange={(event) => setReason(event.target.value)}
                onKeyDown={multilineCommitHandler(() => void submit())}
              />
            </label>
          </div>
        ) : null}
        {action === "reopen" ? (
          !reopenEligible ? (
            <p role="alert" className="text-sm text-moss-coral-strong" data-testid="direct-action-reopen-ineligible">
              Reopen requires a terminal (Closed or Void) record. This record is not terminal.
            </p>
          ) : (
            <>
              <label className="grid gap-1 text-sm">
                New status
                <Select value={toState} data-testid="direct-action-to-state" onChange={(event) => setToState(event.target.value as ActiveState)}>
                  {ACTIVE_STATES.map((state) => (
                    <option key={state} value={state}>
                      {lifecycleLabel(state.toUpperCase() as ConstraintLifecycle)}
                    </option>
                  ))}
                </Select>
              </label>
              <label className="grid gap-1 text-sm">
                Reason
                <Textarea
                  value={reason}
                  data-testid="direct-action-reopen-reason"
                  onChange={(event) => setReason(event.target.value)}
                  onKeyDown={multilineCommitHandler(() => void submit())}
                />
              </label>
            </>
          )
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-moss-coral-strong" data-testid="direct-action-error">
            {error}
          </p>
        ) : null}
        <Badge tone="green">Live write · never optimistic</Badge>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={action === "void" ? "danger" : "primary"}
            disabled={pending || !canSubmit}
            data-testid="direct-action-confirm"
            onClick={() => void submit()}
          >
            {pending ? "Working…" : ACTION_TITLES[action]}
          </Button>
          <Button size="sm" variant="ghost" data-testid="direct-action-cancel" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
