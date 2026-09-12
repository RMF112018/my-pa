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
import { TASK_OPERATION_CONFLICT_MESSAGE, useTaskOperations } from "@/components/tasks/use-task-operations";
import { Button } from "@/components/ui/button";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import { browserWorkClock } from "@/lib/api/work-client";
import {
  formatTaskPriority,
  isTerminalTaskStatus,
  type TaskActiveStatus,
  type TaskCivilClock,
} from "@/lib/tasks/presentation";

/** Product copy owned by this row. Everything else comes from the shared modules. */
const COMMENT_ACTION_LABEL = "Comment";
const MORE_ACTION_LABEL = "More";
const MORE_CLOSE_LABEL = "Hide more actions";
const CONFLICT_REAPPLY_LABEL = "Try again";
const CONFLICT_DISMISS_LABEL = "Leave it";

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

  /*
    A dispatch that stopped being pending without satisfying its intent did not
    happen: a definitive failure, a conflict awaiting the user, or an ambiguous
    result. Drop it, so a later canonical read for an unrelated reason cannot
    satisfy an intent that never took effect and report it as confirmed.
  */
  const rowRef = useRef<HTMLDivElement | null>(null);
  /** The control the user operated, held while the row's write disables it. */
  const lockedFocus = useRef<HTMLElement | null>(null);
  /** Its control group, for when the control itself answers by closing. */
  const lockedGroup = useRef<HTMLElement | null>(null);
  const pendingKind = ops.pending;
  const conflictOutstanding = ops.conflict !== null;
  useEffect(() => {
    if (pendingKind !== null) return;
    /*
      A conflict is not a settled attempt. The intent is still the user's, still
      awaiting an answer, and the reapply they are being offered is the same
      attempt continued — so it must still be recognised when it confirms.
      Dropping it here meant a recovered conflict reconciled nothing, and the
      Task the user had just moved stayed sitting in a filter it had left.
    */
    if (conflictOutstanding) return;
    awaitingRef.current = [];
  }, [pendingKind, conflictOutstanding]);

  /**
   * The row-level control group an element sits in.
   *
   * Not the nearest one: Due's choices are their own group inside the group for
   * Due itself, and the inner one goes when the popover closes. The outer group
   * is the part of the row that stays — for Due, the trigger the popover hangs
   * off — so that is what a return has to aim at.
   */
  const outermostGroup = useCallback((element: HTMLElement): HTMLElement | null => {
    let group = element.closest<HTMLElement>('[role="group"]');
    for (;;) {
      const parent = group?.parentElement?.closest<HTMLElement>('[role="group"]');
      if (!parent || !rowRef.current?.contains(parent)) return group;
      group = parent;
    }
  }, []);

  const await_ = useCallback(
    (entry: AwaitedConfirmation) => {
      awaitingRef.current = [...awaitingRef.current, entry];
      /*
        Remember the control the user is on, here, in their own event.

        This cannot be read from an effect. A browser blurs a focused element
        the instant `disabled` is applied to it, and React applies that while
        committing — so by the time any effect runs the answer is already
        `document.body` and there is nothing left to remember. Read after the
        fact, this captured nothing at all in a browser, and the whole return
        was dead code that only looked alive under a test environment which
        does not implement that blur.
      */
      const active = document.activeElement;
      if (active instanceof HTMLElement && rowRef.current?.contains(active)) {
        lockedFocus.current = active;
        /*
          The control group as well as the control. Some of these affordances
          answer by closing: Due is chosen from a popover, and choosing dismisses
          it, so the button the user pressed is gone before the write even
          settles. Returning focus to it then returns them nothing at all.
        */
        lockedGroup.current = outermostGroup(active);
      }
    },
    [outermostGroup],
  );

  /** The nearest live thing to the control the user operated. */
  const liveReturn = useCallback((held: HTMLElement): HTMLElement | null => {
    if (held.isConnected) return held;
    const group = lockedGroup.current;
    const withinGroup = group?.isConnected
      ? group.querySelector<HTMLElement>("button:not([disabled]), select:not([disabled]), a[href], input:not([disabled])")
      : null;
    // Failing that, the row's own title — still this Task, still where they were.
    return withinGroup ?? rowRef.current?.querySelector<HTMLElement>("a[href]") ?? null;
  }, []);

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
  /** A Task already closed or cancelled cannot be closed again. */
  const terminal = isTerminalTaskStatus(ops.status.value);
  const locked = ops.pending !== null || ops.conflict !== null;
  const conflict = ops.conflict !== null;
  const busy = ops.pending !== null;

  /*
    Give the control back to the hand that was on it.

    Locking disables the control the user just operated, and disabling the
    focused element drops focus to the document body — so the write they started
    with the keyboard costs them their place for as long as it runs. If it is
    then refused, nothing changes the list and nothing else will put them back:
    they are simply stranded. Hold the element while it is disabled and return
    focus to it on unlock, but only if focus is still lying on the body, so a
    user who moved on in the meantime is never pulled back.

    The return waits a frame. Unlocking can unmount whatever currently holds
    focus — the conflict panel's own buttons, when the user stands the conflict
    down — and until that has happened focus still reads as theirs, so the check
    would decline and then the element would vanish underneath it.
  */
  useEffect(() => {
    if (locked) return;
    const held = lockedFocus.current;
    lockedFocus.current = null;
    if (!held) return;
    /*
      Only focus that is lying on the body is ours to place: a user who moved on
      during the write chose where they are. Whatever unlocking unmounted — the
      conflict panel's buttons when the user answers it, the Due popover the
      moment they choose from it — is already gone by the time this runs, so the
      answer here is the settled one.

      What is placed has to be something still on the page. Calling focus on a
      node that has left the document does nothing, silently, and leaves the user
      exactly where the failure left them: on the body, at the top of the
      document. So the nearest live thing stands in for it.
    */
    if (document.activeElement !== document.body) return;
    /*
      With writes in flight on two rows at once, the one that settles first takes
      focus, which need not be the row the user touched last — "focus is on the
      body" cannot tell a user who moved on from one whose second row disabled a
      control under them too. Both are places the user just acted, and the
      alternative is leaving them on the body, so this is an ordering to live
      with rather than a wrong destination. Left deliberately.
    */
    liveReturn(held)?.focus();
  }, [liveReturn, locked]);

  /*
    A conflict is a question put to the user, so put it where they can answer it.

    The control they operated is disabled for as long as the conflict stands, so
    handing focus back to it would hand them nothing. Meanwhile the write that
    raised the conflict has already cost them their place: disabling that control
    dropped focus to the document body. Without this they are left at the top of
    the document, tabbing back down to a panel that appeared without them.
  */
  const conflictRecovery = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!conflict) return;
    /*
      If the user has two writes in flight and both are refused for version, the
      row whose frame runs first takes them to its question rather than the other
      one. Both are questions about their own action, and a conflict cannot arise
      in a row they never wrote to, so this is an ordering the user can follow
      rather than a place they did not ask to be. Left deliberately.
    */
    const frame = requestAnimationFrame(() => {
      if (document.activeElement !== document.body) return;
      conflictRecovery.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [conflict]);

  return (
    <div
      ref={rowRef}
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

        {/*
          A Task that has already been closed or cancelled cannot be closed
          again, so the row withholds the action rather than offering to do it
          once more. Task detail has always drawn this line; the row was offering
          a live Close — and, under More, Cancel — on every row of the Completed
          view, with a confirmation behind it that dispatched a second transition
          against a Task that had already had one.

          The whole affordance goes, not just its contents: More exists to reveal
          Cancel, and an empty labelled group left behind a live disclosure that
          announced itself as expanded with nothing inside it.

          The outcome itself is not restated here: the row's Status already says
          Closed or Cancelled, in those words.
        */}
        {terminal ? null : (
          <>
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
          </>
        )}
      </div>

      {/*
        A conflict is the user's to resolve, and until they do this row's writes
        stay shut. Without somewhere to resolve it the row simply stopped
        working: every control disabled, no explanation, and nothing to press —
        for the rest of the session, because the row never remounts. Task detail
        has always offered exactly these two ways out; the row now offers them
        too rather than locking on a state it gave no means to clear.
      */}
      {ops.conflict ? (
        <div
          role="group"
          data-testid="task-list-row-conflict"
          aria-label={`Resolve the conflict on ${title}`}
          className="flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border-subtle bg-surface-sunken p-2"
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <p className="min-w-0 flex-1 text-sm text-muted">{TASK_OPERATION_CONFLICT_MESSAGE}</p>
          <Button
            variant="secondary"
            className="min-h-11"
            ref={conflictRecovery}
            data-testid="task-list-row-conflict-reapply"
            pending={busy}
            onClick={() => void ops.reapply()}
          >
            {CONFLICT_REAPPLY_LABEL}
          </Button>
          <Button
            variant="ghost"
            className="min-h-11"
            data-testid="task-list-row-conflict-dismiss"
            onClick={ops.dismissConflict}
          >
            {CONFLICT_DISMISS_LABEL}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
