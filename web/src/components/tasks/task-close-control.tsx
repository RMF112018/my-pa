"use client";

/**
 * Terminal Task actions (WP-TUX-03).
 *
 * Close and Cancel are distinct terminal actions, never ordinary Status choices,
 * and there is no Reopen. Closing costs at most two activations — `Close Task`
 * then `Confirm Closed` — and never asks for authored text, so no software
 * keyboard is ever summoned by closing a Task.
 *
 * Boundaries: presentational. No fetch, no mutation/idempotency/retry logic; the
 * component only invokes the callbacks it is given. Product language comes from
 * `@/lib/tasks/presentation`, never from hand-typed copy.
 *
 * The confirmation is an inline `role="alertdialog"` region rather than a modal
 * dialog: this renders inside an existing Radix Sheet, and a nested focus trap
 * is fragile. The inline region is the deliberate choice.
 *
 * While `pending` is true and confirmation is open, the confirmation stays
 * mounted and interaction-atomic: Keep open and Escape cannot dismiss it,
 * terminal triggers cannot switch intent, and Confirm cannot dispatch twice.
 * Success unmount is the parent's job after the Task is terminal.
 */

import type * as React from "react";
import { useCallback, useId, useLayoutEffect, useRef, useState } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import {
  TASK_CANCEL_ACTION_LABEL,
  TASK_CANCEL_CONFIRM_LABEL,
  TASK_CLOSE_ACTION_LABEL,
  TASK_CLOSE_CONFIRM_LABEL,
} from "@/lib/tasks/presentation";

/** Dismissal copy, shared by both confirmations: neither terminal action is taken. */
const KEEP_OPEN_LABEL = "Keep open";

const TOUCH_TARGET = "min-h-11 min-w-11";

const CLOSING_STATUS = "Closing\u2026";
const CANCELLING_STATUS = "Cancelling\u2026";

type TerminalIntent = "close" | "cancel";

export type TaskCloseControlMode = "default" | "cancel-only";

export interface TaskCloseControlProps {
  taskTitle: string;
  /** True only when a canonical current version is held. */
  disabled?: boolean;
  pending?: boolean;
  /** Hide Cancel where a surface has no room for it. Defaults to true. */
  showCancel?: boolean;
  /**
   * `"default"` is Close plus optional Cancel (`showCancel`).
   * `"cancel-only"` hides Close so a compact surface can own Cancel alone.
   */
  readonly mode?: TaskCloseControlMode;
  /**
   * Appearance of the Close *trigger* only (WP-POSTUX-03).
   *
   * A surface that mounts this control inside an already-prominent row may need
   * a quieter trigger. Nothing else is configurable: the two-step confirmation,
   * its `alertdialog` semantics and its button variants are fixed. Defaults to
   * `"primary"`, which is exactly today's rendering.
   */
  readonly triggerVariant?: ButtonProps["variant"];
  onClose(): void;
  onCancelTask(): void;
}

export function TaskCloseControl({
  taskTitle,
  disabled = false,
  pending = false,
  showCancel = true,
  mode = "default",
  triggerVariant = "primary",
  onClose,
  onCancelTask,
}: TaskCloseControlProps): React.JSX.Element {
  const [intent, setIntent] = useState<TerminalIntent | null>(null);
  /** Which trigger a dismissal owes focus back to. */
  const restoreFocusRef = useRef<TerminalIntent | null>(null);
  const closeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const cancelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const keepOpenRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const pendingStatusRef = useRef<HTMLParagraphElement | null>(null);
  const prevPendingRef = useRef(pending);
  const submittedRef = useRef(false);
  const baseId = useId();

  const confirmationLocked = pending && intent !== null;
  const showCloseTrigger = mode !== "cancel-only";
  const showCancelTrigger = mode === "cancel-only" || showCancel;

  /**
   * Focus follows the confirmation: opening (not pending) lands on Keep open,
   * pending moves to the status target before Confirm disables, failure returns
   * to Confirm, and dismissal returns to the trigger that opened it.
   */
  useLayoutEffect(() => {
    const wasPending = prevPendingRef.current;
    prevPendingRef.current = pending;
    if (wasPending && !pending) submittedRef.current = false;

    if (intent !== null) {
      if (pending) {
        pendingStatusRef.current?.focus();
        return;
      }
      if (wasPending) {
        confirmRef.current?.focus();
        return;
      }
      keepOpenRef.current?.focus();
      return;
    }
    const dismissed = restoreFocusRef.current;
    if (dismissed === null) return;
    restoreFocusRef.current = null;
    const trigger = dismissed === "close" ? closeTriggerRef.current : cancelTriggerRef.current;
    trigger?.focus();
  }, [intent, pending]);

  const dismiss = useCallback((dismissed: TerminalIntent) => {
    if (pending) return;
    restoreFocusRef.current = dismissed;
    setIntent(null);
  }, [pending]);

  useLayoutEffect(() => {
    if (intent === null) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (pending) return;
      dismiss(intent);
    };
    document.addEventListener("keydown", onEscape, true);
    return () => document.removeEventListener("keydown", onEscape, true);
  }, [intent, pending, dismiss]);

  useLayoutEffect(() => {
    const node = pendingStatusRef.current;
    return () => {
      if (node && document.activeElement === node) node.blur();
    };
  }, [pending, intent]);

  const setOpenIntent = useCallback(
    (next: TerminalIntent) => {
      if (disabled || confirmationLocked) return;
      setIntent(next);
    },
    [disabled, confirmationLocked],
  );

  const closing = intent === "close";
  const titleId = `${baseId}-title`;
  const descriptionId = `${baseId}-description`;

  return (
    <div
      data-testid={mode === "cancel-only" ? "task-cancel-control" : "task-close-control"}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        {showCloseTrigger ? (
          <Button
            ref={closeTriggerRef}
            variant={triggerVariant}
            disabled={disabled || confirmationLocked}
            data-prominence="primary"
            data-testid="task-close-trigger"
            className={TOUCH_TARGET}
            aria-expanded={intent === "close"}
            onClick={() => {
              setOpenIntent("close");
            }}
          >
            {TASK_CLOSE_ACTION_LABEL}
          </Button>
        ) : null}
        {showCancelTrigger ? (
          <Button
            ref={cancelTriggerRef}
            variant="ghost"
            disabled={disabled || confirmationLocked}
            data-prominence="secondary"
            data-testid="task-cancel-trigger"
            className={TOUCH_TARGET}
            aria-expanded={intent === "cancel"}
            onClick={() => {
              setOpenIntent("cancel");
            }}
          >
            {TASK_CANCEL_ACTION_LABEL}
          </Button>
        ) : null}
      </div>
      {intent === null ? null : (
        <div
          role="alertdialog"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          data-testid={`task-${intent}-confirmation`}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            if (pending) return;
            dismiss(intent);
          }}
          className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3"
        >
          <p id={titleId} className="text-sm font-medium text-text-primary">
            {closing ? TASK_CLOSE_ACTION_LABEL : TASK_CANCEL_ACTION_LABEL}
          </p>
          <p id={descriptionId} className="text-sm text-text-secondary">
            {closing
              ? `\u201C${taskTitle}\u201D will be closed.`
              : `\u201C${taskTitle}\u201D will be cancelled, not closed.`}
          </p>
          {pending ? (
            <p
              ref={pendingStatusRef}
              tabIndex={-1}
              role="status"
              aria-live="polite"
              aria-atomic="true"
              data-testid="task-close-pending-status"
              className="text-sm text-text-secondary"
            >
              {closing ? CLOSING_STATUS : CANCELLING_STATUS}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              ref={keepOpenRef}
              variant="secondary"
              disabled={pending}
              className={TOUCH_TARGET}
              data-testid={`task-${intent}-keep-open`}
              onClick={() => dismiss(intent)}
            >
              {KEEP_OPEN_LABEL}
            </Button>
            <Button
              ref={confirmRef}
              variant="danger"
              pending={pending}
              className={TOUCH_TARGET}
              data-testid={`task-${intent}-confirm`}
              onClick={() => {
                if (pending || submittedRef.current) return;
                submittedRef.current = true;
                if (closing) onClose();
                else onCancelTask();
              }}
            >
              {closing ? TASK_CLOSE_CONFIRM_LABEL : TASK_CANCEL_CONFIRM_LABEL}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
