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
 */

import type * as React from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  TASK_CANCEL_ACTION_LABEL,
  TASK_CANCEL_CONFIRM_LABEL,
  TASK_CLOSE_ACTION_LABEL,
  TASK_CLOSE_CONFIRM_LABEL,
} from "@/lib/tasks/presentation";

/** Dismissal copy, shared by both confirmations: neither terminal action is taken. */
const KEEP_OPEN_LABEL = "Keep open";

const TOUCH_TARGET = "min-h-11 min-w-11";

type TerminalIntent = "close" | "cancel";

export interface TaskCloseControlProps {
  taskTitle: string;
  /** True only when a canonical current version is held. */
  disabled?: boolean;
  pending?: boolean;
  /** Hide Cancel where a surface has no room for it. Defaults to true. */
  showCancel?: boolean;
  onClose(): void;
  onCancelTask(): void;
}

export function TaskCloseControl({
  taskTitle,
  disabled = false,
  pending = false,
  showCancel = true,
  onClose,
  onCancelTask,
}: TaskCloseControlProps): React.JSX.Element {
  const [intent, setIntent] = useState<TerminalIntent | null>(null);
  /** Which trigger a dismissal owes focus back to. */
  const restoreFocusRef = useRef<TerminalIntent | null>(null);
  const closeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const cancelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const keepOpenRef = useRef<HTMLButtonElement | null>(null);
  const baseId = useId();

  /**
   * Focus follows the confirmation: opening lands on the non-destructive
   * dismissal (never the terminal action), and dismissal returns focus to the
   * trigger that opened it.
   */
  useEffect(() => {
    if (intent !== null) {
      keepOpenRef.current?.focus();
      return;
    }
    const dismissed = restoreFocusRef.current;
    if (dismissed === null) return;
    restoreFocusRef.current = null;
    const trigger = dismissed === "close" ? closeTriggerRef.current : cancelTriggerRef.current;
    trigger?.focus();
  }, [intent]);

  const dismiss = useCallback((dismissed: TerminalIntent) => {
    restoreFocusRef.current = dismissed;
    setIntent(null);
  }, []);

  const closing = intent === "close";
  const titleId = `${baseId}-title`;
  const descriptionId = `${baseId}-description`;

  return (
    <div data-testid="task-close-control" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          ref={closeTriggerRef}
          variant="primary"
          disabled={disabled}
          data-prominence="primary"
          data-testid="task-close-trigger"
          className={TOUCH_TARGET}
          aria-expanded={intent === "close"}
          onClick={() => {
            if (disabled) return;
            setIntent("close");
          }}
        >
          {TASK_CLOSE_ACTION_LABEL}
        </Button>
        {showCancel ? (
          <Button
            ref={cancelTriggerRef}
            variant="ghost"
            disabled={disabled}
            data-prominence="secondary"
            data-testid="task-cancel-trigger"
            className={TOUCH_TARGET}
            aria-expanded={intent === "cancel"}
            onClick={() => {
              if (disabled) return;
              setIntent("cancel");
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
          <div className="flex flex-wrap gap-2">
            <Button
              ref={keepOpenRef}
              variant="secondary"
              className={TOUCH_TARGET}
              data-testid={`task-${intent}-keep-open`}
              onClick={() => dismiss(intent)}
            >
              {KEEP_OPEN_LABEL}
            </Button>
            <Button
              variant="danger"
              pending={pending}
              className={TOUCH_TARGET}
              data-testid={`task-${intent}-confirm`}
              onClick={() => {
                if (pending) return;
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
