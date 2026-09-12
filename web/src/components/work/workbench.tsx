"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { MutationFeedbackEvent } from "@/components/ui/mutation-feedback";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import { Textarea } from "@/components/ui/textarea";
import { CommitmentDetailView } from "@/components/work/work-detail";
import { TaskCompactSheet } from "@/components/tasks/task-compact-sheet";
import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import { WorkPerspectives } from "@/components/work/work-perspectives";
import { useTaskRuntime } from "@/components/work/task-runtime-provider";
import { useTaskFreshness } from "@/components/work/use-task-freshness";
import { browserWorkClock, captureEvidence, createAttemptKey, isDefinitiveAttemptFailure, requiredCollection, workRequest } from "@/lib/api/work-client";
import { COMMITMENT_FILTERS, parseWorkUrlState, TASK_VIEWS, WORK_PERSPECTIVES, type CommitmentFilter, type TaskView, type WorkPerspective, type WorkUrlState, type WorkView } from "@/lib/api/work-url";
import { buildTaskQueryKey, serializeTaskQueryKey } from "@/lib/task/query-key";
import type { TaskReadCoordinator } from "@/lib/task/read-coordinator";
import { mapUserError } from "@/lib/ui/user-error";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type {
  CommitmentRow,
  CounterpartyOption,
  TaskBulkConfirmReceipt,
  TaskBulkMutation,
  TaskBulkPreviewReceipt,
  TaskDetail,
  TaskPriority,
  TaskRow,
  WaitingOnRow,
} from "@/contracts/work";

function Labeled({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="grid gap-1 text-sm font-medium text-text-primary"><span>{label}</span>{children}{hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}</label>;
}

function StatusNote({ message, details, className = "mt-4 rounded-lg border border-border bg-surface p-3" }: { message: string; details?: string; className?: string }) {
  if (!message) return null;
  return (
    <div className={className}>
      <p role="status" className="text-sm text-muted">{message}</p>
      {details ? (
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer font-medium text-text-primary">Details</summary>
          <p className="mt-2 whitespace-pre-wrap">{details}</p>
        </details>
      ) : null}
    </div>
  );
}

const LABEL: Record<WorkView, string> = { overdue: "Overdue", today: "Today", upcoming: "Upcoming", unscheduled: "Unscheduled", waiting: "Waiting", blocked: "Blocked", "recently-updated": "Recently updated", "all-open": "All open", completed: "Completed", commitments: "Commitments" };
const PERSPECTIVE_LABEL: Record<WorkPerspective, string> = { list: "List", board: "Board", calendar: "Calendar" };
const COMMITMENT_LABEL: Record<CommitmentFilter, string> = { "all-open": "Open", due: "Commitments due", "recently-updated": "Recently updated", "waiting-on": "Waiting on", closed: "Closed", all: "All" };
const DEFAULT_STATE = parseWorkUrlState({});
const CLOCK_VIEWS = new Set<string>(["overdue", "today", "upcoming", "recently-updated"]);

interface TaskListPayload {
  readonly tasks: readonly TaskRow[];
  readonly disclosure?: DisclosureEnvelope;
}

function sync(parameters: Record<string, string | undefined>) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(parameters)) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  history.replaceState(null, "", url);
}

export function Workbench({ initialState = DEFAULT_STATE }: { initialState?: WorkUrlState }) {
  const runtime = useTaskRuntime();
  const [view, setView] = useState<WorkView>(initialState.view);
  const [perspective, setPerspective] = useState<WorkPerspective>(initialState.perspective);
  const [rows, setRows] = useState<readonly TaskRow[] | readonly CommitmentRow[] | readonly WaitingOnRow[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "failed">("loading");
  const [readError, setReadError] = useState<unknown>();
  const [disclosure, setDisclosure] = useState<DisclosureEnvelope>();
  const [queryDraft, setQueryDraft] = useState(initialState.q);
  const [committedQuery, setCommittedQuery] = useState(initialState.q);
  const [archiveMode, setArchiveMode] = useState(initialState.archived);
  const [commitmentFilter, setCommitmentFilter] = useState(initialState.commitment);
  const [cursor, setCursor] = useState(initialState.cursor);
  const [timezone, setTimezone] = useState(initialState.tz);
  const [nextCursor, setNextCursor] = useState("");
  const [partial, setPartial] = useState(false);
  const [creatingCommitment, setCreatingCommitment] = useState(false);
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(initialState.archived === "only");
  const [lastTaskView, setLastTaskView] = useState<TaskView>(
    initialState.view === "commitments" ? "today" : (initialState.view as TaskView),
  );
  const [selectedTaskIds, setSelectedTaskIds] = useState<readonly string[]>([]);
  const [detail, setDetail] = useState<{ type: "task" | "commitment"; id: string; title: string } | undefined>(
    initialState.task ? { type: "task", id: initialState.task, title: "Task detail" }
      : initialState.commitmentId ? { type: "commitment", id: initialState.commitmentId, title: "Commitment detail" }
      : undefined,
  );
  const commitmentGeneration = useRef(0);
  const activeCommitmentRead = useRef<AbortController | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);
  const workHeading = useRef<HTMLHeadingElement | null>(null);
  /**
   * The row that currently holds focus, and where it sits in the visible list.
   *
   * Focus restoration reacts to focus actually being lost rather than predicting
   * which write will lose it. An earlier design armed a handoff when a mutation
   * was dispatched and spent it on a later list change; because a list change
   * carries no Task identity, an unrelated read — a freshness poll, or a second
   * row's write confirming first — could spend the handoff armed for another
   * row, and when that row really did go there was nothing left to catch focus.
   * Recording where focus is cannot make that mistake: there is one entry, it is
   * whichever row the user is actually in, and it is only acted on when that
   * exact row leaves and focus has genuinely fallen to the document body.
   */
  const focusedRow = useRef<{ readonly taskId: string; readonly index: number } | null>(null);


  /** The Task rows currently on screen, in the order the server returned them. */
  function visibleRowElements(): readonly HTMLElement[] {
    const list = document.querySelector('[aria-label="Work list"]');
    return list ? Array.from(list.querySelectorAll<HTMLElement>("[data-work-item]")) : [];
  }

  /** The title/details trigger of a row — the stable thing to hand focus to. */
  function rowTarget(row: HTMLElement | undefined): HTMLElement | null {
    return row?.querySelector<HTMLElement>("a[href]") ?? null;
  }

  /**
   * Remember which row focus is in, whenever it moves.
   *
   * `focusin` bubbles, so one handler on the list covers every row and every
   * control inside one, including controls a row mounts after this renders.
   */
  function rememberFocusedRow(event: React.FocusEvent<HTMLElement>) {
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-work-item]");
    const taskId = row?.getAttribute("data-work-item") ?? null;
    if (!taskId) return;
    const index = visibleRowElements().findIndex(
      (candidate) => candidate.getAttribute("data-work-item") === taskId,
    );
    focusedRow.current = { taskId, index: Math.max(0, index) };
  }

  /*
    Restore focus after a list change took it away.

    Runs on the rows the server returned, not on a mutation callback: the row
    that was mutated may already be unmounted by then, so nothing it fires can
    be relied on.

    There is exactly one condition, and it is the whole of the design: focus
    must have actually fallen to the document body. That is what makes this
    safe for any list change whatever its cause — a write confirming, a
    freshness poll, pagination, a change of view, a second row's write landing
    first. A change that does not cost the user their focus is left alone, so
    nothing has to be armed when a write is dispatched, stood down when it
    fails, or cleared on navigation. An earlier design predicted which write
    would cost focus and armed a handoff for it; because a list change carries
    no Task identity, an unrelated read could spend the handoff armed for
    another row, and focus was lost precisely when it mattered most.

    Placement prefers the Task the user was actually in, if the list still has
    it; otherwise whatever now occupies its place, then the row before it, and
    only then the heading — never nothing.
  */
  useEffect(() => {
    const lost = focusedRow.current;
    if (!lost) return;
    const frame = requestAnimationFrame(() => {
      /*
        Focus is still somewhere real: the row survived and kept it, or the
        detail sheet, a dialog, or the user's own click took it deliberately.
        Only focus that has fallen to nothing is ours to place.
      */
      const active = document.activeElement;
      if (active && active !== document.body) return;
      focusedRow.current = null;
      const after = visibleRowElements();
      const survivor = after.find(
        (candidate) => candidate.getAttribute("data-work-item") === lost.taskId,
      );
      const target =
        rowTarget(survivor) ??
        rowTarget(after[lost.index]) ??
        (lost.index > 0 ? rowTarget(after[lost.index - 1]) : null);
      if (target) {
        target.focus();
        return;
      }
      workHeading.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [rows]);
  const newTaskTrigger = useRef<HTMLButtonElement | null>(null);

  const taskMode = view !== "commitments";
  const taskViewForQuery: TaskView = taskMode ? (view as TaskView) : lastTaskView;
  const needsClock = CLOCK_VIEWS.has(taskViewForQuery);
  const clock = needsClock ? browserWorkClock(new Date(), timezone || undefined) : null;
  const queryWorkDate = needsClock ? (clock?.workDate ?? null) : null;
  const queryTimezone = needsClock ? (clock?.timezone ?? timezone ?? null) : null;

  const taskQueryKey = useMemo(
    () =>
      buildTaskQueryKey({
        mode: committedQuery ? "search" : "list",
        workView: taskViewForQuery,
        workDate: queryWorkDate,
        timezone: queryTimezone,
        q: committedQuery || null,
        archiveMode,
        cursor: cursor || null,
        sessionEpoch: runtime.sessionEpoch,
      }),
    [
      archiveMode,
      committedQuery,
      cursor,
      queryTimezone,
      queryWorkDate,
      runtime.sessionEpoch,
      taskViewForQuery,
    ],
  );
  const taskQueryKeyId = serializeTaskQueryKey(taskQueryKey);


  const applyTaskList = useCallback((payload: TaskListPayload) => {
    setRows(payload.tasks);
    setDisclosure(payload.disclosure);
    setNextCursor(payload.disclosure?.nextCursor ?? "");
    setPartial(payload.disclosure?.coverage === "partial" || payload.disclosure?.truncated === true);
    setReadError(undefined);
    setState(payload.tasks.length ? "ready" : "empty");
  }, []);

  const taskListFetcher = useCallback(
    async ({ signal }: { signal: AbortSignal }): Promise<TaskListPayload> => {
      const parameters = new URLSearchParams({
        pageSize: "50",
        workView: taskViewForQuery,
        archived: archiveMode,
      });
      if (committedQuery) parameters.set("q", committedQuery);
      if (cursor) parameters.set("after", cursor);
      if (queryWorkDate) parameters.set("workDate", queryWorkDate);
      if (queryTimezone) {
        parameters.set("timezone", queryTimezone);
        if (!timezone) {
          setTimezone(queryTimezone);
          sync({ tz: queryTimezone });
        }
      }
      const data = await workRequest<{ tasks: readonly TaskRow[]; disclosure?: DisclosureEnvelope }>(
        `/api/tasks?${parameters}`,
        { signal },
      );
      return {
        tasks: requiredCollection(data.tasks, "tasks"),
        disclosure: data.disclosure,
      };
    },
    [archiveMode, committedQuery, cursor, queryTimezone, queryWorkDate, taskViewForQuery, timezone],
  );

  const onTaskNotice = useCallback(
    (notice: { kind: string; message: string }) => {
      if (notice.kind !== "degraded") return;
      runtime.feedback.publishPollNotice({
        eventId: MutationFeedbackEvent.pollDegraded(taskQueryKeyId),
        kind: "info",
        message: notice.message,
      });
    },
    [runtime.feedback, taskQueryKeyId],
  );

  const onTaskResult = useCallback(
    (
      result: { outcome: string; data?: TaskListPayload; error?: unknown; silent: boolean },
      snapshot: { lastConfirmed: TaskListPayload | undefined },
    ) => {
      if (result.outcome === "applied" || result.outcome === "deduped") {
        const payload = result.data ?? snapshot.lastConfirmed;
        if (payload) applyTaskList(payload);
        return;
      }
      if (result.outcome === "failed" && !result.silent) {
        if (snapshot.lastConfirmed !== undefined) {
          applyTaskList(snapshot.lastConfirmed);
          return;
        }
        setReadError(result.error);
        setState("failed");
      }
    },
    [applyTaskList],
  );

  const {
    revalidate: revalidateTasks,
    notifyMutationConfirmed,
  } = useTaskFreshness<TaskListPayload>({
    queryKey: taskQueryKey,
    enabled: taskMode,
    coordinator: runtime.readCoordinator as TaskReadCoordinator<TaskListPayload>,
    fetcher: taskListFetcher,
    onResult: onTaskResult,
    onNotice: onTaskNotice,
    reconciliation: runtime.reconciliation,
  });

  // Freshness revalidates when `taskQueryKey` changes; filter/view handlers set loading.

  const loadCommitments = useCallback(async () => {
    activeCommitmentRead.current?.abort();
    const controller = new AbortController();
    activeCommitmentRead.current = controller;
    const generation = ++commitmentGeneration.current;
    setState("loading");
    setReadError(undefined);
    try {
      const parameters = new URLSearchParams({ pageSize: "50" });
      if (cursor) parameters.set("after", cursor);
      const waitingOn = commitmentFilter === "waiting-on";
      const path = waitingOn ? "/api/commitments/waiting-on" : "/api/commitments";
      if (!waitingOn && committedQuery) parameters.set("q", committedQuery);
      if (commitmentFilter === "all-open") parameters.set("state", "open");
      if (commitmentFilter === "closed") parameters.set("state", "closed");
      if (commitmentFilter === "due" || commitmentFilter === "recently-updated") {
        const commitmentClock = browserWorkClock(new Date(), timezone || undefined);
        parameters.set("workView", commitmentFilter === "due" ? "due" : "recently-updated");
        parameters.set("workDate", commitmentClock.workDate);
        parameters.set("timezone", commitmentClock.timezone);
        if (!timezone) {
          setTimezone(commitmentClock.timezone);
          sync({ tz: commitmentClock.timezone });
        }
      }
      const data = await workRequest<{
        commitments?: readonly CommitmentRow[];
        waiting_on?: readonly WaitingOnRow[];
        disclosure?: DisclosureEnvelope;
      }>(`${path}?${parameters}`, { signal: controller.signal });
      if (generation !== commitmentGeneration.current) return;
      const found = waitingOn
        ? requiredCollection(data.waiting_on, "waiting_on")
        : requiredCollection(data.commitments, "commitments");
      setRows(found);
      setDisclosure(data.disclosure);
      setNextCursor(data.disclosure?.nextCursor ?? "");
      setPartial(data.disclosure?.coverage === "partial" || data.disclosure?.truncated === true);
      setState(found.length ? "ready" : "empty");
    } catch (error) {
      if (generation !== commitmentGeneration.current || controller.signal.aborted) return;
      setReadError(error);
      setState("failed");
    }
  }, [commitmentFilter, committedQuery, cursor, timezone]);

  useEffect(() => {
    if (view !== "commitments") {
      activeCommitmentRead.current?.abort();
      return;
    }
    void Promise.resolve().then(loadCommitments);
    return () => activeCommitmentRead.current?.abort();
  }, [loadCommitments, view]);

  function reloadActiveSurface() {
    if (view === "commitments") {
      void loadCommitments();
      return;
    }
    void revalidateTasks("manual");
  }

  function select(next: WorkView) {
    /*
      Cleared explicitly, not left to the query key.

      Toggling between Tasks and Commitments empties the list, which re-runs
      focus resolution against no rows. Nothing needs clearing here: the control
      the user just pressed still holds focus, so the restore declines to move
      it. The earlier design had to clear at each navigation site by hand and
      missed pagination and this toggle in turn.
    */
    if (next !== "commitments") setLastTaskView(next as TaskView);
    setState("loading");
    setRows([]);
    setView(next);
    setCursor("");
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    url.searchParams.delete("cursor");
    history.replaceState(null, "", url);
  }

  function chooseMode(mode: "tasks" | "commitments") {
    if (mode === "commitments") {
      if (view !== "commitments") select("commitments");
      return;
    }
    if (view === "commitments") select(lastTaskView);
  }

  function chooseCommitmentFilter(value: CommitmentFilter) {
    sync({ commitment: value, cursor: undefined, q: value === "waiting-on" ? undefined : committedQuery || undefined });
    setCommitmentFilter(value);
    setCursor("");
    if (value === "waiting-on") {
      setQueryDraft("");
      setCommittedQuery("");
    }
  }

  function choosePerspective(next: string) {
    if (!WORK_PERSPECTIVES.includes(next as WorkPerspective)) return;
    const perspectiveValue = next as WorkPerspective;
    setPerspective(perspectiveValue);
    sync({ perspective: perspectiveValue === "list" ? undefined : perspectiveValue });
  }

  function toggleTask(taskId: string) {
    setSelectedTaskIds((current) =>
      current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId].slice(0, 100),
    );
  }

  function openDetail(type: "task" | "commitment", id: string, title: string, trigger: HTMLElement) {
    detailTrigger.current = trigger;
    setDetail({ type, id, title });
    sync({ task: type === "task" ? id : undefined, commitmentId: type === "commitment" ? id : undefined });
  }


  /**
   * A Task mutation was confirmed by the server.
   *
   * Reconciliation is authoritative — the server decides whether the Task still
   * belongs in this filter, and nothing is inserted or removed locally.
   */
  function onTaskMutationConfirmed() {
    void Promise.resolve(notifyMutationConfirmed()).catch(() => undefined);
  }

  /**
   * The Comment affordance. Opens the Task's own Activity rather than giving the
   * row a second comments implementation to keep in step with the first.
   */
  function openActivity(taskId: string, title: string, trigger: HTMLElement) {
    openDetail("task", taskId, title, trigger);
  }

  function closeDetail() {
    setDetail(undefined);
    sync({ task: undefined, commitmentId: undefined });
    requestAnimationFrame(() => detailTrigger.current?.focus());
  }

  const waitingOnSearch = view === "commitments" && commitmentFilter === "waiting-on";
  return (
    <section aria-labelledby="work-heading" className="mx-auto max-w-5xl pb-24">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 id="work-heading" ref={workHeading} tabIndex={-1} className="text-2xl font-semibold text-text-primary">Work</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">Tasks and commitments you are tracking.</p>
        </div>
        <Button
          ref={newTaskTrigger}
          onClick={() => {
            if (view === "commitments") {
              setCreatingCommitment((open) => !open);
              return;
            }
            setTaskCreateOpen(true);
          }}
        >
          {view === "commitments" ? (creatingCommitment ? "Cancel" : "New commitment") : "New task"}
        </Button>
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Work mode" className="inline-flex gap-1 rounded-[var(--radius-md)] bg-surface-subtle p-1">
          <Button variant={taskMode ? "secondary" : "ghost"} size="sm" aria-pressed={taskMode} onClick={() => chooseMode("tasks")}>
            Tasks
          </Button>
          <Button variant={taskMode ? "ghost" : "secondary"} size="sm" aria-pressed={!taskMode} onClick={() => chooseMode("commitments")}>
            Commitments
          </Button>
        </div>
        {taskMode ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="sm" aria-label="Work views">{LABEL[view]}</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent aria-label="Work views">
              {TASK_VIEWS.map((item) => (
                <DropdownMenuItem key={item} onSelect={() => select(item)} aria-current={view === item ? "true" : undefined}>
                  {LABEL[item]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="sm" aria-label="Commitment filter">{COMMITMENT_LABEL[commitmentFilter]}</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent aria-label="Commitment filter">
              {COMMITMENT_FILTERS.map((item) => (
                <DropdownMenuItem
                  key={item}
                  onSelect={() => chooseCommitmentFilter(item)}
                  aria-current={commitmentFilter === item ? "true" : undefined}
                >
                  {COMMITMENT_LABEL[item]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <div role="group" aria-label="Work perspective" className="inline-flex gap-1 rounded-[var(--radius-md)] bg-surface-subtle p-1">
          {WORK_PERSPECTIVES.map((item) => (
            <Button
              key={item}
              variant={perspective === item ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={perspective === item}
              onClick={() => choosePerspective(item)}
            >
              {PERSPECTIVE_LABEL[item]}
            </Button>
          ))}
        </div>
        {selectedTaskIds.length > 0 ? (
          <p className="text-xs text-muted">
            {selectedTaskIds.length} task{selectedTaskIds.length === 1 ? "" : "s"} selected
          </p>
        ) : null}
      </div>
      {view === "commitments" && creatingCommitment ? (
        <CommitmentCreate onDone={() => { setCreatingCommitment(false); void loadCommitments(); }} />
      ) : null}
      <div className="mt-5 flex flex-wrap items-end gap-3">
        <div className="min-w-0 max-w-sm flex-1">
          <Labeled
            label={view === "commitments" ? "Search commitments" : "Search tasks"}
            hint={waitingOnSearch ? "Search is unavailable for the dedicated Waiting On view." : undefined}
          >
            <Input
              aria-label={view === "commitments" ? "Search commitments" : "Search tasks"}
              value={queryDraft}
              disabled={waitingOnSearch}
              onChange={(event) => setQueryDraft(event.target.value)}
              placeholder={view === "commitments" ? "Search commitments" : "Search tasks"}
            />
          </Labeled>
        </div>
        <Button
          variant="secondary"
          disabled={waitingOnSearch}
          onClick={() => {
            sync({ q: queryDraft || undefined, cursor: undefined });
            setCursor("");
            setCommittedQuery(queryDraft);
          }}
        >
          Search
        </Button>
        {taskMode ? (
          <details className="min-w-[12rem]" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
            <summary className="cursor-pointer text-sm font-medium text-text-primary">Filters</summary>
            <div className="mt-2">
              <Labeled label="Archive">
                <Select
                  aria-label="Archive"
                  value={archiveMode}
                  onChange={(event) => {
                    const value = event.target.value as typeof archiveMode;
                    sync({ archived: value, cursor: undefined });
                    setArchiveMode(value);
                    setCursor("");
                  }}
                >
                  <option value="exclude">Active only</option>
                  <option value="only">Archived only</option>
                </Select>
              </Labeled>
            </div>
          </details>
        ) : null}
      </div>
      <div className="mt-5" aria-live="polite">
        {state === "loading" ? <LoadingStatus label="Loading work…" testId="work-loading" /> : null}
        {state === "failed" ? (
          <SurfaceState kind="unavailable" title={mapUserError(readError).title} error={readError}>
            <Button className="mt-3" variant="secondary" onClick={() => reloadActiveSurface()}>
              Try again
            </Button>
          </SurfaceState>
        ) : null}
        {state === "empty" ? (
          <SurfaceState
            kind="empty"
            title={`${committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open") ? "No matching" : "No"} ${view === "commitments" ? "commitments" : LABEL[view].toLowerCase() + " tasks"}`}
            detail={
              committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open")
                ? "Nothing matched these filters."
                : "Nothing is in this view yet."
            }
          />
        ) : null}
        {state === "ready" ? (
          /*
            React's `onFocus` is `focusin`, which bubbles — so this one handler
            sees focus land anywhere in the list, including on controls a row
            mounts later. It is a listener, not an interactive element.
          */
          <div onFocus={rememberFocusedRow}>
            <WorkPerspectives
              perspective={perspective}
              rows={rows}
              commitments={view === "commitments"}
              selectedTaskIds={selectedTaskIds}
              onSelectTask={toggleTask}
              onOpen={openDetail}
              onOpenActivity={openActivity}
              onTaskMutationConfirmed={onTaskMutationConfirmed}
            />
          </div>
        ) : null}
      </div>
      {disclosure && state !== "failed" ? <Disclosure details={disclosure} /> : null}
      {partial ? <SurfaceState kind="degraded" title="More Work is available" detail="There are more results. Continue to the next page." /> : null}
      {nextCursor ? (
        <Button
          variant="secondary"
          onClick={() => {
            sync({ cursor: nextCursor });
            setCursor(nextCursor);
          }}
        >
          Next page
        </Button>
      ) : null}
      {view !== "commitments" && selectedTaskIds.length > 0 ? (
        <BulkTaskEditor
          key={selectedTaskIds.join("|")}
          taskIds={selectedTaskIds}
          onConfirmed={() => {
            void notifyMutationConfirmed();
          }}
        />
      ) : null}
      {detail?.type === "task" ? (
        <TaskCompactSheet
          taskId={detail.id}
          open
          onOpenChange={(open) => {
            if (!open) closeDetail();
          }}
          seed={taskSeed(rows, detail.id)}
        />
      ) : null}
      {/*
        Canonical Task create. Work prefills nothing from the current view or
        filter, and owns no create reconciliation of its own. The canonical create
        notifies the session-scoped runtime seam itself, so every launcher — Work
        here, Capture from the shell — reconciles identically and none can forget
        to. Work bucket/filter membership is the server's answer, so nothing is
        merged into the list here.
      */}
      <TaskCreateSheet
        open={taskCreateOpen}
        onOpenChange={(open) => {
          setTaskCreateOpen(open);
          if (!open) {
            requestAnimationFrame(() => newTaskTrigger.current?.focus());
          }
        }}
        entry="work"
      />
      <Sheet
        open={detail?.type === "commitment"}
        onOpenChange={(open) => {
          if (!open) closeDetail();
        }}
        title={detail?.title ?? "Work detail"}
        description="Closing restores your place in Work."
        placement="detail"
      >
        {detail?.type === "commitment" ? <CommitmentDetailView commitmentId={detail.id} embedded /> : null}
      </Sheet>
    </section>
  );
}

/**
 * The already-loaded list row for an open Task, used only to paint the compact Sheet
 * while the canonical Task hydrates. A row carries no guaranteed version, so it is a
 * display seed and never a mutation authority.
 */
function taskSeed(
  rows: readonly TaskRow[] | readonly CommitmentRow[] | readonly WaitingOnRow[],
  taskId: string,
): TaskRow | null {
  const match = (rows as readonly { task_id?: string }[]).find((row) => row.task_id === taskId);
  return match && "lifecycle_state" in match ? (match as TaskRow) : null;
}

function Disclosure({ details }: { details: DisclosureEnvelope }) {
  return (
    <aside aria-label="Work answer disclosure" className="mt-4 rounded-lg border border-border bg-surface p-3 text-xs text-muted">
      <p>
        <span className="font-medium text-text-primary">Updated:</span>{" "}
        {details.freshnessAt ? (
          <time className="tabular-nums" data-visual-dynamic="freshness" dateTime={details.freshnessAt}>
            {new Date(details.freshnessAt).toLocaleString()}
          </time>
        ) : (
          "not disclosed"
        )}
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer font-medium text-text-primary">Details</summary>
        <p className="mt-1">
          Authority: {details.authority.replaceAll("_", " ")} · Coverage: {details.coverage} · Truncation:{" "}
          {details.truncated ? "yes" : "no"}
        </p>
        {details.limitations.length ? (
          <ul className="mt-1 list-inside list-disc">
            {details.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1">No additional limitations were disclosed.</p>
        )}
      </details>
    </aside>
  );
}

function bulkCounts(receipt: { affected: number; no_op: number; rejected: number }) {
  return `${receipt.affected} affected, ${receipt.no_op} no-op, ${receipt.rejected} rejected`;
}

function BulkTaskEditor({ taskIds, onConfirmed }: { taskIds: readonly string[]; onConfirmed: () => void }) {
  const [kind, setKind] = useState<"priority" | "transition">("priority");
  const [value, setValue] = useState("p1");
  const [status, setStatus] = useState("Ready to preview. Nothing has changed yet.");
  const [statusDetails, setStatusDetails] = useState("");
  const [preview, setPreview] = useState<TaskBulkPreviewReceipt>();
  const [mutations, setMutations] = useState<readonly TaskBulkMutation[]>();
  const [busy, setBusy] = useState(false);
  const previewAttempt = useRef(createAttemptKey("task-bulk-preview"));
  const confirmAttempt = useRef(createAttemptKey("task-bulk-confirm"));

  function note(headline: string, details = "") {
    setStatus(headline);
    setStatusDetails(details);
  }

  function failureNote(error: unknown, phase: "preview" | "confirm", retainedPreview?: TaskBulkPreviewReceipt) {
    const failure = error as { status?: number; code?: string; message?: string };
    const retained = retainedPreview ? `Preview ${retainedPreview.bulk_operation_id} expires ${retainedPreview.expires_at}.` : "";
    if (failure.status === 409) {
      return phase === "confirm"
        ? note("Confirmation was refused. Nothing was applied; preview again.", `Preview expired or versions drifted. ${retained}`.trim())
        : note("Preview conflicted. Nothing was applied; the selection and action are retained.", failure.message ?? "409 conflict");
    }
    if (failure.status === 503) {
      return note("Work is unavailable. Nothing was applied.", `Selection and action are retained. ${retained}`.trim());
    }
    note(failure.message ?? `Bulk ${phase} failed. Nothing was applied.`, retained);
  }

  async function previewChanges() {
    setBusy(true);
    setPreview(undefined);
    setMutations(undefined);
    note("Preparing preview…");
    try {
      const details = await Promise.all(
        taskIds.map(async (taskId) => {
          const answer = await workRequest<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(taskId)}`);
          return answer.task;
        }),
      );
      const normalized: readonly TaskBulkMutation[] = details.map((task): TaskBulkMutation => {
        if (kind === "priority") {
          const values: Readonly<Record<string, string | boolean>> =
            value === "clear" ? {} : { priority: value as TaskPriority };
          return {
            kind: "update" as const,
            task_id: task.task_id,
            expected_version: task.version,
            values,
            clear_fields: value === "clear" ? ["priority"] : [],
          };
        }
        return {
          kind: "transition" as const,
          task_id: task.task_id,
          expected_version: task.version,
          to_state: value as "open" | "in_progress" | "waiting" | "blocked",
        };
      });
      note("Preparing preview…");
      const receipt = await workRequest<TaskBulkPreviewReceipt>("/api/tasks/bulk/preview", {
        method: "POST",
        body: JSON.stringify({ mutations: normalized, idempotencyKey: previewAttempt.current.forPayload(normalized) }),
      });
      previewAttempt.current.succeeded();
      setMutations(normalized);
      setPreview(receipt);
      note(
        "Preview ready",
        `${receipt.replayed ? "Replayed" : "Applied"} preview: ${bulkCounts(receipt)}. No task has changed. Preview ${receipt.bulk_operation_id} expires ${receipt.expires_at}.`,
      );
    } catch (error) {
      if (isDefinitiveAttemptFailure(error)) previewAttempt.current.succeeded();
      failureNote(error, "preview");
    } finally {
      setBusy(false);
    }
  }

  async function confirmChanges() {
    if (!preview || !mutations) return;
    if (Date.now() >= new Date(preview.expires_at).getTime()) {
      setPreview(undefined);
      setMutations(undefined);
      confirmAttempt.current.succeeded();
      note(
        "The preview expired before confirmation. Nothing was applied; preview again.",
        `Preview ${preview.bulk_operation_id} expired at ${preview.expires_at}.`,
      );
      return;
    }
    setBusy(true);
    note("Applying the previewed changes…");
    try {
      const receipt = await workRequest<TaskBulkConfirmReceipt>("/api/tasks/bulk/confirm", {
        method: "POST",
        body: JSON.stringify({
          bulkOperationId: preview.bulk_operation_id,
          idempotencyKey: confirmAttempt.current.forPayload({ bulkOperationId: preview.bulk_operation_id, mutations }),
          mutations,
        }),
      });
      confirmAttempt.current.succeeded();
      setPreview(undefined);
      setMutations(undefined);
      note(
        "Changes applied",
        `${receipt.replayed ? "Replayed" : "Applied"} confirmation: ${bulkCounts(receipt)}; history_ids: ${receipt.history_ids.join(", ") || "none"}.`,
      );
      onConfirmed();
    } catch (error) {
      const responseStatus = (error as { status?: number }).status;
      const definitive = responseStatus !== undefined && [400, 401, 403, 404, 409, 410, 422].includes(responseStatus);
      if (definitive) {
        confirmAttempt.current.succeeded();
        setPreview(undefined);
        setMutations(undefined);
        failureNote(error, "confirm");
      } else {
        failureNote(error, "confirm", preview);
      }
    } finally {
      setBusy(false);
    }
  }

  function changeKind(next: "priority" | "transition") {
    setKind(next);
    setValue(next === "priority" ? "p1" : "open");
    setPreview(undefined);
    setMutations(undefined);
    note("Action changed. Preview the retained selection before confirmation.");
  }

  return (
    <section aria-labelledby="bulk-heading" className="mt-6 rounded-xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="bulk-heading" className="font-semibold text-text-primary">Bulk change</h2>
        <span className="text-sm text-muted">{taskIds.length} selected · maximum 100</span>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Labeled label="Action">
          <select
            aria-label="Bulk action"
            value={kind}
            disabled={busy}
            onChange={(event) => changeKind(event.target.value as "priority" | "transition")}
            className="h-10 rounded-md border bg-surface px-3"
          >
            <option value="priority">Set priority</option>
            <option value="transition">Move lifecycle</option>
          </select>
        </Labeled>
        <Labeled label={kind === "priority" ? "Priority" : "Lifecycle state"}>
          <select
            aria-label="Bulk value"
            value={value}
            disabled={busy}
            onChange={(event) => {
              setValue(event.target.value);
              setPreview(undefined);
              setMutations(undefined);
              note("Action changed. Preview the retained selection before confirmation.");
            }}
            className="h-10 rounded-md border bg-surface px-3"
          >
            {kind === "priority" ? (
              <>
                <option value="p1">P1</option>
                <option value="p2">P2</option>
                <option value="p3">P3</option>
                <option value="p4">P4</option>
                <option value="clear">Clear priority</option>
              </>
            ) : (
              <>
                <option value="open">Open</option>
                <option value="in_progress">In progress</option>
                <option value="waiting">Waiting</option>
                <option value="blocked">Blocked</option>
              </>
            )}
          </select>
        </Labeled>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" variant="secondary" disabled={busy} onClick={() => void previewChanges()}>
          {busy && !preview ? "Previewing…" : preview ? "Refresh preview" : "Preview change"}
        </Button>
        <Button type="button" disabled={busy || !preview} onClick={() => void confirmChanges()}>
          {busy && preview ? "Confirming…" : "Confirm exact preview"}
        </Button>
      </div>
      <StatusNote message={status} details={statusDetails} className="mt-3" />
    </section>
  );
}

function CommitmentCreate({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState("");
  const [counterparties, setCounterparties] = useState<readonly CounterpartyOption[]>([]);
  const [optionsStatus, setOptionsStatus] = useState("Loading verified counterparties…");
  const [optionsTruncated, setOptionsTruncated] = useState(false);
  const captureAttempt = useRef(createAttemptKey("commitment-origin"));
  const createAttempt = useRef(createAttemptKey("commitment-create"));
  useEffect(() => {
    const controller = new AbortController();
    void workRequest<{ counterparty_options: readonly CounterpartyOption[]; counterparty_options_truncated?: boolean }>(
      "/api/commitments?pageSize=1",
      { signal: controller.signal },
    )
      .then((answer) => {
        setCounterparties(requiredCollection(answer.counterparty_options, "counterparty_options"));
        setOptionsTruncated(Boolean(answer.counterparty_options_truncated));
        setOptionsStatus("");
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setOptionsStatus(error instanceof Error ? error.message : "Verified counterparties are unavailable");
        }
      });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const note = String(form.get("origin"));
    const counterpartyPersonId = String(form.get("counterparty") ?? "");
    if (!counterparties.some((item) => item.person_id === counterpartyPersonId)) {
      setStatus("Choose a verified counterparty from the list.");
      return;
    }
    setStatus("Saving evidence…");
    try {
      const origin = await captureEvidence(note, "commitment-origin", captureAttempt.current.forPayload({ note }));
      setStatus("Creating commitment…");
      const payload = {
        summary: form.get("summary"),
        counterpartyPersonId,
        direction: form.get("direction"),
        dueAt: form.get("dueAt") ? new Date(String(form.get("dueAt"))).toISOString() : undefined,
        originEvidenceRef: origin,
      };
      await workRequest("/api/commitments", {
        method: "POST",
        body: JSON.stringify({ ...payload, idempotencyKey: createAttempt.current.forPayload(payload) }),
      });
      captureAttempt.current.succeeded();
      createAttempt.current.succeeded();
      setStatus("Commitment created.");
      onDone();
    } catch (error) {
      if (isDefinitiveAttemptFailure(error)) {
        captureAttempt.current.succeeded();
        createAttempt.current.succeeded();
      }
      setStatus(error instanceof Error ? error.message : "Commitment was not created");
    }
  }
  return (
    <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-border bg-surface p-4">
      <h2 className="font-semibold">Create commitment</h2>
      <Labeled label="Summary">
        <Input name="summary" required />
      </Labeled>
      <div className="grid gap-4 sm:grid-cols-2">
        <Labeled label="Counterparty">
          <select
            name="counterparty"
            required
            disabled={Boolean(optionsStatus) || counterparties.length === 0}
            className="h-10 rounded-md border bg-surface px-3"
          >
            <option value="">Choose a person</option>
            {counterparties.map((item) => (
              <option key={item.person_id} value={item.person_id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </Labeled>
        <Labeled label="Direction">
          <select name="direction" className="h-10 rounded-md border bg-surface px-3">
            <option value="owed_to_principal">Owed to me</option>
            <option value="owed_by_principal">Owed by me</option>
          </select>
        </Labeled>
        <Labeled label="Due">
          <Input name="dueAt" type="datetime-local" />
        </Labeled>
      </div>
      {optionsStatus ? (
        <p role="status" className="text-sm text-muted">
          {optionsStatus}
        </p>
      ) : counterparties.length === 0 ? (
        <p role="status" className="text-sm text-muted">
          No verified relationship people are available for selection.
        </p>
      ) : optionsTruncated ? (
        <p role="status" className="text-sm text-muted">
          Showing the first 100 verified people.
        </p>
      ) : null}
      <Labeled label="Origin note" hint="Saved through Quick Capture before the commitment is attempted.">
        <Textarea name="origin" required />
      </Labeled>
      <Button type="submit" disabled={counterparties.length === 0}>
        Create commitment
      </Button>
      <p role="status" className="text-sm text-muted">
        {status}
      </p>
    </form>
  );
}
