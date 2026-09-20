"use client";

/**
 * Canonical Task create surface (WP-TUX-04).
 *
 * One create form for every entry point — Work, Capture and a scoped context.
 * The surface asks the Principal for the four things a Task needs and nothing
 * else: Origin, Commitment and Role are decided by the runtime and the server,
 * not by a person filling in a form, so they have no field here and this
 * component issues no commitments request.
 *
 * Identity and idempotency live in the runtime's `CreateIntentSession`, never in
 * React form state: unmounting this sheet must not erase an unresolved intent,
 * and an ambiguous attempt must be retried with the same frozen request and the
 * same key rather than a freshly minted one.
 *
 * WP-POSTUX-02 / F-001: every launcher mounts its own copy of this form over one
 * shared `CreateIntentStore`, and those copies stay mounted while closed. An
 * unresolved create is therefore a property of the session, not of whichever
 * copy is on screen, so the session is re-resolved on every open and then
 * observed — one human intent, one key, one reconciliation, one announcement,
 * however many launchers happen to be mounted.
 *
 * Due is a civil day. It is serialized with `civilDayEndIso` against the
 * browser's own IANA zone, never by truncating or Z-suffixing a timestamp, and
 * a frozen `dueAt` is displayed back through `civilDayInZone` for the same
 * reason.
 */

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MutationFeedbackEvent } from "@/components/ui/mutation-feedback";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useTaskRuntime } from "@/components/work/task-runtime-provider";
import { browserWorkClock, workRequest } from "@/lib/api/work-client";
import type { CreateIntentSession, TaskCreateRequest } from "@/lib/task/create-intent";
import {
  NO_PRIORITY_LABEL,
  TASK_DUE_FIELD_LABEL,
  TASK_PRIORITY_LABELS,
  civilDayEndIso,
  civilDayInZone,
} from "@/lib/tasks/presentation";
import type { TaskPriority } from "@/contracts/work";

/** Scope the create was started from. Ids are carried, never displayed raw. */
export interface TaskCreateContext {
  readonly projectId?: string;
  readonly situationId?: string;
  readonly label?: string;
}

export interface TaskCreateSheetProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly entry: "work" | "capture" | "scoped_context";
  readonly context?: TaskCreateContext;
  /** Capture chooser only: return to the chooser instead of closing. */
  readonly onBack?: () => void;
  readonly onConfirmed?: (task: unknown) => void;
}

export const TASK_CREATE_TITLE_LABEL = "Title";
export const TASK_CREATE_DESCRIPTION_LABEL = "Description";
export const TASK_CREATE_PRIORITY_LABEL = "Priority";
export const TASK_CREATE_TITLE_REQUIRED = "Enter a task title.";

const CREATE_PENDING_STATUS = "Creating task…";
const CREATE_AMBIGUOUS_STATUS =
  "Create may still have succeeded. Retry with the same intent — do not edit it until this resolves.";

/** Priority choices in product language. `""` is the explicit absence of a priority. */
const PRIORITY_CHOICES: readonly { readonly value: "" | TaskPriority; readonly label: string }[] = [
  { value: "", label: NO_PRIORITY_LABEL },
  { value: "p1", label: TASK_PRIORITY_LABELS.p1 },
  { value: "p2", label: TASK_PRIORITY_LABELS.p2 },
  { value: "p3", label: TASK_PRIORITY_LABELS.p3 },
  { value: "p4", label: TASK_PRIORITY_LABELS.p4 },
];

/** An unresolved intent owns a frozen request; anything else is editable. */
function isUnresolved(session: CreateIntentSession): boolean {
  const phase = session.getPhase();
  return phase === "pending" || phase === "ambiguous";
}

/** Terminal for this surface: the session can never become visible work again. */
function isSpent(session: CreateIntentSession): boolean {
  const phase = session.getPhase();
  return session.isRetired() || phase === "confirmed" || phase === "abandoned";
}

export function TaskCreateSheet({
  open,
  onOpenChange,
  entry,
  context,
  onBack,
  onConfirmed,
}: TaskCreateSheetProps): React.JSX.Element {
  const runtime = useTaskRuntime();
  const clock = useMemo(() => browserWorkClock(), []);
  const baseId = useId();
  const titleId = `${baseId}-title`;
  const titleErrorId = `${baseId}-title-error`;
  const descriptionId = `${baseId}-description`;
  const priorityId = `${baseId}-priority`;
  const dueId = `${baseId}-due`;
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  // Submit mutex outside React state: a second activation can arrive before the
  // pending render lands, and it must not reach the session or the network. It
  // is also this instance's claim of ownership over the session's transitions —
  // an observing sibling must not reconcile, announce or re-focus a create it
  // did not dispatch.
  const dispatchingRef = useRef(false);

  const [session, setSession] = useState<CreateIntentSession>(
    () => runtime.createIntents.getUnresolvedSession() ?? runtime.createIntents.openSession(),
  );
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"" | TaskPriority>("");
  const [due, setDue] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  // Bumped by the bound session's own emissions so a change made by another
  // mounted copy of this form re-renders this one.
  const [, setObserved] = useState(0);

  // Refs the session listener reads: it must see the current binding and props
  // without re-subscribing on every parent render. Written after commit, never
  // during render.
  const sessionRef = useRef(session);
  const openRef = useRef(open);
  const onOpenChangeRef = useRef(onOpenChange);
  useEffect(() => {
    sessionRef.current = session;
    openRef.current = open;
    onOpenChangeRef.current = onOpenChange;
  });

  const phase = session.getPhase();
  // Ambiguous and in-flight intents own a frozen request: the draft must not move.
  const frozen = phase === "ambiguous" || phase === "pending";
  const dispatchingPhase = phase === "pending";
  const inert = pending || frozen;

  /** Show a session's frozen request verbatim. Returns false if it has none. */
  const showFrozenRequest = useCallback(
    (next: CreateIntentSession): boolean => {
      const nextPhase = next.getPhase();
      const frozenRequest = isUnresolved(next) ? next.getFrozenRequest() : undefined;
      if (!frozenRequest) return false;
      setTitle(frozenRequest.title);
      setDescription(frozenRequest.description ?? "");
      setPriority((frozenRequest.priority as "" | TaskPriority | undefined) ?? "");
      // Civil day in the browser's zone — a UTC truncation of the frozen instant
      // can name the wrong day.
      setDue(frozenRequest.dueAt ? civilDayInZone(frozenRequest.dueAt, clock.timezone) : "");
      setTitleError(null);
      setStatus(nextPhase === "ambiguous" ? CREATE_AMBIGUOUS_STATUS : CREATE_PENDING_STATUS);
      return true;
    },
    [clock.timezone],
  );

  const clearFields = useCallback(() => {
    setTitle("");
    setDescription("");
    setPriority("");
    setDue("");
    setTitleError(null);
    setStatus("");
  }, []);

  /**
   * Bind this surface to a session and show what that session actually holds:
   * its frozen request when it owns one, an empty form otherwise.
   */
  const bindSession = useCallback(
    (next: CreateIntentSession) => {
      setSession(next);
      if (!showFrozenRequest(next)) clearFields();
    },
    [showFrozenRequest, clearFields],
  );

  /**
   * Resume the session's unresolved create on every open (WP02-AC-067).
   *
   * This form is mounted before it is ever opened, so the session cannot be
   * resolved once at mount: an intent that became unresolved in another launcher
   * afterwards must still be adopted here, and it wins over any local draft. No
   * intent is minted and nothing is dispatched.
   */
  useEffect(() => {
    if (!open) return;
    const store = runtime.createIntents;
    const unresolved = store.getUnresolvedSession();
    /* The re-render this schedules is the point, and it cannot be derived during
       render instead: which session is bound depends on what every other mounted
       launcher has done since, and resolving it can mint an intent — a store
       write that must never happen in a render pass. */
    const next =
      unresolved ?? (isSpent(sessionRef.current) ? store.openSession() : undefined);
    if (next) bindSession(next);
  }, [open, runtime, bindSession]);

  /**
   * Observe the bound session (WP02-AC-070). The subscription is keyed on the
   * session identity, so replacing the binding unsubscribes the old one, and
   * unmounting unsubscribes too — no stale listeners (WP02-AC-074).
   */
  useEffect(() => {
    return session.subscribe(() => {
      setObserved((version) => version + 1);
      // The instance that dispatched owns the whole transition: its own submit
      // path reconciles, announces, retires and closes. An observer must not.
      if (dispatchingRef.current) return;
      if (isUnresolved(session)) {
        showFrozenRequest(session);
        return;
      }
      if (!isSpent(session)) {
        // Resolved, but still this surface's session — an ambiguous attempt that
        // came back definitively failed. The frozen values are still what the
        // Principal wrote, but "may still have succeeded" is now untrue, so the
        // announcement must not outlive the phase that justified it.
        setStatus("");
        return;
      }
      // Confirmed, abandoned or pruned under us: settle quietly — no second
      // reconcile, no second announcement. Deliberately no new session here: one
      // confirm emits more than once, and minting per emission would strand a
      // fresh draft in the store on each. The spent binding is harmless while
      // closed, and the open effect re-resolves on the next open.
      clearFields();
      if (openRef.current) onOpenChangeRef.current(false);
    });
  }, [session, showFrozenRequest, clearFields]);

  /**
   * Resumed-state focus (WP02-AC-034). A fresh form keeps Title's autofocus; a
   * resumed one must not put editing focus on a field the Principal cannot edit,
   * so an ambiguous resume lands on its actionable primary and a pending resume
   * lands on the panel's own dismissal while the status stays announced.
   */
  const resumedFocusKey = open && frozen ? `${session.intentId}:${phase}` : "";
  const focusedKeyRef = useRef("");
  useEffect(() => {
    if (!resumedFocusKey) {
      focusedKeyRef.current = "";
      return;
    }
    if (focusedKeyRef.current === resumedFocusKey) return;
    focusedKeyRef.current = resumedFocusKey;
    // This instance dispatched: the Principal's focus is already where they put it.
    if (dispatchingRef.current) return;
    if (phase === "ambiguous") {
      primaryRef.current?.focus();
      return;
    }
    const dismiss = formRef.current
      ?.closest('[role="dialog"]')
      ?.querySelector<HTMLElement>('[aria-label="Close panel"]');
    dismiss?.focus();
  }, [resumedFocusKey, phase]);

  function buildRequest(): TaskCreateRequest {
    return {
      title: title.trim(),
      // Whitespace-only is an absent description; authored line breaks survive.
      description: description.trim() ? description : undefined,
      priority: priority || undefined,
      dueAt: due ? civilDayEndIso(due, clock.timezone) : undefined,
      projectId: context?.projectId || undefined,
      situationId: context?.situationId || undefined,
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || dispatchingRef.current) return;

    const active = session;
    const current = active.getPhase();
    // Ambiguous / pending: submit() retries the exact frozen request under the
    // exact same key. The launcher's own context must never be written into it.
    const resuming = current === "ambiguous" || current === "pending";

    if (!resuming && !title.trim()) {
      setTitleError(TASK_CREATE_TITLE_REQUIRED);
      setStatus("");
      titleRef.current?.focus();
      return;
    }
    setTitleError(null);

    // Claimed before any store mutation: abandoning a definitively failed session
    // emits, and this instance must not treat its own replacement as a sibling's
    // settle.
    dispatchingRef.current = true;
    let dispatched = active;
    try {
      if (!resuming) {
        const request = buildRequest();
        if (current === "failed") {
          dispatched = runtime.createIntents.replaceAfterMaterialEdit(active, request);
          setSession(dispatched);
        } else {
          try {
            dispatched.updateDraft(request);
          } catch {
            // §8.4: the status line is product language in both modes.
            setStatus("Draft could not be updated.");
            return;
          }
        }
      }

      setPending(true);
      setStatus(current === "ambiguous" ? "Retrying the same create…" : CREATE_PENDING_STATUS);
      const outcome = await dispatched.submit(
        async ({ request: frozenRequest, idempotencyKey }) =>
          workRequest("/api/tasks", {
            method: "POST",
            body: JSON.stringify({ ...frozenRequest, idempotencyKey }),
          }),
        {
          feedback: () => {
            const confirmedTitle = dispatched.getFrozenRequest()?.title ?? title.trim();
            runtime.feedback.publish({
              eventId: MutationFeedbackEvent.createConfirmed(dispatched.intentId),
              kind: "success",
              message: `Task created: ${confirmedTitle}`,
            });
          },
        },
      );
      if (outcome.refused) {
        if (outcome.reason === "create dispatch already in flight") return;
        // WP07 §6.2: `reason` is the coordinator's own implementation-state
        // narration ("create dispatch already in flight"). The consequence —
        // nothing was created and the draft is intact — is the product truth.
        setStatus("The Task was not created. Your draft is still here.");
        return;
      }
      // Confirmed. Reconciliation belongs to the canonical create itself, not to
      // each launcher: Work and Capture must both revalidate active Task queries,
      // and a launcher that forgot to wire it would silently leave a just-created
      // Task missing from a mounted list. It is published exactly once — by the
      // instance that dispatched, never by a sibling observing the same session.
      runtime.reconciliation.notifyCreateConfirmed(outcome.result);
      // Retire the intent, clear the draft, hand the result back.
      runtime.createIntents.pruneTerminal();
      setSession(runtime.createIntents.getUnresolvedSession() ?? runtime.createIntents.openSession());
      clearFields();
      onConfirmed?.(outcome.result);
      onOpenChange(false);
    } catch {
      if (dispatched.getPhase() === "ambiguous") {
        setStatus(CREATE_AMBIGUOUS_STATUS);
      } else {
        setStatus("Task was not created.");
      }
    } finally {
      dispatchingRef.current = false;
      setPending(false);
    }
  }

  const primaryLabel =
    pending || dispatchingPhase ? "Creating…" : phase === "ambiguous" ? "Retry same create" : "Create";
  const busy = pending || dispatchingPhase;

  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Create task" placement="detail">
      <form
        ref={formRef}
        data-testid="task-create-sheet"
        onSubmit={(event) => void submit(event)}
        aria-busy={busy || undefined}
        /* F-002: the create surface alone compacts its major-field rhythm — 12px
           on a narrow viewport, the shared 16px from lg up. */
        className="flex flex-col gap-3 lg:gap-4"
      >
        {/* The label describes the *current* launcher's scope. A frozen request
            was composed somewhere else, so showing it here would falsely
            describe what is about to be retried (WP02-AC-073). */}
        {context?.label && !frozen ? (
          <p
            data-testid="task-create-context"
            className="w-fit rounded-[var(--radius-md)] bg-surface-subtle px-2 py-1 text-xs text-text-secondary"
          >
            {context.label}
          </p>
        ) : null}

        <div className="flex flex-col gap-1">
          <label htmlFor={titleId} className="text-sm font-medium text-text-primary">
            {TASK_CREATE_TITLE_LABEL}
          </label>
          <Input
            ref={titleRef}
            id={titleId}
            /* A resumed, uneditable form must not take editing focus (WP02-AC-034). */
            autoFocus={!frozen}
            className="min-h-11"
            value={title}
            disabled={inert}
            readOnly={frozen}
            /* Required from the first render, not only after a refusal
               (WP02-AC-072). Not native `required`: browser validation would
               intercept and replace the accepted custom refusal path. */
            aria-required="true"
            aria-invalid={titleError ? true : undefined}
            aria-describedby={titleError ? titleErrorId : undefined}
            onChange={(event) => {
              if (frozen) return;
              setTitle(event.target.value);
              if (titleError) setTitleError(null);
            }}
          />
          {titleError ? (
            <p id={titleErrorId} role="alert" className="text-xs text-destructive">
              {titleError}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={descriptionId} className="text-sm font-medium text-text-primary">
            {TASK_CREATE_DESCRIPTION_LABEL}
          </label>
          {/* F-002: 80px on a narrow viewport, the shared 96px from lg up. The
              important suffix is load-bearing — Tailwind emits `min-h-20` before
              the primitive's `min-h-24`, so an unflagged caller class loses. */}
          <Textarea
            id={descriptionId}
            className="min-h-20! lg:min-h-24!"
            value={description}
            disabled={inert}
            readOnly={frozen}
            onChange={(event) => {
              if (frozen) return;
              setDescription(event.target.value);
            }}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={priorityId} className="text-sm font-medium text-text-primary">
            {TASK_CREATE_PRIORITY_LABEL}
          </label>
          <Select
            id={priorityId}
            value={priority}
            disabled={inert}
            onChange={(event) => {
              if (frozen) return;
              setPriority(event.target.value as "" | TaskPriority);
            }}
            className="min-h-11 text-text-primary disabled:opacity-60"
          >
            {PRIORITY_CHOICES.map((choice) => (
              <option key={choice.value || "none"} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={dueId} className="text-sm font-medium text-text-primary">
            {TASK_DUE_FIELD_LABEL}
          </label>
          <div className="flex items-center gap-2">
            <Input
              id={dueId}
              type="date"
              className="min-h-11"
              value={due}
              disabled={inert}
              readOnly={frozen}
              onChange={(event) => {
                if (frozen) return;
                setDue(event.target.value);
              }}
            />
            <Button
              type="button"
              variant="ghost"
              className="min-h-11 min-w-11"
              disabled={inert}
              onClick={() => setDue("")}
            >
              Clear
            </Button>
          </div>
        </div>

        {status ? (
          <p role="status" className="text-sm text-muted">
            {status}
          </p>
        ) : null}

        {/* Safe-area aware footer: the primary action stays reachable with a
            software keyboard open, and never sits under the home indicator. */}
        <div className="sticky bottom-0 flex flex-wrap gap-2 bg-surface pt-2 pb-[env(safe-area-inset-bottom)]">
          <Button
            ref={primaryRef}
            type="submit"
            className="min-h-11"
            disabled={busy}
            aria-busy={busy || undefined}
          >
            {primaryLabel}
          </Button>
          {entry === "capture" && onBack ? (
            <Button type="button" variant="secondary" className="min-h-11" onClick={onBack}>
              Back
            </Button>
          ) : null}
        </div>
      </form>
    </Sheet>
  );
}
