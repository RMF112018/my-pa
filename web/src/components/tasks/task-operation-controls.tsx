"use client";

/**
 * The operational affordances of a Task card, shared by List, Board and
 * Calendar (WP-TUX-06).
 *
 * Extracted verbatim from the WP-TUX-05 List row. Each piece is a presentation
 * shell around the landed compact primitives — Status, Due, Close — plus the
 * group semantics, event containment and accessible names a surface would
 * otherwise have to restate. Layout is the caller's: every piece takes a
 * `className` and composes into whatever arrangement the surface wants, while
 * the semantics stay identical everywhere. Accessible names are parameterised
 * by the Task title, and test ids by a per-surface prefix, so a Board card reads
 * the same to a screen reader as the List row does.
 *
 * Intent only. Nothing here writes: the dispatchers, lock flags and focus refs
 * all come from `useTaskRowOperations`, which is the single mutation path.
 */

import { useId, useState } from "react";

import { TaskCloseControl, type TaskCloseControlProps } from "@/components/tasks/task-close-control";
import { TaskDueControl, type TaskDueControlProps } from "@/components/tasks/task-due-control";
import {
  TaskStatusControl,
  type TaskStatusControlProps,
} from "@/components/tasks/task-status-control";
import { TASK_OPERATION_CONFLICT_MESSAGE } from "@/components/tasks/use-task-operations";
import type { TaskRowOperations } from "@/components/tasks/use-task-row-operations";
import { Button } from "@/components/ui/button";

/** Product copy owned by these affordances. */
export const MORE_ACTION_LABEL = "More";
export const MORE_CLOSE_LABEL = "Hide more actions";
export const CONFLICT_REAPPLY_LABEL = "Try again";
export const CONFLICT_DISMISS_LABEL = "Leave it";

/**
 * A card sits inside a surface that treats a click on it as selection or open.
 * Operating a control is neither, so every group swallows the events it owns.
 */
export function stopPropagation(event: { stopPropagation(): void }): void {
  event.stopPropagation();
}

interface TaskOperationPieceProps {
  /** Names every affordance for assistive technology. */
  readonly taskTitle: string;
  readonly operations: TaskRowOperations;
  readonly className?: string;
}

interface TaskStatusOperationControlProps extends TaskOperationPieceProps {
  /**
   * Whether the Status field label is drawn visually (WP-POSTUX-03).
   *
   * Forwarded verbatim to `TaskStatusControl`, which hides it visually only:
   * the `<label htmlFor>` stays in the DOM and the accessible name is
   * unchanged. Omit it and this wrapper renders exactly what it always has,
   * which is what Board and Calendar rely on.
   */
  readonly labelVisibility?: TaskStatusControlProps["labelVisibility"];
}

/** Status, wrapped in the labelled group that contains its events. */
export function TaskStatusOperationControl({
  taskTitle,
  operations,
  className = "min-w-0",
  labelVisibility,
}: TaskStatusOperationControlProps): React.JSX.Element {
  const { ops, locked, conflict, handleStatus } = operations;
  return (
    <div
      role="group"
      aria-label={`Change status for ${taskTitle}`}
      className={className}
      onClick={stopPropagation}
      onKeyDown={stopPropagation}
    >
      <TaskStatusControl
        compact
        value={ops.status.value}
        disabled={locked}
        pending={ops.pending === "status"}
        conflict={conflict}
        labelVisibility={labelVisibility}
        onChange={handleStatus}
      />
    </div>
  );
}

interface TaskDueOperationControlProps extends TaskOperationPieceProps {
  /**
   * Presents the trigger as an action instead of the current Due value
   * (WP-TUX-07). A surface that holds no Task read — Today's Pulse card binds a
   * Task id alone — must not announce a Due phrase it has not read. Omit it and
   * the control behaves exactly as it always has.
   */
  readonly triggerLabel?: string;
  /**
   * Whether the Due trigger carries its visual `Due` prefix (WP-POSTUX-03).
   *
   * Forwarded verbatim to `TaskDueControl`; the accessible name is unaffected.
   * Omit it and this wrapper renders exactly what it always has.
   */
  readonly presentation?: TaskDueControlProps["presentation"];
}

/** Due date, wrapped in the labelled group that contains its events. */
export function TaskDueOperationControl({
  taskTitle,
  operations,
  className = "min-w-0",
  triggerLabel,
  presentation,
}: TaskDueOperationControlProps): React.JSX.Element {
  const { ops, civilClock, locked, conflict, handleDue } = operations;
  return (
    <div
      role="group"
      aria-label={`Change due date for ${taskTitle}`}
      className={className}
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
        triggerLabel={triggerLabel}
        presentation={presentation}
        onChange={handleDue}
      />
    </div>
  );
}

interface TaskTerminalActionsProps extends TaskOperationPieceProps {
  /** Prefixes the test ids so each surface keeps its own hooks. */
  readonly testIdPrefix: string;
  /** Layout for the More disclosure, which is a sibling of the Close group. */
  readonly moreClassName?: string;
  /** Button variant for the Close trigger. Forwarded verbatim; default unchanged. */
  readonly closeTriggerVariant?: TaskCloseControlProps["triggerVariant"];
  /**
   * Visible wording of the More disclosure once it is expanded (WP-POSTUX-03).
   *
   * The accessible name never changes — it stays `More actions for <title>` in
   * both states — so this is visible wording only, for a surface whose row
   * rhythm cannot afford the default phrase. Omit it and the disclosure reads
   * exactly as it always has.
   */
  readonly moreExpandedLabel?: string;
}

/**
 * Close, and the More disclosure that reveals Cancel.
 *
 * A Task that has already been closed or cancelled cannot be closed again, so
 * the surface withholds the action rather than offering to do it once more.
 * Task detail has always drawn this line; the row was offering a live Close —
 * and, under More, Cancel — on every row of the Completed view, with a
 * confirmation behind it that dispatched a second transition against a Task that
 * had already had one.
 *
 * The whole affordance goes, not just its contents: More exists to reveal
 * Cancel, and an empty labelled group left behind a live disclosure that
 * announced itself as expanded with nothing inside it.
 *
 * The outcome itself is not restated here: the card's Status already says Closed
 * or Cancelled, in those words.
 *
 * Render this unconditionally and let it withhold itself — the disclosure's open
 * state then survives a Task becoming terminal and back.
 */
export function TaskTerminalActions({
  taskTitle,
  operations,
  testIdPrefix,
  className = "min-w-0",
  moreClassName = "min-h-11 min-w-11",
  closeTriggerVariant,
  moreExpandedLabel = MORE_CLOSE_LABEL,
}: TaskTerminalActionsProps): React.JSX.Element | null {
  const { ops, locked, terminal, handleClose, handleCancel } = operations;
  const [moreOpen, setMoreOpen] = useState(false);
  const baseId = useId();
  const terminalRegionId = `${baseId}-terminal`;

  if (terminal) return null;

  return (
    <>
      <div
        role="group"
        id={terminalRegionId}
        aria-label={`Close ${taskTitle}`}
        className={className}
        onClick={stopPropagation}
        onKeyDown={stopPropagation}
      >
        <TaskCloseControl
          taskTitle={taskTitle}
          disabled={locked}
          pending={ops.pending === "close" || ops.pending === "cancel"}
          // Cancel is deliberately not a peer of Close in the card: it is
          // revealed only once More is activated.
          showCancel={moreOpen}
          triggerVariant={closeTriggerVariant}
          onClose={handleClose}
          onCancelTask={handleCancel}
        />
      </div>

      <Button
        variant="ghost"
        className={moreClassName}
        data-testid={`${testIdPrefix}-more`}
        data-prominence="tertiary"
        aria-label={`More actions for ${taskTitle}`}
        aria-expanded={moreOpen}
        aria-controls={terminalRegionId}
        onClick={(event) => {
          event.stopPropagation();
          setMoreOpen((open) => !open);
        }}
      >
        {moreOpen ? moreExpandedLabel : MORE_ACTION_LABEL}
      </Button>
    </>
  );
}

interface TaskConflictPanelProps extends TaskOperationPieceProps {
  /** Prefixes the test ids so each surface keeps its own hooks. */
  readonly testIdPrefix: string;
}

/**
 * The way out of a version conflict.
 *
 * A conflict is the user's to resolve, and until they do this card's writes stay
 * shut. Without somewhere to resolve it the card simply stopped working: every
 * control disabled, no explanation, and nothing to press — for the rest of the
 * session, because the card never remounts. Task detail has always offered
 * exactly these two ways out; the card now offers them too rather than locking
 * on a state it gave no means to clear.
 */
export function TaskConflictPanel({
  taskTitle,
  operations,
  testIdPrefix,
  className = "flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border-subtle bg-surface-sunken p-2",
}: TaskConflictPanelProps): React.JSX.Element | null {
  const { ops, busy, conflictRecovery } = operations;
  if (!ops.conflict) return null;

  return (
    <div
      role="group"
      data-testid={`${testIdPrefix}-conflict`}
      aria-label={`Resolve the conflict on ${taskTitle}`}
      className={className}
      onClick={stopPropagation}
      onKeyDown={stopPropagation}
    >
      <p className="min-w-0 flex-1 text-sm text-muted">{TASK_OPERATION_CONFLICT_MESSAGE}</p>
      <Button
        variant="secondary"
        className="min-h-11"
        ref={conflictRecovery}
        data-testid={`${testIdPrefix}-conflict-reapply`}
        pending={busy}
        onClick={() => void ops.reapply()}
      >
        {CONFLICT_REAPPLY_LABEL}
      </Button>
      <Button
        variant="ghost"
        className="min-h-11"
        data-testid={`${testIdPrefix}-conflict-dismiss`}
        onClick={ops.dismissConflict}
      >
        {CONFLICT_DISMISS_LABEL}
      </Button>
    </div>
  );
}
