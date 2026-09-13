"use client";

/**
 * Compact Status control for a Task (WP-TUX-03).
 *
 * Presentation only. It emits an intent and nothing else: no fetch, no
 * idempotency key, no retry, no version reconciliation. The caller owns the
 * mutation and tells this control whether it holds a canonical current
 * version (`disabled`) and whether that version has drifted (`conflict`).
 *
 * Product language comes solely from `@/lib/tasks/presentation`; backend
 * tokens such as `in_progress` are never rendered or used as an accessible
 * name.
 */

import { useId } from "react";

import { Select } from "@/components/ui/select";
import type { TaskLifecycle } from "@/contracts/work";
import {
  TASK_ACTIVE_STATUSES,
  TASK_STATUS_FIELD_LABEL,
  TASK_STATUS_LABELS,
  formatTaskStatus,
  isTerminalTaskStatus,
  type TaskActiveStatus,
} from "@/lib/tasks/presentation";

/** Concise, frozen conflict vocabulary shared by the compact Task controls. */
export const TASK_CONFLICT_COPY =
  "This task changed elsewhere. Review the latest version before saving.";

export interface TaskStatusControlProps {
  readonly value: TaskLifecycle;
  /** True whenever no canonical current version is held. */
  readonly disabled?: boolean;
  readonly pending?: boolean;
  readonly conflict?: boolean;
  readonly compact?: boolean;
  readonly id?: string;
  onChange(next: TaskActiveStatus): void;
}

export function TaskStatusControl({
  value,
  disabled = false,
  pending = false,
  conflict = false,
  compact = false,
  id,
  onChange,
}: TaskStatusControlProps): React.JSX.Element {
  const generatedId = useId();
  const controlId = id ?? `${generatedId}-status`;
  const conflictId = `${controlId}-conflict`;
  const terminal = isTerminalTaskStatus(value);

  const conflictNote = conflict ? (
    <p id={conflictId} className="text-sm text-destructive">
      {TASK_CONFLICT_COPY}
    </p>
  ) : null;

  if (terminal) {
    // Closure and cancellation are distinct terminal actions, not ordinary
    // Status choices, so there is nothing to edit here. The terminal state is
    // stated in words rather than carried by colour alone.
    return (
      <div
        data-testid="task-status-control"
        data-terminal="true"
        aria-busy={pending || undefined}
        className={`flex flex-col gap-1 ${compact ? "text-sm" : ""}`}
      >
        <span className="text-sm text-text-muted">{TASK_STATUS_FIELD_LABEL}</span>
        <span className="min-h-11 inline-flex items-center text-sm font-medium text-text-primary">
          {formatTaskStatus(value)}
        </span>
        {conflictNote}
      </div>
    );
  }

  return (
    <div
      data-testid="task-status-control"
      aria-busy={pending || undefined}
      className={`flex flex-col gap-1 ${compact ? "text-sm" : ""}`}
    >
      <label htmlFor={controlId} className="text-sm text-text-muted">
        {TASK_STATUS_FIELD_LABEL}
      </label>
      <Select
        id={controlId}
        className="min-h-11 min-w-11"
        value={value}
        disabled={disabled || pending}
        aria-describedby={conflict ? conflictId : undefined}
        onChange={(event) => {
          onChange(event.target.value as TaskActiveStatus);
        }}
      >
        {TASK_ACTIVE_STATUSES.map((state) => (
          <option key={state} value={state}>
            {TASK_STATUS_LABELS[state]}
          </option>
        ))}
      </Select>
      {conflictNote}
    </div>
  );
}
