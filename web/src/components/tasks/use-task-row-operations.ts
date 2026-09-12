"use client";

/**
 * Shared Task-operation machinery for a *card-shaped* surface (WP-TUX-06).
 *
 * Extracted verbatim from the WP-TUX-05 List row so Board and Calendar can carry
 * the same operational affordances without standing up a second mutation engine
 * or a second focus-return engine beside it. This module owns no fetch, no
 * idempotency key, no retry and no version reconciliation: every write still
 * goes through the shared binder `useTaskOperations`, whose contract is
 * unchanged. What lives here is only the part a surface would otherwise have to
 * re-implement — awaited-intent confirmation, the focus the user loses when a
 * write disables the control under their hand, and the derived lock flags.
 *
 * The seed a surface passes is a display projection, never write authority. The
 * binder canonical-hydrates at the first versioned write and sends that version,
 * so a stale projection version can never reach the server.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  useTaskOperations,
  type UseTaskOperationsResult,
} from "@/components/tasks/use-task-operations";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import { browserWorkClock } from "@/lib/api/work-client";
import { isTerminalTaskStatus, type TaskActiveStatus, type TaskCivilClock } from "@/lib/tasks/presentation";

/** The four intents a card-shaped surface can dispatch. */
export type ConfirmKind = "status" | "due" | "close" | "cancel";

export interface AwaitedConfirmation {
  readonly kind: ConfirmKind;
  satisfied(task: TaskDetail): boolean;
}

export interface UseTaskRowOperationsInput {
  readonly taskId: string;
  /**
   * Display projection (a list/board row, or a detail snapshot). Seeds display
   * only; it never authorizes a mutation.
   */
  readonly task?: TaskDetail | TaskRow | null;
  /** Civil-day context. Defaults to the browser clock. */
  readonly clock?: TaskCivilClock;
  /** Fired once a mutation is confirmed by the server, for filter/focus handling. */
  onMutationConfirmed?(input: { taskId: string; kind: string }): void;
}

export interface TaskRowOperations<E extends HTMLElement = HTMLElement> {
  /** The shared binder result, unchanged. */
  readonly ops: UseTaskOperationsResult;
  /** The resolved civil clock, for controls that need one. */
  readonly civilClock: TaskCivilClock;
  /** Attach to the surface's root: focus return is scoped to it. */
  readonly rowRef: React.RefObject<E | null>;
  /** Attach to the conflict panel's reapply button. */
  readonly conflictRecovery: React.RefObject<HTMLButtonElement | null>;
  /** A write is in flight, or an unresolved conflict is showing. */
  readonly locked: boolean;
  /** The Task is already closed or cancelled. */
  readonly terminal: boolean;
  /** A write is in flight. */
  readonly busy: boolean;
  /** An unresolved conflict is showing. */
  readonly conflict: boolean;
  handleStatus(next: TaskActiveStatus): void;
  handleDue(nextIso: string | null): void;
  handleClose(): void;
  handleCancel(): void;
}

export function useTaskRowOperations<E extends HTMLElement = HTMLElement>({
  taskId,
  task,
  clock,
  onMutationConfirmed,
}: UseTaskRowOperationsInput): TaskRowOperations<E> {
  const browserClock = useMemo<TaskCivilClock>(() => browserWorkClock(), []);
  const civilClock = clock ?? browserClock;

  const ops = useTaskOperations(
    { taskId, task },
    {
      clock: civilClock,
      /*
        Always on-demand. A list or board projection is never write authority —
        not even when it carries a `version`, which is a read of some earlier
        moment — so the binder canonical-hydrates at the first versioned write
        and sends that version. Hydrating every card on mount instead would
        issue one detail read per card for a collection the user may never
        touch. `authoritative` is deliberately never passed from here.
      */
      hydrate: "on-demand",
    },
  );

  const { changeStatus, changeDue, closeTask, cancelTask } = ops;

  /* --------------------------------------------------------------- *
   * Confirmation reporting
   *
   * The binder owns the outcome; the surface only needs to know that the
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
  const rowRef = useRef<E | null>(null);
  /** The control the user operated, held while the surface's write disables it. */
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
   * The surface-level control group an element sits in.
   *
   * Not the nearest one: Due's choices are their own group inside the group for
   * Due itself, and the inner one goes when the popover closes. The outer group
   * is the part of the card that stays — for Due, the trigger the popover hangs
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
    // Failing that, the card's own title — still this Task, still where they were.
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

  /*
    Controls stay operable before hydration. The package requires the canonical
    read before the *mutation*, not before the affordance, and the binder does
    exactly that — so gating the control on `canMutate` here would either lock a
    card forever or force an eager detail read per card to unlock it. A write is
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
      With writes in flight on two cards at once, the one that settles first
      takes focus, which need not be the card the user touched last — "focus is
      on the body" cannot tell a user who moved on from one whose second card
      disabled a control under them too. Both are places the user just acted, and
      the alternative is leaving them on the body, so this is an ordering to live
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
      card whose frame runs first takes them to its question rather than the
      other one. Both are questions about their own action, and a conflict cannot
      arise in a card they never wrote to, so this is an ordering the user can
      follow rather than a place they did not ask to be. Left deliberately.
    */
    const frame = requestAnimationFrame(() => {
      if (document.activeElement !== document.body) return;
      conflictRecovery.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [conflict]);

  return {
    ops,
    civilClock,
    rowRef,
    conflictRecovery,
    locked,
    terminal,
    busy,
    conflict,
    handleStatus,
    handleDue,
    handleClose,
    handleCancel,
  };
}
