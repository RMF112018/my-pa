"use client";

/**
 * Operational Work List Task row (WP-TUX-05).
 *
 * List-only by design. `work-perspectives.tsx` has a single `TaskCard` shared by
 * List, Board and Calendar; Board and Calendar belong to WP-TUX-06, so putting
 * operations on that shared card would leak this package's scope into them. The
 * operational row therefore lives here and is composed into the List perspective
 * by the Work surface owner.
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

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { TaskCloseControl } from "@/components/tasks/task-close-control";
import { TaskDueControl } from "@/components/tasks/task-due-control";
import { TaskStatusControl } from "@/components/tasks/task-status-control";
import { useTaskOperations } from "@/components/tasks/use-task-operations";
import { Button } from "@/components/ui/button";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import { browserWorkClock } from "@/lib/api/work-client";
import {
  formatTaskPriority,
  type TaskActiveStatus,
  type TaskCivilClock,
} from "@/lib/tasks/presentation";

/** Product copy owned by this row. Everything else comes from the shared modules. */
const COMMENT_ACTION_LABEL = "Comment";
const MORE_ACTION_LABEL = "More";
const MORE_CLOSE_LABEL = "Hide more actions";

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
  /**
   * Fired synchronously when a mutation is dispatched, before anything moves.
   *
   * Focus handling needs the list as the user last saw it: once the write
   * confirms, reconciliation may already have removed this row, taking the
   * control that had focus with it. The ordering has to be captured while it is
   * still true.
   */
  onMutationDispatched?(input: { taskId: string; kind: string }): void;
  /** Civil-day context. Defaults to the browser clock. */
  clock?: TaskCivilClock;
}

type ConfirmKind = "status" | "due" | "close" | "cancel";

interface AwaitedConfirmation {
  readonly kind: ConfirmKind;
  satisfied(task: TaskDetail): boolean;
}

function stopPropagation(event: { stopPropagation(): void }): void {
  event.stopPropagation();
}

export function TaskListRow({
  task,
  selected,
  onSelect,
  onOpen,
  onOpenActivity,
  onMutationConfirmed,
  onMutationDispatched,
  clock,
}: TaskListRowProps): React.JSX.Element {
  const browserClock = useMemo<TaskCivilClock>(() => browserWorkClock(), []);
  const civilClock = clock ?? browserClock;
  const baseId = useId();
  const terminalRegionId = `${baseId}-terminal`;

  const [moreOpen, setMoreOpen] = useState(false);

  const ops = useTaskOperations(
    { taskId: task.task_id, task },
    {
      clock: civilClock,
      /*
        Always on-demand. A list projection is never write authority — not even
        when it carries a `version`, which is a read of some earlier moment — so
        the binder canonical-hydrates at the first versioned write and sends that
        version. Hydrating every row on mount instead would issue one detail read
        per row for a list the user may never touch.
      */
      hydrate: "on-demand",
    },
  );

  const { changeStatus, changeDue, closeTask, cancelTask } = ops;

  /* --------------------------------------------------------------- *
   * Confirmation reporting
   *
   * The binder owns the outcome; the row only needs to know that the
   * canonical Task now satisfies the intent it dispatched, so the Work
   * surface can run filter-movement and focus handling.
   * --------------------------------------------------------------- */
  const awaitingRef = useRef<AwaitedConfirmation[]>([]);
  const canonical = ops.task;

  useEffect(() => {
    if (!canonical || awaitingRef.current.length === 0) return;
    const remaining: AwaitedConfirmation[] = [];
    const confirmed: ConfirmKind[] = [];
    for (const entry of awaitingRef.current) {
      if (entry.satisfied(canonical)) confirmed.push(entry.kind);
      else remaining.push(entry);
    }
    awaitingRef.current = remaining;
    for (const kind of confirmed) {
      onMutationConfirmed?.({ taskId: canonical.task_id, kind });
    }
  }, [canonical, onMutationConfirmed]);

  const await_ = useCallback(
    (entry: AwaitedConfirmation) => {
      awaitingRef.current = [...awaitingRef.current, entry];
      onMutationDispatched?.({ taskId: task.task_id, kind: entry.kind });
    },
    [onMutationDispatched, task.task_id],
  );

  const handleStatus = useCallback(
    (next: TaskActiveStatus) => {
      await_({ kind: "status", satisfied: (current) => current.lifecycle_state === next });
      void changeStatus(next);
    },
    [await_, changeStatus],
  );

  const handleDue = useCallback(
    (nextIso: string | null) => {
      await_({ kind: "due", satisfied: (current) => (current.due_at ?? null) === nextIso });
      void changeDue(nextIso);
    },
    [await_, changeDue],
  );

  const handleClose = useCallback(() => {
    await_({ kind: "close", satisfied: (current) => current.lifecycle_state === "completed" });
    void closeTask();
  }, [await_, closeTask]);

  const handleCancel = useCallback(() => {
    await_({ kind: "cancel", satisfied: (current) => current.lifecycle_state === "cancelled" });
    void cancelTask();
  }, [await_, cancelTask]);

  const title = ops.task?.title ?? task.title;
  const priority = ops.task?.priority ?? task.priority;
  /*
    Controls stay operable before hydration. The package requires the canonical
    read before the *mutation*, not before the affordance, and the binder does
    exactly that — so gating the control on `canMutate` here would either lock a
    row forever or force an eager detail read per row to unlock it. A write is
    still blocked while one is in flight or an unresolved conflict is showing.
  */
  const locked = ops.pending !== null || ops.conflict !== null;
  const conflict = ops.conflict !== null;
  const busy = ops.pending !== null;

  return (
    <div
      data-testid="task-list-row"
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
        <div
          role="group"
          aria-label={`Change status for ${title}`}
          className="min-w-0"
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <TaskStatusControl
            compact
            value={ops.status.value}
            disabled={locked}
            pending={ops.pending === "status"}
            conflict={conflict}
            onChange={handleStatus}
          />
        </div>
        <div
          role="group"
          aria-label={`Change due date for ${title}`}
          className="min-w-0"
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <TaskDueControl
            compact
            value={ops.due.value}
            clock={civilClock}
            disabled={locked}
            pending={ops.pending === "due"}
            conflict={conflict}
            onChange={handleDue}
          />
        </div>
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

        <div
          role="group"
          id={terminalRegionId}
          aria-label={`Close ${title}`}
          className="min-w-0"
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <TaskCloseControl
            taskTitle={title}
            disabled={locked}
            pending={ops.pending === "close" || ops.pending === "cancel"}
            // Cancel is deliberately not a peer of Close in the row: it is
            // revealed only once More is activated.
            showCancel={moreOpen}
            onClose={handleClose}
            onCancelTask={handleCancel}
          />
        </div>

        <Button
          variant="ghost"
          className="min-h-11 min-w-11"
          data-testid="task-list-row-more"
          data-prominence="tertiary"
          aria-label={`More actions for ${title}`}
          aria-expanded={moreOpen}
          aria-controls={terminalRegionId}
          onClick={(event) => {
            event.stopPropagation();
            setMoreOpen((open) => !open);
          }}
        >
          {moreOpen ? MORE_CLOSE_LABEL : MORE_ACTION_LABEL}
        </Button>
      </div>
    </div>
  );
}
