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
 * Due is a civil day. It is serialized with `civilDayEndIso` against the
 * browser's own IANA zone, never by truncating or Z-suffixing a timestamp.
 */

import { useId, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MutationFeedbackEvent } from "@/components/ui/mutation-feedback";
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

/** Priority choices in product language. `""` is the explicit absence of a priority. */
const PRIORITY_CHOICES: readonly { readonly value: "" | TaskPriority; readonly label: string }[] = [
  { value: "", label: NO_PRIORITY_LABEL },
  { value: "p1", label: TASK_PRIORITY_LABELS.p1 },
  { value: "p2", label: TASK_PRIORITY_LABELS.p2 },
  { value: "p3", label: TASK_PRIORITY_LABELS.p3 },
  { value: "p4", label: TASK_PRIORITY_LABELS.p4 },
];

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
  const titleRef = useRef<HTMLInputElement>(null);
  // Submit mutex outside React state: a second activation can arrive before the
  // pending render lands, and it must not reach the session or the network.
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

  const phase = session.getPhase();
  // Ambiguous and in-flight intents own a frozen request: the draft must not move.
  const frozen = phase === "ambiguous" || phase === "pending";
  const inert = pending || frozen;

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

    if (!title.trim()) {
      setTitleError(TASK_CREATE_TITLE_REQUIRED);
      setStatus("");
      titleRef.current?.focus();
      return;
    }
    setTitleError(null);

    const request = buildRequest();

    let active = session;
    const current = active.getPhase();
    // Ambiguous / pending: never mutate the draft — submit() retries the frozen request/key.
    if (current === "failed") {
      active = runtime.createIntents.replaceAfterMaterialEdit(active, request);
      setSession(active);
    } else if (current !== "ambiguous" && current !== "pending") {
      try {
        active.updateDraft(request);
      } catch (error) {
        setStatus(error instanceof Error ? error.message : "Draft could not be updated");
        return;
      }
    }

    dispatchingRef.current = true;
    setPending(true);
    setStatus(current === "ambiguous" ? "Retrying the same create…" : "Creating task…");
    try {
      const outcome = await active.submit(
        async ({ request: frozenRequest, idempotencyKey }) =>
          workRequest("/api/tasks", {
            method: "POST",
            body: JSON.stringify({ ...frozenRequest, idempotencyKey }),
          }),
        {
          feedback: () => {
            const confirmedTitle = active.getFrozenRequest()?.title ?? request.title;
            runtime.feedback.publish({
              eventId: MutationFeedbackEvent.createConfirmed(active.intentId),
              kind: "success",
              message: `Task created: ${confirmedTitle}`,
            });
          },
        },
      );
      if (outcome.refused) {
        if (outcome.reason === "create dispatch already in flight") return;
        setStatus(outcome.reason);
        return;
      }
      // Confirmed. Reconciliation belongs to the canonical create itself, not to
      // each launcher: Work and Capture must both revalidate active Task queries,
      // and a launcher that forgot to wire it would silently leave a just-created
      // Task missing from a mounted list.
      runtime.reconciliation.notifyCreateConfirmed(outcome.result);
      // Retire the intent, clear the draft, hand the result back.
      runtime.createIntents.pruneTerminal();
      setSession(runtime.createIntents.getUnresolvedSession() ?? runtime.createIntents.openSession());
      setTitle("");
      setDescription("");
      setPriority("");
      setDue("");
      setStatus("");
      onConfirmed?.(outcome.result);
      onOpenChange(false);
    } catch (error) {
      if (active.getPhase() === "ambiguous") {
        setStatus(
          "Create may still have succeeded. Retry with the same intent — do not edit it until this resolves.",
        );
      } else {
        setStatus(error instanceof Error ? error.message : "Task was not created");
      }
    } finally {
      dispatchingRef.current = false;
      setPending(false);
    }
  }

  const primaryLabel = pending
    ? "Creating…"
    : session.getPhase() === "ambiguous"
      ? "Retry same create"
      : "Create";

  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Create task" placement="detail">
      <form
        data-testid="task-create-sheet"
        onSubmit={(event) => void submit(event)}
        aria-busy={pending || undefined}
        className="flex flex-col gap-4"
      >
        {context?.label ? (
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
            autoFocus
            className="min-h-11"
            value={title}
            disabled={inert}
            readOnly={frozen}
            aria-invalid={titleError ? true : undefined}
            aria-describedby={titleError ? titleErrorId : undefined}
            onChange={(event) => {
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
          <Textarea
            id={descriptionId}
            value={description}
            disabled={inert}
            readOnly={frozen}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={priorityId} className="text-sm font-medium text-text-primary">
            {TASK_CREATE_PRIORITY_LABEL}
          </label>
          <select
            id={priorityId}
            value={priority}
            disabled={inert}
            onChange={(event) => setPriority(event.target.value as "" | TaskPriority)}
            className="min-h-11 rounded-[var(--radius-md)] border border-border-subtle bg-surface px-3 text-sm text-text-primary disabled:opacity-60"
          >
            {PRIORITY_CHOICES.map((choice) => (
              <option key={choice.value || "none"} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
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
              onChange={(event) => setDue(event.target.value)}
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
          <Button type="submit" className="min-h-11" disabled={pending} aria-busy={pending || undefined}>
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
