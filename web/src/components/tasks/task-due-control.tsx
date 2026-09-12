"use client";

/**
 * Compact Due control for a Task (WP-TUX-03).
 *
 * Presentation only. It emits an intent and nothing else: no fetch, no
 * mutation, no idempotency, no retry. Civil-day semantics are taken from the
 * caller's clock and turned into instants by `civilDayStartIso`, never by
 * truncating a UTC timestamp.
 *
 * There is deliberately no `Next week` choice: its product meaning is not
 * frozen, and a quick intent whose meaning is unsettled is worse than no
 * quick intent.
 */

import { useEffect, useId, useRef, useState } from "react";

import { TASK_CONFLICT_COPY } from "@/components/tasks/task-status-control";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  TASK_DUE_FIELD_LABEL,
  addCivilDays,
  civilDayStartIso,
  formatTaskDue,
  type TaskCivilClock,
} from "@/lib/tasks/presentation";

export interface TaskDueControlProps {
  /** ISO timestamp, or null when the Task has no due date. */
  readonly value: string | null;
  readonly clock: TaskCivilClock;
  readonly disabled?: boolean;
  readonly pending?: boolean;
  readonly conflict?: boolean;
  readonly compact?: boolean;
  /** `null` is an explicit clear intent, never an empty string. */
  onChange(nextIso: string | null): void;
}

export function TaskDueControl({
  value,
  clock,
  disabled = false,
  pending = false,
  conflict = false,
  compact = false,
  onChange,
}: TaskDueControlProps): React.JSX.Element {
  const baseId = useId();
  const conflictId = `${baseId}-conflict`;
  const pickerId = `${baseId}-pick`;
  const inert = disabled || pending;

  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstChoiceRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) firstChoiceRef.current?.focus();
  }, [open]);

  const due = formatTaskDue(value, clock);

  function close(returnFocus: boolean) {
    setOpen(false);
    setPicking(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function emit(nextIso: string | null) {
    onChange(nextIso);
    close(true);
  }

  return (
    <div
      data-testid="task-due-control"
      aria-busy={pending || undefined}
      className={`relative flex flex-col gap-1 ${compact ? "text-sm" : ""}`}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          close(true);
        }
      }}
    >
      <Button
        ref={triggerRef}
        variant="secondary"
        className="min-h-11 min-w-11"
        disabled={disabled}
        pending={pending}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`${TASK_DUE_FIELD_LABEL}, ${due.phrase}`}
        aria-describedby={conflict ? conflictId : undefined}
        onClick={() => {
          if (inert) return;
          setOpen((current) => {
            if (current) setPicking(false);
            return !current;
          });
        }}
      >
        <span aria-hidden="true" className="text-text-muted">
          {TASK_DUE_FIELD_LABEL}
        </span>
        <span>{due.phrase}</span>
      </Button>

      {open ? (
        <div
          role="group"
          aria-label={`${TASK_DUE_FIELD_LABEL} choices`}
          className="flex flex-col gap-1 rounded-[var(--radius-md)] border border-border-subtle bg-surface p-2"
        >
          <Button
            ref={firstChoiceRef}
            variant="ghost"
            className="min-h-11 justify-start"
            aria-current={due.tone === "today" ? "true" : undefined}
            onClick={() => {
              emit(civilDayStartIso(clock.workDate, clock.timezone));
            }}
          >
            Today
          </Button>
          <Button
            variant="ghost"
            className="min-h-11 justify-start"
            aria-current={due.tone === "tomorrow" ? "true" : undefined}
            onClick={() => {
              emit(civilDayStartIso(addCivilDays(clock.workDate, 1), clock.timezone));
            }}
          >
            Tomorrow
          </Button>
          <Button
            variant="ghost"
            className="min-h-11 justify-start"
            aria-expanded={picking}
            onClick={() => {
              setPicking(true);
            }}
          >
            Pick date
          </Button>
          {picking ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={pickerId} className="text-sm text-text-muted">
                Pick a date
              </label>
              {/* A date input opens a date picker, not a text keyboard. */}
              <Input
                id={pickerId}
                type="date"
                className="min-h-11"
                onChange={(event) => {
                  const picked = event.target.value;
                  if (!picked) return;
                  emit(civilDayStartIso(picked, clock.timezone));
                }}
              />
            </div>
          ) : null}
          {value !== null ? (
            <Button
              variant="ghost"
              className="min-h-11 justify-start"
              onClick={() => {
                emit(null);
              }}
            >
              Clear due date
            </Button>
          ) : null}
        </div>
      ) : null}

      {conflict ? (
        <p id={conflictId} className="text-sm text-destructive">
          {TASK_CONFLICT_COPY}
        </p>
      ) : null}
    </div>
  );
}
