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

/**
 * List wording for the expanded More disclosure (WP-POSTUX-03).
 *
 * The default phrase is a sentence on a line that has three other actions on
 * it; in a dense list it wraps the action band and costs a row of height. The
 * accessible name is untouched — the disclosure is still announced as
 * "More actions for <title>" — so this is visible wording only, and only here.
 */
const MORE_EXPANDED_LABEL = "Less";

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

  /*
    No per-row card chrome (WP03-AC-043). The grouped surface — one border, one
    rounding, one background for the whole list — belongs to the list container;
    a row that drew its own repeated that chrome once per Task and turned a list
    into a column of islands. What is left on the root is layout, and the
    selected fill.

    Selection is carried by `data-state="selected"`, present only when the row
    is selected (WP03-AC-051/052), and deliberately not by `aria-selected`: this
    row is not an option in a listbox, and the checkbox already states selection
    to assistive technology. The fill is a token tint, not a second card.
  */
  return (
    <div
      ref={rowRef}
      data-testid={ROW_TEST_ID}
      data-work-item={task.task_id}
      aria-busy={busy || undefined}
      data-state={selected ? "selected" : undefined}
      className="flex min-w-0 flex-col gap-1.5 px-3 py-2 data-[state=selected]:bg-interactive-subtle"
    >
      {/* Band one: selection and identity. Nothing else is clickable here. */}
      <div className="flex min-w-0 items-start gap-2">
        {/*
          A `<label>`, not a `<span>`. The 44x44 box was always here, but a bare
          span forwards no click, so the *effective* target was the 20px box the
          checkbox paints — under both this shell's 44px floor and WCAG 2.5.8's
          24px minimum. The label makes the box that was already reserved
          actually operable. The input keeps `aria-label`, which wins over an
          empty label's (absent) text, so the accessible name is unchanged.

          `stopPropagation` belongs here as well as on the input. The input
          already stopped its own clicks, but the padding is new operable area,
          and a click landing on it would otherwise reach an ancestor. Nothing
          above this row listens for clicks today, so this guards an invariant
          rather than fixing a live defect — but the invariant is exactly the
          one a future row-level open would break, silently selecting as well
          as opening.
        */}
        <label
          className="flex min-h-11 min-w-11 items-center justify-center"
          onClick={stopPropagation}
        >
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
        </label>
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
      </div>

      {/*
        Band two: what state this Task is in and how urgent it is — Priority,
        Status, Due, read together.

        Priority moved here from the identity line and lost the `sm:` gate that
        hid it on every phone width in scope (WP03-AC-049): a set Priority is
        part of the urgency reading, so withholding it exactly where the list is
        read most made the band incomplete. It is plain text, never invented
        when the Task has none, and — being a non-interactive `<span>` — it
        takes no place in the row's interactive DOM order (WP03-AC-102).
      */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {priority ? (
          <span className="shrink-0 text-sm text-text-muted">{formatTaskPriority(priority)}</span>
        ) : null}
        <TaskStatusOperationControl
          taskTitle={title}
          operations={operations}
          labelVisibility="sr-only"
        />
        <TaskDueOperationControl
          taskTitle={title}
          operations={operations}
          presentation="value-only"
        />
      </div>

      {/* Band three: the action row. Comment, Close, and More (which holds Cancel). */}
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
        <TaskTerminalActions
          taskTitle={title}
          operations={operations}
          testIdPrefix={ROW_TEST_ID}
          closeTriggerVariant="secondary"
          moreExpandedLabel={MORE_EXPANDED_LABEL}
        />
      </div>

      <TaskConflictPanel taskTitle={title} operations={operations} testIdPrefix={ROW_TEST_ID} />
    </div>
  );
}
