"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { RevealDialog } from "@/components/shell/reveal-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import {
  TaskRuntimeProvider,
  useTaskRuntime,
} from "@/components/work/task-runtime-provider";
import { mapUserError, type UserErrorPresentation } from "@/lib/ui/user-error";
import { Textarea } from "@/components/ui/textarea";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type {
  CommitmentDetail,
  CommitmentFollowUp,
  CommitmentRow,
  CounterpartyOption,
  TaskComment,
  TaskDetail,
  TaskRow,
  TaskLifecycle,
  WorkHistoryRow,
} from "@/contracts/work";
import { TaskCloseControl } from "@/components/tasks/task-close-control";
import { TaskCompact } from "@/components/tasks/task-compact";
import { TaskComments } from "@/components/tasks/task-comments";
import { TaskDetailSections } from "@/components/tasks/task-detail-sections";
import { TaskDueControl } from "@/components/tasks/task-due-control";
import { TaskStatusControl } from "@/components/tasks/task-status-control";
import { TaskTechnicalDetails } from "@/components/tasks/task-technical-details";
import {
  TASK_OPERATION_AMBIGUOUS_MESSAGE,
  TASK_OPERATION_CONFLICT_MESSAGE,
  TASK_OPERATION_FAILURE_MESSAGE,
  useTaskOperations,
} from "@/components/tasks/use-task-operations";
import { formatTaskStatus, toTaskPresentationModel, type TaskCivilClock } from "@/lib/tasks/presentation";
import {
  browserWorkClock,
  captureEvidence,
  createAttemptKey,
  isDefinitiveAttemptFailure,
  requiredCollection,
  workRequest,
  type ApiFailure,
} from "@/lib/api/work-client";
import type { MutationPhase } from "@/lib/task/mutation-state";
import { buildTaskQueryKey } from "@/lib/task/query-key";
import type { TaskReadCoordinator } from "@/lib/task/read-coordinator";

function Labeled({ label, children }: { label: string; children: ReactNode }) { return <label className="grid gap-1 text-sm font-medium text-moss-slate"><span>{label}</span>{children}</label>; }
function display(value: string | null | undefined) { return value ? value.replaceAll("_", " ") : "Not set"; }
function dateInput(value: string | null | undefined) { return value?.slice(0, 16) ?? ""; }
function counterpartyLabel(id: unknown, choices: readonly CounterpartyOption[]) { if (!id) return "Not set"; return choices.find((choice) => choice.person_id === id)?.display_name ?? "Counterparty not resolved"; }

/** Bounded field save outcome copy. Operation copy comes from the shared binder. */
const TASK_SAVED_MESSAGE = "Task saved.";

interface TaskDraft {
  title: string;
  description: string;
  priority: string;
  dueAt: string;
  scheduledAt: string;
  deferredUntil: string;
  commitmentId: string;
  role: string;
  archived: boolean;
}

function taskDraft(task: TaskDetail): TaskDraft {
  return {
    title: task.title,
    description: task.description ?? "",
    priority: task.priority ?? "",
    dueAt: dateInput(task.due_at),
    scheduledAt: dateInput(task.scheduled_at),
    deferredUntil: dateInput(task.deferred_until),
    commitmentId: task.commitment_id ?? "",
    role: task.role ?? "",
    archived: Boolean(task.archived_at),
  };
}

function draftsEqual(a: TaskDraft, b: TaskDraft): boolean {
  return (
    a.title === b.title &&
    a.description === b.description &&
    a.priority === b.priority &&
    a.dueAt === b.dueAt &&
    a.scheduledAt === b.scheduledAt &&
    a.deferredUntil === b.deferredUntil &&
    a.commitmentId === b.commitmentId &&
    a.role === b.role &&
    a.archived === b.archived
  );
}

function isDraftDirty(draft: TaskDraft, authoritative: TaskDetail): boolean {
  return !draftsEqual(draft, taskDraft(authoritative));
}

function isTaskDetail(value: unknown): value is TaskDetail {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<TaskDetail>;
  return typeof row.task_id === "string" && typeof row.title === "string" && typeof row.version === "number";
}

function taskFromUnknown(value: unknown): TaskDetail | undefined {
  if (isTaskDetail(value)) return value;
  if (value && typeof value === "object" && "task" in value && isTaskDetail((value as { task: unknown }).task)) {
    return (value as { task: TaskDetail }).task;
  }
  return undefined;
}

/**
 * Task detail with authoritative snapshot / dirty draft / conflict separation.
 *
 * Isolated variant: mounts its own Task runtime so tests, stories and any mount
 * that is deliberately outside AppShell still get real coordinators. Ordinary
 * signed-in surfaces — the Work-hosted sheet and the standalone
 * `/work/tasks/[taskId]` route — use {@link TaskDetailViewConnected}, which
 * consumes the shell-persistent runtime instead.
 */
export function TaskDetailView({
  taskId,
  embedded = false,
  seed,
}: {
  taskId: string;
  embedded?: boolean;
  /** Projection that seeds fast paint only. It never authorizes a mutation. */
  seed?: TaskRow | null;
}) {
  return (
    <TaskRuntimeProvider principalId="isolated-task-detail" sessionEpoch="isolated-task-detail">
      <TaskDetailViewInner taskId={taskId} embedded={embedded} seed={seed} />
    </TaskRuntimeProvider>
  );
}

/** Connected variant for mounts already inside TaskRuntimeProvider (AppShell). */
export function TaskDetailViewConnected({
  taskId,
  embedded = false,
  seed,
}: {
  taskId: string;
  embedded?: boolean;
  seed?: TaskRow | null;
}) {
  return <TaskDetailViewInner taskId={taskId} embedded={embedded} seed={seed} />;
}

function TaskDetailViewInner({
  taskId,
  embedded = false,
  seed,
}: {
  taskId: string;
  embedded?: boolean;
  seed?: TaskRow | null;
}) {
  const runtime = useTaskRuntime();
  const mutationCoordinator = runtime.mutationCoordinator.coordinator;
  const readCoordinator = runtime.readCoordinator as TaskReadCoordinator<TaskDetail>;
  const sessionEpoch = runtime.sessionEpoch;
  const feedback = runtime.feedback;

  const detailKey = useMemo(
    () => buildTaskQueryKey({ mode: "detail", taskId, sessionEpoch }),
    [taskId, sessionEpoch],
  );
  /** Civil-day context for every date phrase. Derived once per mount from the browser clock. */
  const clock = useMemo<TaskCivilClock>(() => browserWorkClock(), []);

  /** Authoritative canonical Task snapshot (versioned). */
  const [authoritative, setAuthoritative] = useState<TaskDetail>();
  /** Editable draft; may diverge from authoritative when dirty. */
  const [draft, setDraft] = useState<TaskDraft>();
  /** True when a newer canonical arrived while the draft was dirty (or after 409). */
  const [changedElsewhere, setChangedElsewhere] = useState(false);
  const [history, setHistory] = useState<readonly WorkHistoryRow[]>([]);
  const [historyDisclosure, setHistoryDisclosure] = useState<DisclosureEnvelope>();
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [comments, setComments] = useState<readonly TaskComment[]>([]);
  const [commentsDisclosure, setCommentsDisclosure] = useState<DisclosureEnvelope>();
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentsUnavailable, setCommentsUnavailable] = useState(false);
  const [commentsLoadingMore, setCommentsLoadingMore] = useState(false);
  const [status, setStatus] = useState("Loading task…");
  const [failure, setFailure] = useState<UserErrorPresentation>();
  const [conflict, setConflict] = useState(false);
  const [proposal, setProposal] = useState<Record<string, unknown>>();
  const [commitments, setCommitments] = useState<readonly CommitmentRow[]>([]);
  const [mutationPending, setMutationPending] = useState(false);
  const [readPending, setReadPending] = useState(false);
  const [ambiguousAttemptId, setAmbiguousAttemptId] = useState<string | null>(null);
  const [revealSubject, setRevealSubject] = useState<string | null>(null);

  const updateAttempt = useRef(createAttemptKey("task-update"));
  const authoritativeRef = useRef<TaskDetail | undefined>(undefined);
  const draftRef = useRef<TaskDraft | undefined>(undefined);
  useEffect(() => {
    authoritativeRef.current = authoritative;
  }, [authoritative]);
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const publishFeedback = useCallback(
    (kind: "success" | "error" | "conflict" | "info", message: string, eventId: string) => {
      feedback.publish({ eventId, kind, message });
    },
    [feedback],
  );

  /**
   * Apply a newer canonical Task.
   * Clean editor: advance authoritative + draft.
   * Dirty editor: preserve draft exactly; store authoritative separately; flag external change.
   */
  const applyCanonical = useCallback((next: TaskDetail, options?: { forceDraft?: boolean }) => {
    const currentDraft = draftRef.current;
    const prior = authoritativeRef.current;
    const dirty =
      !options?.forceDraft &&
      currentDraft !== undefined &&
      prior !== undefined &&
      isDraftDirty(currentDraft, prior);

    setAuthoritative(next);
    authoritativeRef.current = next;

    if (!dirty || options?.forceDraft) {
      const nextDraft = taskDraft(next);
      setDraft(nextDraft);
      draftRef.current = nextDraft;
      setChangedElsewhere(false);
      return;
    }

    // Preserve unsaved draft exactly — no silent overwrite, no auto-merge.
    setChangedElsewhere(true);
  }, []);

  const loadComments = useCallback(async () => {
    setCommentsLoading(true);
    try {
      const page = await workRequest<{ comments: readonly TaskComment[]; disclosure?: DisclosureEnvelope }>(
        `/api/tasks/${encodeURIComponent(taskId)}/comments?pageSize=20`,
      );
      setComments(requiredCollection(page.comments, "comments"));
      setCommentsDisclosure(page.disclosure);
      setCommentsUnavailable(false);
    } catch {
      // Comments are an independent collection: their unavailability never fails the Task read.
      setCommentsUnavailable(true);
    } finally {
      setCommentsLoading(false);
    }
  }, [taskId]);

  /**
   * Technical history is a separate lazy collection.
   * It is deliberately not part of the Task open path — see `TaskTechnicalDetails`.
   */
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const trail = await workRequest<{ history: readonly WorkHistoryRow[]; disclosure?: DisclosureEnvelope }>(
        `/api/tasks/${encodeURIComponent(taskId)}/history?pageSize=50`,
      );
      setHistory(requiredCollection(trail.history, "history"));
      setHistoryDisclosure(trail.disclosure);
      setHistoryLoaded(true);
    } catch (error) {
      setStatus(mapUserError(error).message);
    } finally {
      setHistoryLoading(false);
    }
  }, [taskId]);

  const loadTaskBundle = useCallback(
    async (options?: { forceDraft?: boolean }) => {
      setReadPending(true);
      try {
        const [detailResult, choices] = await Promise.all([
          readCoordinator.read(
            detailKey,
            async () => {
              const detail = await workRequest<{ task: TaskDetail }>(
                `/api/tasks/${encodeURIComponent(taskId)}`,
              );
              return detail.task;
            },
            { force: true },
          ),
          workRequest<{ commitments: readonly CommitmentRow[] }>("/api/commitments?pageSize=100"),
        ]);

        if (detailResult.silent && detailResult.outcome !== "applied" && detailResult.outcome !== "deduped") {
          return;
        }
        if (detailResult.outcome === "failed" || !detailResult.data) {
          throw detailResult.error ?? new Error("Task detail read failed");
        }

        let available = requiredCollection(choices.commitments, "commitments");
        const task = detailResult.data;
        if (task.commitment_id && !available.some((item) => item.commitment_id === task.commitment_id)) {
          const linked = await workRequest<{ commitment: CommitmentRow }>(
            `/api/commitments/${encodeURIComponent(task.commitment_id)}`,
          );
          available = [...available, linked.commitment];
        }

        setCommitments(available);
        applyCanonical(task, { forceDraft: options?.forceDraft ?? authoritativeRef.current === undefined });
        setStatus("");
        setFailure(undefined);
      } catch (error) {
        setFailure(mapUserError(error));
      } finally {
        setReadPending(false);
      }
    },
    [applyCanonical, detailKey, readCoordinator, taskId],
  );

  useEffect(() => {
    readCoordinator.retain(detailKey);
    void Promise.resolve().then(() => loadTaskBundle({ forceDraft: true }));
    void Promise.resolve().then(() => loadComments());
    return () => {
      readCoordinator.release(detailKey);
    };
  }, [detailKey, loadComments, loadTaskBundle, readCoordinator]);

  async function loadMoreHistory() {
    const after = historyDisclosure?.nextCursor;
    if (!after) return;
    setHistoryLoading(true);
    try {
      const trail = await workRequest<{ history: readonly WorkHistoryRow[]; disclosure?: DisclosureEnvelope }>(
        `/api/tasks/${encodeURIComponent(taskId)}/history?pageSize=50&after=${encodeURIComponent(after)}`,
      );
      setHistory((current) => [
        ...current,
        ...requiredCollection(trail.history, "history").filter(
          (row) => !current.some((existing) => existing.history_id === row.history_id),
        ),
      ]);
      setHistoryDisclosure(trail.disclosure);
    } catch (error) {
      setStatus(mapUserError(error).message);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadMoreComments() {
    const after = commentsDisclosure?.nextCursor;
    if (!after) return;
    setCommentsLoadingMore(true);
    try {
      const page = await workRequest<{ comments: readonly TaskComment[]; disclosure?: DisclosureEnvelope }>(
        `/api/tasks/${encodeURIComponent(taskId)}/comments?pageSize=20&after=${encodeURIComponent(after)}`,
      );
      setComments((current) => [
        ...current,
        ...requiredCollection(page.comments, "comments").filter(
          (row) => !current.some((existing) => existing.comment_id === row.comment_id),
        ),
      ]);
      setCommentsDisclosure(page.disclosure);
    } catch (error) {
      setStatus(mapUserError(error).message);
    } finally {
      setCommentsLoadingMore(false);
    }
  }

  async function fetchCurrentTask(): Promise<TaskDetail | undefined> {
    const result = await readCoordinator.read(
      detailKey,
      async () => {
        const detail = await workRequest<{ task: TaskDetail }>(
          `/api/tasks/${encodeURIComponent(taskId)}`,
        );
        return detail.task;
      },
      { force: true },
    );
    return result.data;
  }

  function handleConflict(current: unknown, values?: Record<string, unknown>) {
    const resolved = taskFromUnknown(current);
    if (resolved) {
      // Store authoritative separately; never overwrite the unsaved draft/proposal.
      setAuthoritative(resolved);
      authoritativeRef.current = resolved;
    }
    setChangedElsewhere(true);
    setConflict(true);
    if (values) setProposal(values);
    setStatus(TASK_OPERATION_CONFLICT_MESSAGE);
    // Identity/version diagnostics stay behind Technical details; the event id is not user copy.
    publishFeedback(
      "conflict",
      TASK_OPERATION_CONFLICT_MESSAGE,
      `task-conflict:${taskId}:${resolved?.version ?? "unknown"}`,
    );
  }

  /**
   * One bounded field- or section-level save intent — never a whole-Task atomic
   * patch, and never a lifecycle transition. Status, Due, Close, Cancel and
   * comments all belong to the shared operation binder.
   */
  async function applyProposal(
    values: Record<string, unknown>,
    options?: { deliberate?: boolean; expectedVersion?: number },
  ) {
    if (!authoritative || !draft) return;
    if (changedElsewhere && !options?.deliberate && !conflict) {
      setStatus(TASK_OPERATION_CONFLICT_MESSAGE);
      return;
    }

    const expectedVersion = options?.expectedVersion ?? authoritative.version;
    const material = { ...values, expectedVersion };
    const idempotencyKey = updateAttempt.current.forPayload(material);
    setStatus("Saving…");
    setConflict(false);
    setMutationPending(true);

    const draftSnapshot = { ...draft };
    const outcome = ambiguousAttemptId
      ? await mutationCoordinator.retry(ambiguousAttemptId)
      : await mutationCoordinator.mutate({
          kind: "update",
          taskId,
          expectedVersion,
          idempotencyKey,
          request: material,
          draft: draftSnapshot,
          hooks: {
            fetchCurrent: async () => fetchCurrentTask(),
            barriers: {
              onMutationStart: () => {
                readCoordinator.raiseMutationBarrier(detailKey, { entityId: taskId });
              },
            },
            reconcile: async (result) => {
              const confirmed = taskFromUnknown(result);
              if (confirmed) {
                readCoordinator.applyConfirmed(detailKey, confirmed, { entityId: taskId });
                applyCanonical(confirmed, { forceDraft: true });
              } else {
                readCoordinator.raiseMutationBarrier(detailKey, { entityId: taskId });
                await loadTaskBundle({ forceDraft: true });
              }
            },
            feedback: async (_result, phase: MutationPhase) => {
              if (phase === "confirmed") {
                publishFeedback("success", TASK_SAVED_MESSAGE, `task-update-ok:${idempotencyKey}`);
              }
            },
          },
          dispatch: async ({ request, idempotencyKey: key, expectedVersion: version }) =>
            workRequest(`/api/tasks/${encodeURIComponent(taskId)}`, {
              method: "PATCH",
              body: JSON.stringify({ ...request, expectedVersion: version, idempotencyKey: key }),
            }),
        });

    setMutationPending(false);

    if (outcome.refused) {
      setStatus(outcome.reason ?? "Mutation refused.");
      return;
    }

    // Coordinator preserves draft on conflict/failure — reaffirm local draft identity.
    if (outcome.draft && typeof outcome.draft === "object") {
      setDraft(outcome.draft as TaskDraft);
      draftRef.current = outcome.draft as TaskDraft;
    }

    if (outcome.state.phase === "conflict") {
      // Conflict is definitive for the stale version; rotate attempt identity for the next deliberate try.
      updateAttempt.current.succeeded();
      setAmbiguousAttemptId(null);
      handleConflict(outcome.state.conflictCurrent, values);
      return;
    }

    if (outcome.state.phase === "confirmed") {
      updateAttempt.current.succeeded();
      setAmbiguousAttemptId(null);
      setProposal(undefined);
      setChangedElsewhere(false);
      setConflict(false);
      setStatus(TASK_SAVED_MESSAGE);
      return;
    }

    if (outcome.state.phase === "ambiguous") {
      setAmbiguousAttemptId(outcome.attemptId);
      setStatus(TASK_OPERATION_AMBIGUOUS_MESSAGE);
      publishFeedback("info", TASK_OPERATION_AMBIGUOUS_MESSAGE, `task-update-ambiguous:${idempotencyKey}`);
      return;
    }

    updateAttempt.current.succeeded();
    setAmbiguousAttemptId(null);
    setStatus(TASK_OPERATION_FAILURE_MESSAGE);
    publishFeedback("error", TASK_OPERATION_FAILURE_MESSAGE, `task-update-fail:${idempotencyKey}`);
  }

  function discardDraftForLatest() {
    if (!authoritative) return;
    applyCanonical(authoritative, { forceDraft: true });
    setConflict(false);
    setProposal(undefined);
    setStatus("Loaded the latest version.");
  }

  // Blind saves stay locked while an unseen newer canonical or conflict is outstanding.
  const controlsLocked = mutationPending || changedElsewhere;

  if (failure) {
    return (
      <SurfaceState kind="unavailable" title={failure.title} detail={failure.message} diagnostic={failure.diagnostic}>
        <Button className="mt-3" variant="secondary" pending={readPending} onClick={() => void loadTaskBundle({ forceDraft: true })}>
          Retry Task read
        </Button>
      </SurfaceState>
    );
  }
  if (!authoritative || !draft) {
    if (!seed) return <LoadingStatus label={status} />;
    // A projection paints immediately but owns no trustworthy version, so it renders
    // read-only: no Status, Due, Close or comment control is mounted at all.
    return (
      <div data-testid="task-detail-hydrating">
        <TaskCompact model={toTaskPresentationModel(seed, { clock, canMutate: false })} />
        <LoadingStatus label={status} />
      </div>
    );
  }

  return (
    <article className="mx-auto max-w-4xl pb-[env(safe-area-inset-bottom)]">
      {embedded ? null : (
        <Link href="/work?view=all-open" className="text-sm text-moss-green underline">
          ← Work
        </Link>
      )}

      {changedElsewhere ? (
        <section role="alert" data-testid="task-changed-elsewhere" className="mt-4 rounded-lg border border-moss-coral-strong p-3 text-sm">
          <h2 className="font-semibold">Task changed elsewhere</h2>
          <p className="mt-1">{TASK_OPERATION_CONFLICT_MESSAGE}</p>
          <p className="mt-1 text-muted">Latest saved title “{authoritative.title}”. Your draft was preserved.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={discardDraftForLatest}>
              Discard edits and load latest
            </Button>
            {conflict && proposal ? (
              <Button
                type="button"
                variant="secondary"
                pending={mutationPending}
                onClick={() => void applyProposal(proposal, { deliberate: true })}
              >
                Reapply my change to the latest version
              </Button>
            ) : null}
          </div>
        </section>
      ) : null}

      <p role="status" className="mt-4 text-sm text-muted">
        {status}
      </p>
      <div className="mt-2">
        <Button
          type="button"
          variant="secondary"
          pending={readPending}
          onClick={() => void loadTaskBundle()}
          data-testid="task-detail-refresh"
        >
          Refresh task
        </Button>
      </div>

      {/*
        Keyed on the Task, not its version. The binder adopts a newer
        authoritative seed in place, so a bounded field save advances its write
        authority without remounting it — remounting would also discard an
        unsent comment left awaiting retry.
      */}
      <TaskOperationSurface
        key={`task-operations:${taskId}`}
        taskId={taskId}
        task={authoritative}
        draft={draft}
        clock={clock}
        embedded={embedded}
        locked={controlsLocked}
        updatePending={mutationPending}
        commitmentLabel={
          authoritative.commitment_id
            ? commitments.find((item) => item.commitment_id === authoritative.commitment_id)?.title ?? null
            : "No commitment linked"
        }
        comments={comments}
        commentsLoading={commentsLoading}
        commentsUnavailable={commentsUnavailable}
        commentsHasMore={Boolean(commentsDisclosure?.nextCursor)}
        commentsLoadingMore={commentsLoadingMore}
        onDraftChange={setDraft}
        onSaveFields={(values, clearFields, expectedVersion) =>
          void applyProposal(clearFields.length ? { ...values, clearFields } : values, { expectedVersion })
        }
        onCommentsSettled={() => void loadComments()}
        onLoadMoreComments={() => void loadMoreComments()}
        onRetryLoadComments={() => void loadComments()}
        renderTechnicalDetails={(current) => (
          <TaskTechnicalDetails
            task={current}
            clock={clock}
            history={history}
            historyDisclosure={historyDisclosure}
            historyLoaded={historyLoaded}
            historyLoading={historyLoading}
            onExpand={() => void loadHistory()}
            onContinueHistory={() => void loadMoreHistory()}
            onRevealEvidence={(ref) => setRevealSubject(ref)}
          />
        )}
      />

      {revealSubject ? <RevealDialog open onClose={() => setRevealSubject(null)} subjectId={revealSubject} /> : null}
    </article>
  );
}

interface TaskOperationSurfaceProps {
  readonly taskId: string;
  /** Canonical, versioned Task snapshot from this surface's own detail read. */
  readonly task: TaskDetail;
  readonly draft: TaskDraft;
  readonly clock: TaskCivilClock;
  readonly embedded: boolean;
  /** A newer unseen canonical or an in-flight bounded save locks blind writes. */
  readonly locked: boolean;
  readonly updatePending: boolean;
  readonly commitmentLabel: string | null;
  readonly comments: readonly TaskComment[];
  readonly commentsLoading: boolean;
  readonly commentsUnavailable: boolean;
  readonly commentsHasMore: boolean;
  readonly commentsLoadingMore: boolean;
  onDraftChange(next: TaskDraft): void;
  onSaveFields(
    values: Record<string, unknown>,
    clearFields: readonly string[],
    expectedVersion: number,
  ): void;
  onCommentsSettled(): void;
  onLoadMoreComments(): void;
  onRetryLoadComments(): void;
  renderTechnicalDetails(current: TaskDetail): ReactNode;
}

/**
 * Task detail operations, bound once through the shared binder.
 *
 * Status and Due are optimistic, Close and Cancel are pessimistic, comments are
 * append-only pending rows — all of that is the binder's, not this surface's.
 * Bounded title / description / priority / planning saves stay with the owning
 * detail view, which is the only holder of the dirty draft.
 */
function TaskOperationSurface({
  taskId,
  task,
  draft,
  clock,
  embedded,
  locked,
  updatePending,
  commitmentLabel,
  comments,
  commentsLoading,
  commentsUnavailable,
  commentsHasMore,
  commentsLoadingMore,
  onDraftChange,
  onSaveFields,
  onCommentsSettled,
  onLoadMoreComments,
  onRetryLoadComments,
  renderTechnicalDetails,
}: TaskOperationSurfaceProps) {
  // The seed is canonical: it is this surface's own `/api/tasks/{id}` read, never
  // a list or search projection, so it may authorize a versioned write directly.
  const ops = useTaskOperations({ taskId, task, authoritative: true }, { clock });

  const current = ops.task ?? task;
  const canMutate = ops.canMutate && !locked;
  const busy = updatePending || ops.pending !== null;

  /** Status and Due render their optimistic value; every other field is canonical. */
  const displayed = useMemo<TaskDetail>(
    () => ({ ...current, lifecycle_state: ops.status.value, due_at: ops.due.value }),
    [current, ops.status.value, ops.due.value],
  );
  const model = toTaskPresentationModel(displayed, { clock, canMutate });

  const writeVersion = typeof current.version === "number" ? current.version : task.version;

  async function addComment(body: string) {
    await ops.addComment(body);
    onCommentsSettled();
  }

  async function retryComment(localId: string) {
    await ops.retryComment(localId);
    onCommentsSettled();
  }

  return (
    <>
      <header className={embedded ? "" : "mt-4"}>
        <h1 className="text-2xl font-semibold text-moss-slate">{current.title}</h1>
        <p className="mt-1 text-sm text-muted">{model.statusLabel} · {model.due.phrase}</p>
      </header>

      {ops.conflict ? (
        <section
          role="alert"
          data-testid="task-operation-conflict"
          className="mt-4 rounded-lg border border-moss-coral-strong p-3 text-sm"
        >
          <p>{TASK_OPERATION_CONFLICT_MESSAGE}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" variant="secondary" pending={busy} onClick={() => void ops.reapply()}>
              Try my change again
            </Button>
            <Button type="button" variant="secondary" onClick={ops.dismissConflict}>
              Keep the latest details
            </Button>
          </div>
        </section>
      ) : null}

      <TaskDetailSections
        model={model}
        task={current}
        clock={clock}
        title={draft.title}
        titleDirty={draft.title !== task.title}
        priority={current.priority}
        description={draft.description}
        descriptionDirty={draft.description !== (task.description ?? "")}
        disabled={!canMutate || busy}
        pending={busy}
        projectLabel={null}
        situationLabel={null}
        commitmentLabel={commitmentLabel}
        roleLabel={current.role === "follow_up" ? "Follow up" : "No role set"}
        statusControl={
          <TaskStatusControl
            value={ops.status.value}
            disabled={!canMutate}
            pending={busy}
            conflict={locked || ops.conflict !== null}
            onChange={(next) => void ops.changeStatus(next)}
          />
        }
        dueControl={
          <TaskDueControl
            value={ops.due.value}
            clock={clock}
            disabled={!canMutate}
            pending={busy}
            conflict={locked || ops.conflict !== null}
            onChange={(nextIso) => void ops.changeDue(nextIso)}
          />
        }
        closeControl={
          <TaskCloseControl
            taskTitle={current.title}
            disabled={!canMutate}
            pending={busy}
            onClose={() => void ops.closeTask()}
            onCancelTask={() => void ops.cancelTask()}
          />
        }
        comments={
          <TaskComments
            comments={comments}
            pending={ops.pendingComments.map((row) => ({
              localId: row.localId,
              body: row.body,
              // The thread has two truthful states; an unconfirmed attempt is not persisted.
              status: row.state === "pending" ? ("pending" as const) : ("failed" as const),
              message:
                row.state === "ambiguous"
                  ? TASK_OPERATION_AMBIGUOUS_MESSAGE
                  : row.state === "failed"
                    ? TASK_OPERATION_FAILURE_MESSAGE
                    : undefined,
            }))}
            loading={commentsLoading}
            unavailable={commentsUnavailable}
            hasMore={commentsHasMore}
            loadingMore={commentsLoadingMore}
            disabled={!canMutate}
            submitting={ops.pending === "commentCreate"}
            onSubmit={(body) => void addComment(body)}
            onRetry={(localId) => void retryComment(localId)}
            onLoadMore={onLoadMoreComments}
            onRetryLoad={onRetryLoadComments}
          />
        }
        technicalDetails={renderTechnicalDetails(current)}
        onTitleChange={(next) => onDraftChange({ ...draft, title: next })}
        onTitleSave={() => onSaveFields({ title: draft.title.trim() }, [], writeVersion)}
        onPriorityChange={(next) =>
          onSaveFields(next ? { priority: next } : {}, next ? [] : ["priority"], writeVersion)
        }
        onDescriptionChange={(next) => onDraftChange({ ...draft, description: next })}
        onDescriptionSave={() =>
          onSaveFields(
            draft.description ? { description: draft.description } : {},
            draft.description ? [] : ["description"],
            writeVersion,
          )
        }
        onPlannedForChange={(next) =>
          onSaveFields(next ? { scheduledAt: next } : {}, next ? [] : ["scheduled_at"], writeVersion)
        }
        onSnoozedUntilChange={(next) =>
          onSaveFields(next ? { deferredUntil: next } : {}, next ? [] : ["deferred_until"], writeVersion)
        }
        onArchivedChange={(next) => onSaveFields({ archived: next }, [], writeVersion)}
      />
    </>
  );
}

interface CommitmentDraft { summary: string; counterparty: string; dueAt: string }
function commitmentDraft(record: CommitmentDetail): CommitmentDraft { return { summary: record.title, counterparty: record.counterparty_person_id ?? "", dueAt: dateInput(record.due_date) }; }
function followUpProjection(source: { follow_up_task?: unknown }): CommitmentFollowUp {
  if (!("follow_up_task" in source)) return { state: "unavailable", reason: "The server did not return a follow-up Task projection." };
  if (source.follow_up_task === null) return { state: "empty" };
  if (typeof source.follow_up_task !== "object" || source.follow_up_task === null) return { state: "unavailable", reason: "The server returned an unreadable follow-up Task projection." };
  const task = source.follow_up_task as Record<string, unknown>;
  const lifecycle = task.lifecycle_state;
  if (typeof task.task_id !== "string" || typeof task.title !== "string" || typeof lifecycle !== "string" || !["open", "in_progress", "waiting", "blocked", "completed", "cancelled"].includes(lifecycle)) return { state: "unavailable", reason: "The server returned an incomplete follow-up Task projection." };
  return { state: "linked", task_id: task.task_id, title: task.title, lifecycle_state: lifecycle as TaskLifecycle };
}

export function CommitmentDetailView({ commitmentId, embedded = false }: { commitmentId: string; embedded?: boolean }) {
  const [record, setRecord] = useState<CommitmentDetail>(); const [draft, setDraft] = useState<CommitmentDraft>(); const [history, setHistory] = useState<readonly WorkHistoryRow[]>([]); const [historyDisclosure, setHistoryDisclosure] = useState<DisclosureEnvelope>();
  const [followUp, setFollowUp] = useState<CommitmentFollowUp>({ state: "unavailable", reason: "Follow-up Task context has not been read." });
  const [counterparties, setCounterparties] = useState<readonly CounterpartyOption[]>([]); const [counterpartiesTruncated, setCounterpartiesTruncated] = useState(false);
  const [status, setStatus] = useState("Loading commitment…"); const [failure, setFailure] = useState<UserErrorPresentation>(); const [conflict, setConflict] = useState(false); const [proposal, setProposal] = useState<Record<string, unknown>>(); const [closureNote, setClosureNote] = useState("");
  const updateAttempt = useRef(createAttemptKey("commitment-update")); const closeAttempt = useRef(createAttemptKey("commitment-close")); const closureCaptureAttempt = useRef(createAttemptKey("commitment-closure"));
  const load = useCallback(async () => { try { const [detail, trail] = await Promise.all([workRequest<{ commitment: CommitmentDetail; follow_up_task?: unknown; counterparty_options?: readonly CounterpartyOption[]; counterparty_options_truncated?: boolean }>(`/api/commitments/${encodeURIComponent(commitmentId)}`), workRequest<{ history: readonly WorkHistoryRow[]; disclosure?: DisclosureEnvelope }>(`/api/commitments/${encodeURIComponent(commitmentId)}/history?pageSize=50`)]); const options = requiredCollection(detail.counterparty_options, "counterparty_options"); setCounterparties(detail.commitment.counterparty && !options.some((item) => item.person_id === detail.commitment.counterparty?.person_id) ? [...options, detail.commitment.counterparty] : options); setCounterpartiesTruncated(Boolean(detail.counterparty_options_truncated)); setRecord(detail.commitment); setDraft(commitmentDraft(detail.commitment)); setFollowUp(followUpProjection(detail)); setHistory(requiredCollection(trail.history, "history")); setHistoryDisclosure(trail.disclosure); setStatus(""); setFailure(undefined); } catch (error) { setFailure(mapUserError(error)); } }, [commitmentId]); useEffect(() => { void Promise.resolve().then(load); }, [load]);
  async function loadMoreHistory() { const after = historyDisclosure?.nextCursor; if (!after) return; setStatus("Reading more Commitment history…"); try { const trail = await workRequest<{ history: readonly WorkHistoryRow[]; disclosure?: DisclosureEnvelope }>(`/api/commitments/${encodeURIComponent(commitmentId)}/history?pageSize=50&after=${encodeURIComponent(after)}`); setHistory((current) => [...current, ...requiredCollection(trail.history, "history").filter((row) => !current.some((existing) => existing.history_id === row.history_id))]); setHistoryDisclosure(trail.disclosure); setStatus(""); } catch (error) { setStatus(mapUserError(error).message); } }
  async function applyProposal(values: Record<string, unknown>) { if (!record) return; const material = { ...values, expectedVersion: record.version }; setStatus("Saving commitment…"); setConflict(false); try { await workRequest(`/api/commitments/${encodeURIComponent(commitmentId)}`, { method: "PATCH", body: JSON.stringify({ ...material, idempotencyKey: updateAttempt.current.forPayload(material) }) }); updateAttempt.current.succeeded(); setProposal(undefined); setStatus("Commitment update persisted."); await load(); } catch (error) { const problem = error as ApiFailure; const isConflict = problem.status === 409; setConflict(isConflict); setProposal(isConflict ? values : undefined); if (isConflict && problem.current) setRecord(problem.current as CommitmentDetail); setStatus(isConflict ? "Conflict: compare every canonical field with the retained proposal, then reapply deliberately." : mapUserError(problem).message); if (isDefinitiveAttemptFailure(error)) updateAttempt.current.succeeded(); } }
  async function update(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!draft) return; await applyProposal({ summary: draft.summary, counterpartyPersonId: draft.counterparty, dueAt: draft.dueAt ? new Date(draft.dueAt).toISOString() : undefined, clearDueAt: !draft.dueAt }); }
  async function close(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!record) return; setStatus("Saving closure evidence…"); try { const evidence = await captureEvidence(closureNote, "commitment-closure", closureCaptureAttempt.current.forPayload({ note: closureNote })); const material = { expectedVersion: record.version, closureEvidenceRef: evidence }; await workRequest(`/api/commitments/${encodeURIComponent(commitmentId)}/close`, { method: "POST", body: JSON.stringify({ ...material, idempotencyKey: closeAttempt.current.forPayload(material) }) }); closureCaptureAttempt.current.succeeded(); closeAttempt.current.succeeded(); setClosureNote(""); await load(); setStatus("Commitment explicitly closed."); } catch (error) { const problem = error as ApiFailure; if (problem.status === 409 && problem.current) { setRecord(problem.current as CommitmentDetail); setDraft(commitmentDraft(problem.current as CommitmentDetail)); } if (isDefinitiveAttemptFailure(error)) closeAttempt.current.succeeded(); setStatus(mapUserError(problem).message); } }
  if (failure) return <SurfaceState kind="unavailable" title={failure.title} detail={failure.message} diagnostic={failure.diagnostic}><Button className="mt-3" variant="secondary" onClick={() => void load()}>Retry Commitment read</Button></SurfaceState>;
  if (!record || !draft) return <LoadingStatus label={status} />;
  return <article className="mx-auto max-w-4xl">{embedded ? null : <Link href="/work?view=commitments" className="text-sm text-moss-green underline">← Commitments</Link>}<header className={embedded ? "" : "mt-4"}><h1 className="text-2xl font-semibold text-moss-slate">{record.title}</h1><p className="mt-1 text-sm text-muted">{record.counterparty?.display_name ?? "Counterparty not resolved"} · {display(record.direction)} · {record.state} · version {record.version}</p></header>{conflict && proposal ? <Conflict title="Canonical versus proposed"><dl><dt>Summary</dt><dd>Canonical: {record.title} · Proposed: {String(proposal.summary ?? "")}</dd><dt>Counterparty</dt><dd>Canonical: {counterpartyLabel(record.counterparty_person_id, counterparties)} · Proposed: {counterpartyLabel(proposal.counterpartyPersonId, counterparties)}</dd><dt>Due</dt><dd>Canonical: {record.due_date ?? "Not set"} · Proposed: {String(proposal.dueAt ?? "Clear")}</dd></dl><Button type="button" variant="secondary" onClick={() => void applyProposal(proposal)}>Reapply proposed update to version {record.version}</Button></Conflict> : null}<p role="status" className="mt-4 text-sm text-muted">{status}</p><div className="mt-6 grid gap-6 lg:grid-cols-2"><form onSubmit={update} className="grid gap-4 rounded-xl border border-moss-slate/15 bg-surface p-4"><h2 className="font-semibold">Edit commitment</h2><Labeled label="Summary"><Input value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} required /></Labeled><Labeled label="Counterparty"><select value={draft.counterparty} onChange={(event) => setDraft({ ...draft, counterparty: event.target.value })} required className="h-10 rounded-md border bg-surface px-3">{counterparties.map((item) => <option key={item.person_id} value={item.person_id}>{item.display_name}</option>)}</select></Labeled>{counterpartiesTruncated ? <p className="text-xs text-muted">Showing the first 100 verified people, plus this Commitment&rsquo;s current counterparty.</p> : null}<Labeled label="Due"><Input type="datetime-local" value={draft.dueAt} onChange={(event) => setDraft({ ...draft, dueAt: event.target.value })} /></Labeled><Button type="submit" disabled={counterparties.length === 0}>Save commitment</Button></form><form onSubmit={close} className="grid content-start gap-4 rounded-xl border border-moss-slate/15 bg-surface p-4"><h2 className="font-semibold">Close explicitly</h2><Labeled label="Closure note"><Textarea value={closureNote} onChange={(event) => setClosureNote(event.target.value)} required /></Labeled><Button type="submit" variant="danger" disabled={record.state === "closed"}>{record.state === "closed" ? "Already closed" : "Close commitment"}</Button></form></div><CommitmentFollowUpPanel projection={followUp} /><Evidence subject="Commitment" state={record.evidence_state} origin={record.origin_evidence_ref} closure={record.closure_evidence_ref} closedAt={record.closed_at} reviewDecisionId={record.accepted_by_review_decision_id} /><History subject="Commitment" rows={history} disclosure={historyDisclosure} onContinue={() => void loadMoreHistory()} /></article>;
}

function Conflict({ title, children }: { title: string; children: ReactNode }) { return <section role="alert" className="mt-4 rounded-lg border border-moss-coral-strong p-3 text-sm"><h2 className="font-semibold">{title}</h2>{children}</section>; }
function CommitmentFollowUpPanel({ projection }: { projection: CommitmentFollowUp }) { return <section aria-labelledby="follow-up-heading" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4"><h2 id="follow-up-heading" className="font-semibold">Follow-up execution</h2>{projection.state === "linked" ? <div className="mt-3 text-sm"><Link href={`/work/tasks/${encodeURIComponent(projection.task_id)}`} className="font-medium text-moss-green underline">{projection.title}</Link><p className="text-muted">Task state: {formatTaskStatus(projection.lifecycle_state)}</p></div> : projection.state === "empty" ? <p className="mt-2 text-sm text-muted">No follow-up Task is linked.</p> : <div className="mt-2 text-sm"><p className="font-medium">Follow-up Task context is unavailable.</p><p className="text-muted">{projection.reason}</p></div>}</section>; }
interface EvidenceProps {
  subject: "Task" | "Commitment";
  state: string;
  originKind?: "direct_principal" | "evidence" | string | null;
  origin: string | null;
  closure: string | null;
  closedAt: string | null;
  acceptanceKind?: string | null;
  reviewDecisionId: string | null;
  closureHistoryId?: string | null;
}

function Evidence({ subject, state, originKind, origin, closure, closedAt, acceptanceKind, reviewDecisionId, closureHistoryId }: EvidenceProps) {
  const [revealSubject, setRevealSubject] = useState<string | null>(null);
  const hasOriginEvidence = typeof origin === "string" && origin.length > 0;
  return <>
    <section aria-labelledby="evidence-heading" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4">
      <h2 id="evidence-heading" className="font-semibold">Why / provenance</h2>
      <p className="mt-1 text-xs text-muted">Evidence content is never loaded automatically. Reveal is an explicit, server-governed read.</p>
      <dl className="mt-3 grid gap-3 text-sm">
        <div><dt className="text-muted">Evidence state</dt><dd>{display(state)}</dd></div>
        <div>
          <dt className="text-muted">Origin</dt>
          {hasOriginEvidence ? (
            <>
              <dd>Recorded origin evidence</dd>
              <dd className="break-all font-mono text-xs text-muted">Reference {origin}</dd>
              <Button className="mt-2" type="button" variant="secondary" onClick={() => setRevealSubject(origin)}>View origin evidence</Button>
            </>
          ) : (
            <>
              <dd>Direct principal authoring</dd>
              {originKind ? <dd className="text-xs text-muted">{display(originKind)}</dd> : null}
            </>
          )}
        </div>
        <div><dt className="text-muted">Acceptance</dt><dd>{acceptanceKind ? display(acceptanceKind) : reviewDecisionId ? "Accepted through review" : "No review acceptance was returned"}</dd>{reviewDecisionId ? <dd className="break-all font-mono text-xs text-muted">Review decision {reviewDecisionId}</dd> : null}</div>
        <div><dt className="text-muted">Closure</dt>{closure ? <><dd>Closure evidence recorded{closedAt ? <> at <time dateTime={closedAt}>{new Date(closedAt).toLocaleString()}</time></> : ""}</dd><dd className="break-all font-mono text-xs text-muted">Reference {closure}</dd>{closureHistoryId ? <dd className="break-all font-mono text-xs text-muted">History receipt {closureHistoryId}</dd> : null}<Button className="mt-2" type="button" variant="secondary" onClick={() => setRevealSubject(closure)}>View closure evidence</Button></> : <dd>{closedAt ? `${subject} is terminal, but closure evidence metadata was unavailable.` : `${subject} is not closed.`}</dd>}</div>
      </dl>
    </section>
    {revealSubject ? <RevealDialog open onClose={() => setRevealSubject(null)} subjectId={revealSubject} /> : null}
  </>;
}

function History({ subject, rows, closureHistoryId, disclosure, onContinue }: { subject: string; rows: readonly WorkHistoryRow[]; closureHistoryId?: string | null; disclosure?: DisclosureEnvelope; onContinue: () => void }) { return <section aria-labelledby="history-heading" className="mt-6"><h2 id="history-heading" className="font-semibold">History</h2>{rows.length ? <ol className="mt-3 grid gap-2">{rows.map((row)=><li key={row.history_id} className="rounded-lg border border-moss-slate/15 bg-surface p-3 text-sm"><span className="font-medium">{display(row.action)}</span> · {row.outcome} · v{row.before_version}→v{row.after_version}{row.history_id === closureHistoryId ? <strong className="ml-2 text-xs">Closure receipt</strong> : null}<time className="block text-xs text-muted" dateTime={row.recorded_at}>{new Date(row.recorded_at).toLocaleString()}</time></li>)}</ol> : <p className="mt-2 text-sm text-muted">No history rows were returned.</p>}{disclosure ? <aside aria-label={`${subject} history disclosure`} className="mt-3 rounded-lg border border-moss-slate/15 bg-surface p-3 text-xs text-muted"><p>Authority: {disclosure.authority.replaceAll("_", " ")} · Coverage: {disclosure.coverage} · Freshness: {disclosure.freshnessAt ? new Date(disclosure.freshnessAt).toLocaleString() : "not disclosed"} · Truncated: {disclosure.truncated ? "yes" : "no"}</p>{disclosure.limitations.length ? <ul className="mt-1 list-inside list-disc">{disclosure.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}</aside> : null}{disclosure?.nextCursor ? <Button className="mt-3" type="button" variant="secondary" onClick={onContinue}>Continue {subject} history</Button> : null}</section>; }
