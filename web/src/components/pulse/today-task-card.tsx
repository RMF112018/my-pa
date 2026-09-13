"use client";

/**
 * A Task surfaced by Today's Pulse, with the two operations that answer it
 * directly (WP-TUX-07).
 *
 * ## What this card knows, and what it therefore may say
 *
 * A Pulse item is a `BackendPulseItem` — a projection of *why now* — and it is
 * not a `TaskRow`. It carries no `lifecycle_state`, no `due_at`, no `version`
 * and no `updated_at`. So this card holds a Task **id** and a display title and
 * reason, and nothing else about the Task's state.
 *
 * From that follows the whole shape of this component:
 *
 * - **No Status control.** With no seed the binder falls back to the literal
 *   `"open"`, and a Status control would announce that as fact about a Task
 *   nobody has read. It is not required here, so it is not offered.
 * - **No current Due value, anywhere.** The same fallback makes `due.value`
 *   `null`, which the shared Due trigger would announce as "Due, No due date" —
 *   for a Task that Pulse surfaced *because it is overdue*. That is a
 *   fabrication. The trigger is therefore given `triggerLabel`, so it presents
 *   itself as the action "Reschedule <title>" and asserts no value.
 * - The attention reason is the one thing this card is authoritative about: it
 *   comes from the Pulse projection, which is exactly a statement about why the
 *   item surfaced.
 *
 * The fix for the missing state is deliberately *not* hydration. `hydrate:
 * "eager"`, or fetching a TaskRow seed per card, is one detail read per Pulse
 * item for a list the user may never touch. `useTaskRowOperations` pins
 * `hydrate: "on-demand"` and never passes `authoritative`, so the canonical
 * read before the first versioned write is structural: the card reads the Task
 * at the moment it writes to it, and never before.
 *
 * Boundaries: presentation and intent only. No fetch, no idempotency key, no
 * retry, no version reconciliation — every write goes through the shared binder.
 * Success, failure and conflict are announced by `useTaskOperations` through the
 * shared mutation feedback region, which is mounted at shell lifetime; this card
 * publishes nothing of its own.
 */

import { useId } from "react";

import {
  stopPropagation,
  TaskConflictPanel,
  TaskDueOperationControl,
  TaskTerminalActions,
} from "@/components/tasks/task-operation-controls";
import { useTaskRowOperations } from "@/components/tasks/use-task-row-operations";
import type { TaskCivilClock } from "@/lib/tasks/presentation";

/** Test-id namespace for the shared affordances rendered in this surface. */
const CARD_TEST_ID_PREFIX = "today-card";

/** Product copy owned by this card. */
const RESCHEDULE_ACTION_LABEL = "Reschedule";

export interface TodayTaskCardProps {
  /** The Task this Pulse item is about. The only Task fact the card is given. */
  readonly taskId: string;
  /** Display title, from the Pulse projection's `subjectTitle`. Never an id. */
  readonly title: string;
  /** The concise attention reason, from the Pulse projection's `reason`. */
  readonly reason: string;
  /**
   * Optional elaboration — what happens if this is ignored. Rendered after the
   * actions, because it explains rather than asks.
   */
  readonly explanation?: string;
  /** Civil-day context. Defaults to the browser clock. */
  readonly clock?: TaskCivilClock;
  /** Fired once a mutation is confirmed by the server, for list/focus handling. */
  onMutationConfirmed?(input: { taskId: string; kind: string }): void;
}

export function TodayTaskCard({
  taskId,
  title,
  reason,
  explanation,
  clock,
  onMutationConfirmed,
}: TodayTaskCardProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLElement>({
    taskId,
    /*
      Deliberately undefined. A Pulse item is not a Task read, and passing it as
      a seed would be passing a projection of a different thing entirely.
    */
    task: undefined,
    clock,
    onMutationConfirmed,
  });
  const { ops, rowRef, busy } = operations;
  /** Names the card for a screen reader when focus lands on the root. */
  const titleId = useId();

  /*
    Once a write has confirmed, the canonical Task is held and its title is the
    newer information about this Task — a rename made elsewhere should not leave
    the card's accessible names pinned to whatever Pulse was generated with.
    Until then the projection's title is all there is.
  */
  const displayTitle = ops.display?.title ?? title;

  return (
    <article
      ref={rowRef}
      data-testid="today-task-card"
      /*
        Which Task this card is about, on the element that is the card.

        The surface that owns the list restores focus when its authoritative
        re-read removes a card the user was standing in, and to do that it has to
        be able to say *which* card left and which one now stands in its place.
        The test id names the kind of thing; this names the thing itself. It is
        read, never written, by that surface.
      */
      data-today-task={taskId}
      aria-busy={busy || undefined}
      aria-labelledby={titleId}
      /*
        Focusable by script, never a tab stop.

        This card's own affordances withdraw when the Task becomes terminal:
        confirm Close and both the control the user is holding and its
        `role="group"` unmount together. The shared focus engine then walks its
        fallback chain, and a card that is not a link has no anchor for the chain
        to land on — so without this the keyboard user who just closed a Task is
        dropped on `document.body`. `-1` lets the engine place them on the card
        they acted on (announced as the Task, via `aria-labelledby`) with the
        card's surviving controls ahead of them, while adding nothing to the tab
        order for everyone else. There is no second focus path here: the engine
        in `useTaskRowOperations` is the only one, and this is the target it was
        missing.
      */
      tabIndex={-1}
      className="flex min-w-0 flex-col gap-2 rounded-[var(--radius-md)] border border-border-subtle bg-surface p-3"
    >
      {/* Reading order: what it is, why now, what to do, and only then why it matters. */}
      <h3 id={titleId} data-testid="today-task-card-title" className="min-w-0 break-words font-medium text-text-primary">
        {displayTitle}
      </h3>

      <p data-testid="today-task-card-reason" className="min-w-0 text-sm text-text-secondary">
        {reason}
      </p>

      {/*
        The card sits in a surface that may treat a click on it as opening the
        Task. Operating a control is neither selection nor navigation, so the
        action region swallows the events it owns. The shared pieces contain
        their own events too; this is the containment for the region itself.
      */}
      <div
        className="flex min-w-0 flex-wrap items-start gap-2"
        onClick={stopPropagation}
        onKeyDown={stopPropagation}
      >
        <TaskDueOperationControl
          taskTitle={displayTitle}
          operations={operations}
          triggerLabel={`${RESCHEDULE_ACTION_LABEL} ${displayTitle}`}
        />
        <TaskTerminalActions
          taskTitle={displayTitle}
          operations={operations}
          testIdPrefix={CARD_TEST_ID_PREFIX}
        />
      </div>

      {/*
        Mandatory, not decorative. A conflict disables every write on this card
        until the user answers it, and `conflictRecovery` focuses the reapply
        button inside this panel — without it a conflicted card is locked for the
        rest of the session with nothing to press.
      */}
      <TaskConflictPanel
        taskTitle={displayTitle}
        operations={operations}
        testIdPrefix={CARD_TEST_ID_PREFIX}
      />

      {explanation ? (
        <p data-testid="today-task-card-explanation" className="min-w-0 text-sm text-muted">
          {explanation}
        </p>
      ) : null}
    </article>
  );
}
