"use client";

/**
 * Operational Work List Task row (WP-TUX-05).
 *
 * List layout only. The operational machinery it used to hold privately —
 * the binder call, the awaited-intent confirmation, the focus capture and
 * return, and the Status/Due/Close/conflict affordances — now lives in
 * `@/components/tasks/use-task-row-operations` and
 * `@/components/tasks/task-operation-controls`, because Board and Calendar
 * (WP-TUX-06) need the same operations and re-implementing them would stand a
 * second mutation and focus system beside this one. This file is what remains:
 * the List arrangement, its identity line, and its Comment affordance.
 *
 * Boundaries: presentation and intent only. Every write goes through the shared
 * binder `useTaskOperations` — this file contains no fetch, no idempotency key,
 * no retry and no version reconciliation, and it re-uses the landed compact
 * Status/Due/Close primitives unchanged. Comments are not re-implemented here:
 * the Comment affordance opens the existing Task Activity surface.
 *
 * The list projection is a display seed, never write authority. The binder
 * canonical-hydrates at the first versioned write and sends that version, so a
 * stale list version can never reach the server — and the list does not pay one
 * detail read per row to make its controls usable.
 */

import {
  stopPropagation,
  TaskConflictPanel,
  TaskDueOperationControl,
  TaskStatusOperationControl,
  TaskTerminalActions,
} from "@/components/tasks/task-operation-controls";
import { useTaskRowOperations } from "@/components/tasks/use-task-row-operations";
import { Button } from "@/components/ui/button";
import type { TaskRow } from "@/contracts/work";
import { formatTaskPriority, type TaskCivilClock } from "@/lib/tasks/presentation";

/** Product copy owned by this row. Everything else comes from the shared modules. */
const COMMENT_ACTION_LABEL = "Comment";

/** Test-id namespace for the shared affordances rendered in this surface. */
const ROW_TEST_ID = "task-list-row";

export interface TaskListRowProps {
  /** List projection. Seeds display only; it never authorizes a mutation. */
  task: TaskRow;
  selected: boolean;
  onSelect(taskId: string): void;
  onOpen(type: "task", id: string, title: string, trigger: HTMLElement): void;
  /**
   * Opens the Task Activity surface (comments) for this Task. When absent the
   * row falls back to opening Task detail, whose Activity section owns comments:
   * a row never grows a second comments implementation.
   */
  onOpenActivity?(taskId: string, title: string, trigger: HTMLElement): void;
  /** Fired once a mutation is confirmed by the server, for filter/focus handling. */
  onMutationConfirmed?(input: { taskId: string; kind: string }): void;
  /** Civil-day context. Defaults to the browser clock. */
  clock?: TaskCivilClock;
}

export function TaskListRow({
  task,
  selected,
  onSelect,
  onOpen,
  onOpenActivity,
  onMutationConfirmed,
  clock,
}: TaskListRowProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLDivElement>({
    taskId: task.task_id,
    task,
    clock,
    onMutationConfirmed,
  });
  const { ops, rowRef, busy } = operations;

  /*
    Every word the row says about this Task comes from the display base, not from
    the held snapshot. The snapshot is a reading of one moment and the row never
    remounts while it stays listed, so reading names from it pinned the title to
    whatever was true at mount: rename the Task from its own detail sheet and the
    row went on showing the old name — in its link, in every control's accessible
    name, and in the outcome spoken after a write.
  */
  const title = ops.display?.title ?? task.title;
  const priority = ops.display?.priority ?? task.priority;

  return (
    <div
      ref={rowRef}
      data-testid={ROW_TEST_ID}
      data-work-item={task.task_id}
      aria-busy={busy || undefined}
      className="flex min-w-0 flex-col gap-2 rounded-[var(--radius-md)] border border-border-subtle bg-surface p-3"
    >
      {/* Line one: selection and identity. Nothing else is clickable here. */}
      <div className="flex min-w-0 items-start gap-2">
        <span className="flex min-h-11 min-w-11 items-center justify-center">
          <input
            type="checkbox"
            className="size-5 accent-[var(--interactive)]"
            aria-label={`Select ${title}`}
            checked={selected}
            onClick={stopPropagation}
            onChange={(event) => {
              event.stopPropagation();
              onSelect(task.task_id);
            }}
          />
        </span>
        <a
          href={`/work/tasks/${encodeURIComponent(task.task_id)}`}
          data-testid="task-list-row-title"
          className="flex min-h-11 min-w-0 flex-1 items-center text-left font-medium text-text-primary focus-visible:rounded focus-visible:outline focus-visible:outline-2"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onOpen("task", task.task_id, title, event.currentTarget);
          }}
        >
          <span className="min-w-0 break-words">{title}</span>
        </a>
        {priority ? (
          <span className="hidden shrink-0 self-center text-sm text-text-muted sm:inline">
            {formatTaskPriority(priority)}
          </span>
        ) : null}
      </div>

      {/* Line two: the two inline field edits. */}
      <div className="flex min-w-0 flex-wrap items-start gap-3">
        <TaskStatusOperationControl taskTitle={title} operations={operations} />
        <TaskDueOperationControl taskTitle={title} operations={operations} />
      </div>

      {/* Line three: the action row. Comment, Close, and More (which holds Cancel). */}
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <Button
          variant="ghost"
          className="min-h-11 min-w-11"
          data-testid="task-list-row-comment"
          aria-label={`Add comment to ${title}`}
          onClick={(event) => {
            event.stopPropagation();
            const trigger = event.currentTarget;
            if (onOpenActivity) onOpenActivity(task.task_id, title, trigger);
            else onOpen("task", task.task_id, title, trigger);
          }}
        >
          {COMMENT_ACTION_LABEL}
        </Button>

        {/*
          Close and More withhold themselves once the Task is terminal — the rule
          lives with the affordance now, so every surface gets it. Rendered
          unconditionally so the disclosure keeps its state.
        */}
        <TaskTerminalActions taskTitle={title} operations={operations} testIdPrefix={ROW_TEST_ID} />
      </div>

      <TaskConflictPanel taskTitle={title} operations={operations} testIdPrefix={ROW_TEST_ID} />
    </div>
  );
}
