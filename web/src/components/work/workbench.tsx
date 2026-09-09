"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import { Textarea } from "@/components/ui/textarea";
import { CommitmentDetailView, TaskDetailView } from "@/components/work/work-detail";
import { WorkPerspectives } from "@/components/work/work-perspectives";
import { browserWorkClock, captureEvidence, createAttemptKey, isDefinitiveAttemptFailure, requiredCollection, workRequest } from "@/lib/api/work-client";
import { COMMITMENT_FILTERS, parseWorkUrlState, TASK_VIEWS, WORK_PERSPECTIVES, type CommitmentFilter, type TaskView, type WorkPerspective, type WorkUrlState, type WorkView } from "@/lib/api/work-url";
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

export function Workbench({ initialState = DEFAULT_STATE }: { initialState?: WorkUrlState }) {
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
  const [creating, setCreating] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(initialState.archived === "only");
  const lastTaskView = useRef<TaskView>(initialState.view === "commitments" ? "today" : initialState.view);
  const [selectedTaskIds, setSelectedTaskIds] = useState<readonly string[]>([]);
  const [detail, setDetail] = useState<{ type: "task" | "commitment"; id: string; title: string } | undefined>(
    initialState.task ? { type: "task", id: initialState.task, title: "Task detail" }
      : initialState.commitmentId ? { type: "commitment", id: initialState.commitmentId, title: "Commitment detail" }
      : undefined,
  );
  const readGeneration = useRef(0);
  const activeRead = useRef<AbortController | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    activeRead.current?.abort();
    const controller = new AbortController();
    activeRead.current = controller;
    const generation = ++readGeneration.current;
    setState("loading"); setReadError(undefined);
    try {
      if (view === "commitments") {
        const parameters = new URLSearchParams({ pageSize: "50" });
        if (cursor) parameters.set("after", cursor);
        const waitingOn = commitmentFilter === "waiting-on";
        const path = waitingOn ? "/api/commitments/waiting-on" : "/api/commitments";
        if (!waitingOn && committedQuery) parameters.set("q", committedQuery);
        if (commitmentFilter === "all-open") parameters.set("state", "open");
        if (commitmentFilter === "closed") parameters.set("state", "closed");
        if (commitmentFilter === "due" || commitmentFilter === "recently-updated") {
          const clock = browserWorkClock(new Date(), timezone || undefined);
          parameters.set("workView", commitmentFilter === "due" ? "due" : "recently-updated");
          parameters.set("workDate", clock.workDate);
          parameters.set("timezone", clock.timezone);
          if (!timezone) { setTimezone(clock.timezone); sync({ tz: clock.timezone }); }
        }
        const data = await workRequest<{ commitments?: readonly CommitmentRow[]; waiting_on?: readonly WaitingOnRow[]; disclosure?: DisclosureEnvelope }>(`${path}?${parameters}`, { signal: controller.signal });
        if (generation !== readGeneration.current) return;
        const found = waitingOn
          ? requiredCollection(data.waiting_on, "waiting_on")
          : requiredCollection(data.commitments, "commitments");
        setRows(found); setDisclosure(data.disclosure); setNextCursor(data.disclosure?.nextCursor ?? ""); setPartial(data.disclosure?.coverage === "partial" || data.disclosure?.truncated === true); setState(found.length ? "ready" : "empty");
      } else {
        const parameters = new URLSearchParams({ pageSize: "50", workView: view, archived: archiveMode });
        if (committedQuery) parameters.set("q", committedQuery);
        if (cursor) parameters.set("after", cursor);
        if (["overdue", "today", "upcoming", "recently-updated"].includes(view)) {
          const clock = browserWorkClock(new Date(), timezone || undefined);
          parameters.set("workDate", clock.workDate);
          parameters.set("timezone", clock.timezone);
          if (!timezone) { setTimezone(clock.timezone); sync({ tz: clock.timezone }); }
        }
        const data = await workRequest<{ tasks: readonly TaskRow[]; disclosure?: DisclosureEnvelope }>(`/api/tasks?${parameters}`, { signal: controller.signal });
        if (generation !== readGeneration.current) return;
        const tasks = requiredCollection(data.tasks, "tasks");
        setRows(tasks); setDisclosure(data.disclosure); setNextCursor(data.disclosure?.nextCursor ?? ""); setPartial(data.disclosure?.coverage === "partial" || data.disclosure?.truncated === true); setState(tasks.length ? "ready" : "empty");
      }
    } catch (error) {
      if (generation !== readGeneration.current || controller.signal.aborted) return;
      setReadError(error); setState("failed");
    }
  }, [archiveMode, commitmentFilter, committedQuery, cursor, timezone, view]);
  useEffect(() => {
    void Promise.resolve().then(load);
    return () => activeRead.current?.abort();
  }, [load]);

  function select(next: WorkView) {
    if (next !== "commitments") lastTaskView.current = next;
    setState("loading"); setRows([]); setView(next); setCursor("");
    const url = new URL(window.location.href); url.searchParams.set("view", next); url.searchParams.delete("cursor"); history.replaceState(null, "", url);
  }

  function chooseMode(mode: "tasks" | "commitments") {
    if (mode === "commitments") {
      if (view !== "commitments") select("commitments");
      return;
    }
    if (view === "commitments") select(lastTaskView.current);
  }

  function chooseCommitmentFilter(value: CommitmentFilter) {
    sync({ commitment: value, cursor: undefined, q: value === "waiting-on" ? undefined : committedQuery || undefined });
    setCommitmentFilter(value);
    setCursor("");
    if (value === "waiting-on") { setQueryDraft(""); setCommittedQuery(""); }
  }

  function sync(parameters: Record<string, string | undefined>) {
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(parameters)) {
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
    }
    history.replaceState(null, "", url);
  }

  function choosePerspective(next: string) {
    if (!WORK_PERSPECTIVES.includes(next as WorkPerspective)) return;
    const perspectiveValue = next as WorkPerspective;
    setPerspective(perspectiveValue);
    sync({ perspective: perspectiveValue === "list" ? undefined : perspectiveValue });
  }

  function toggleTask(taskId: string) {
    setSelectedTaskIds((current) => current.includes(taskId)
      ? current.filter((id) => id !== taskId)
      : [...current, taskId].slice(0, 100));
  }

  function openDetail(type: "task" | "commitment", id: string, title: string, trigger: HTMLElement) {
    detailTrigger.current = trigger;
    setDetail({ type, id, title });
    sync({ task: type === "task" ? id : undefined, commitmentId: type === "commitment" ? id : undefined });
  }

  function closeDetail() {
    setDetail(undefined);
    sync({ task: undefined, commitmentId: undefined });
    requestAnimationFrame(() => detailTrigger.current?.focus());
  }

  const waitingOnSearch = view === "commitments" && commitmentFilter === "waiting-on";
  const taskMode = view !== "commitments";
  return <section aria-labelledby="work-heading" className="mx-auto max-w-5xl pb-24">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 id="work-heading" className="text-2xl font-semibold text-text-primary">Work</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">Tasks and commitments you are tracking.</p>
      </div>
      <Button onClick={() => setCreating((open) => !open)}>{creating ? "Cancel" : view === "commitments" ? "New commitment" : "New task"}</Button>
    </div>
    <div className="mt-6 flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Work mode"
        className="inline-flex gap-1 rounded-[var(--radius-md)] bg-surface-subtle p-1"
      >
        <Button
          variant={taskMode ? "secondary" : "ghost"}
          size="sm"
          aria-pressed={taskMode}
          onClick={() => chooseMode("tasks")}
        >
          Tasks
        </Button>
        <Button
          variant={taskMode ? "ghost" : "secondary"}
          size="sm"
          aria-pressed={!taskMode}
          onClick={() => chooseMode("commitments")}
        >
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
              <DropdownMenuItem key={item} onSelect={() => select(item)} aria-current={view === item ? "true" : undefined}>{LABEL[item]}</DropdownMenuItem>
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
              <DropdownMenuItem key={item} onSelect={() => chooseCommitmentFilter(item)} aria-current={commitmentFilter === item ? "true" : undefined}>{COMMITMENT_LABEL[item]}</DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <div
        role="group"
        aria-label="Work perspective"
        className="inline-flex gap-1 rounded-[var(--radius-md)] bg-surface-subtle p-1"
      >
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
      {selectedTaskIds.length > 0 ? <p className="text-xs text-muted">{selectedTaskIds.length} task{selectedTaskIds.length === 1 ? "" : "s"} selected</p> : null}
    </div>
    {creating ? (view === "commitments" ? <CommitmentCreate onDone={() => { setCreating(false); void load(); }} /> : <TaskCreate onDone={() => { setCreating(false); void load(); }} />) : null}
    <div className="mt-5 flex flex-wrap items-end gap-3">
      <div className="min-w-0 max-w-sm flex-1">
        <Labeled label={view === "commitments" ? "Search commitments" : "Search tasks"} hint={waitingOnSearch ? "Search is unavailable for the dedicated Waiting On view." : undefined}>
          <Input aria-label={view === "commitments" ? "Search commitments" : "Search tasks"} value={queryDraft} disabled={waitingOnSearch} onChange={(event) => setQueryDraft(event.target.value)} placeholder={view === "commitments" ? "Search commitments" : "Search tasks"} />
        </Labeled>
      </div>
      <Button variant="secondary" disabled={waitingOnSearch} onClick={() => { sync({ q: queryDraft || undefined, cursor: undefined }); setCursor(""); setCommittedQuery(queryDraft); }}>Search</Button>
      {taskMode ? (
        <details className="min-w-[12rem]" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-medium text-text-primary">Filters</summary>
          <div className="mt-2">
            <Labeled label="Archive">
              <Select aria-label="Archive" value={archiveMode} onChange={(event) => { const value = event.target.value as typeof archiveMode; sync({ archived: value, cursor: undefined }); setArchiveMode(value); setCursor(""); }}>
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
      {state === "failed" ? <SurfaceState kind="unavailable" title={mapUserError(readError).title} error={readError}><Button className="mt-3" variant="secondary" onClick={() => void load()}>Try again</Button></SurfaceState> : null}
      {state === "empty" ? <SurfaceState kind="empty" title={`${committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open") ? "No matching" : "No"} ${view === "commitments" ? "commitments" : LABEL[view].toLowerCase() + " tasks"}`} detail={committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open") ? "Nothing matched these filters." : "Nothing is in this view yet."} /> : null}
      {state === "ready" ? <WorkPerspectives perspective={perspective} rows={rows} commitments={view === "commitments"} selectedTaskIds={selectedTaskIds} onSelectTask={toggleTask} onOpen={openDetail} /> : null}
    </div>
    {disclosure && state !== "failed" ? <Disclosure details={disclosure} /> : null}
    {partial ? <SurfaceState kind="degraded" title="More Work is available" detail="There are more results. Continue to the next page." /> : null}
    {nextCursor ? <Button variant="secondary" onClick={() => { sync({ cursor: nextCursor }); setCursor(nextCursor); }}>Next page</Button> : null}
    {view !== "commitments" && selectedTaskIds.length > 0 ? <BulkTaskEditor key={selectedTaskIds.join("|")} taskIds={selectedTaskIds} onConfirmed={() => { void load(); }} /> : null}
    <Sheet open={Boolean(detail)} onOpenChange={(open) => { if (!open) closeDetail(); }} title={detail?.title ?? "Work detail"} description="Closing restores your place in Work." placement="detail">
      {detail?.type === "task" ? <TaskDetailView taskId={detail.id} embedded /> : null}
      {detail?.type === "commitment" ? <CommitmentDetailView commitmentId={detail.id} embedded /> : null}
    </Sheet>
  </section>;
}

function Disclosure({ details }: { details: DisclosureEnvelope }) {
  return <aside aria-label="Work answer disclosure" className="mt-4 rounded-lg border border-border bg-surface p-3 text-xs text-muted">
    <p><span className="font-medium text-text-primary">Updated:</span> {details.freshnessAt ? <time className="tabular-nums" data-visual-dynamic="freshness" dateTime={details.freshnessAt}>{new Date(details.freshnessAt).toLocaleString()}</time> : "not disclosed"}</p>
    <details className="mt-2">
      <summary className="cursor-pointer font-medium text-text-primary">Details</summary>
      <p className="mt-1">Authority: {details.authority.replaceAll("_", " ")} · Coverage: {details.coverage} · Truncation: {details.truncated ? "yes" : "no"}</p>
      {details.limitations.length ? <ul className="mt-1 list-inside list-disc">{details.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul> : <p className="mt-1">No additional limitations were disclosed.</p>}
    </details>
  </aside>;
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
    setBusy(true); setPreview(undefined); setMutations(undefined); note("Preparing preview…");
    try {
      const details = await Promise.all(taskIds.map(async (taskId) => {
        const answer = await workRequest<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(taskId)}`);
        return answer.task;
      }));
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
      previewAttempt.current.succeeded(); setMutations(normalized); setPreview(receipt);
      note("Preview ready", `${receipt.replayed ? "Replayed" : "Applied"} preview: ${bulkCounts(receipt)}. No task has changed. Preview ${receipt.bulk_operation_id} expires ${receipt.expires_at}.`);
    } catch (error) { if (isDefinitiveAttemptFailure(error)) previewAttempt.current.succeeded(); failureNote(error, "preview"); }
    finally { setBusy(false); }
  }

  async function confirmChanges() {
    if (!preview || !mutations) return;
    if (Date.now() >= new Date(preview.expires_at).getTime()) {
      setPreview(undefined);
      setMutations(undefined);
      confirmAttempt.current.succeeded();
      note("The preview expired before confirmation. Nothing was applied; preview again.", `Preview ${preview.bulk_operation_id} expired at ${preview.expires_at}.`);
      return;
    }
    setBusy(true); note("Applying the previewed changes…");
    try {
      const receipt = await workRequest<TaskBulkConfirmReceipt>("/api/tasks/bulk/confirm", {
        method: "POST",
        body: JSON.stringify({ bulkOperationId: preview.bulk_operation_id, idempotencyKey: confirmAttempt.current.forPayload({ bulkOperationId: preview.bulk_operation_id, mutations }), mutations }),
      });
      confirmAttempt.current.succeeded(); setPreview(undefined); setMutations(undefined);
      note("Changes applied", `${receipt.replayed ? "Replayed" : "Applied"} confirmation: ${bulkCounts(receipt)}; history_ids: ${receipt.history_ids.join(", ") || "none"}.`);
      onConfirmed();
    } catch (error) {
      const responseStatus = (error as { status?: number }).status;
      const definitive = responseStatus !== undefined && [400, 401, 403, 404, 409, 410, 422].includes(responseStatus);
      if (definitive) { confirmAttempt.current.succeeded(); setPreview(undefined); setMutations(undefined); failureNote(error, "confirm"); }
      else { failureNote(error, "confirm", preview); }
    } finally { setBusy(false); }
  }

  function changeKind(next: "priority" | "transition") {
    setKind(next); setValue(next === "priority" ? "p1" : "open"); setPreview(undefined); setMutations(undefined);
    note("Action changed. Preview the retained selection before confirmation.");
  }

  return <section aria-labelledby="bulk-heading" className="mt-6 rounded-xl border border-border bg-surface p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="bulk-heading" className="font-semibold text-text-primary">Bulk change</h2><span className="text-sm text-muted">{taskIds.length} selected · maximum 100</span></div>
    <div className="mt-4 grid gap-4 sm:grid-cols-2">
      <Labeled label="Action"><select aria-label="Bulk action" value={kind} disabled={busy} onChange={(event) => changeKind(event.target.value as "priority" | "transition")} className="h-10 rounded-md border bg-surface px-3"><option value="priority">Set priority</option><option value="transition">Move lifecycle</option></select></Labeled>
      <Labeled label={kind === "priority" ? "Priority" : "Lifecycle state"}><select aria-label="Bulk value" value={value} disabled={busy} onChange={(event) => { setValue(event.target.value); setPreview(undefined); setMutations(undefined); note("Action changed. Preview the retained selection before confirmation."); }} className="h-10 rounded-md border bg-surface px-3">{kind === "priority" ? <><option value="p1">P1</option><option value="p2">P2</option><option value="p3">P3</option><option value="p4">P4</option><option value="clear">Clear priority</option></> : <><option value="open">Open</option><option value="in_progress">In progress</option><option value="waiting">Waiting</option><option value="blocked">Blocked</option></>}</select></Labeled>
    </div>
    <div className="mt-4 flex flex-wrap gap-2"><Button type="button" variant="secondary" disabled={busy} onClick={() => void previewChanges()}>{busy && !preview ? "Previewing…" : preview ? "Refresh preview" : "Preview change"}</Button><Button type="button" disabled={busy || !preview} onClick={() => void confirmChanges()}>{busy && preview ? "Confirming…" : "Confirm exact preview"}</Button></div>
    <StatusNote message={status} details={statusDetails} className="mt-3" />
  </section>;
}

function TaskCreate({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState("");
  const [commitments, setCommitments] = useState<readonly CommitmentRow[]>([]);
  const [optionsStatus, setOptionsStatus] = useState("Loading verified commitments…");
  const captureAttempt = useRef(createAttemptKey("task-origin"));
  const createAttempt = useRef(createAttemptKey("task-create"));
  useEffect(() => {
    const controller = new AbortController();
    void workRequest<{ commitments: readonly CommitmentRow[] }>("/api/commitments?pageSize=100", { signal: controller.signal })
      .then((answer) => { setCommitments(requiredCollection(answer.commitments, "commitments")); setOptionsStatus(""); })
      .catch((error) => { if (!controller.signal.aborted) setOptionsStatus(error instanceof Error ? error.message : "Verified commitments are unavailable"); });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setStatus("Saving evidence…"); const form = new FormData(event.currentTarget);
    const note = String(form.get("origin"));
    const commitmentId = String(form.get("commitmentId") ?? "");
    if (commitmentId && !commitments.some((item) => item.commitment_id === commitmentId)) { setStatus("Choose a verified commitment from the list."); return; }
    try { const origin = await captureEvidence(note, "task-origin", captureAttempt.current.forPayload({ note })); setStatus("Creating task…"); const payload = { title: form.get("title"), description: form.get("description") || undefined, priority: form.get("priority") || undefined, dueAt: form.get("dueAt") ? new Date(String(form.get("dueAt"))).toISOString() : undefined, commitmentId: commitmentId || undefined, role: form.get("role") || undefined, originEvidenceRef: origin }; await workRequest("/api/tasks", { method: "POST", body: JSON.stringify({ ...payload, idempotencyKey: createAttempt.current.forPayload(payload) }) }); captureAttempt.current.succeeded(); createAttempt.current.succeeded(); setStatus("Task created."); onDone(); } catch (error) { if (isDefinitiveAttemptFailure(error)) { captureAttempt.current.succeeded(); createAttempt.current.succeeded(); } setStatus(error instanceof Error ? error.message : "Task was not created"); }
  }
  return <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-border bg-surface p-4"><h2 className="font-semibold">Create task</h2><Labeled label="Title"><Input name="title" required /></Labeled><Labeled label="Description"><Textarea name="description" /></Labeled><div className="grid gap-4 sm:grid-cols-2"><Labeled label="Priority"><select name="priority" className="h-10 rounded-md border bg-surface px-3"><option value="">Unset</option>{["p1","p2","p3","p4"].map((p)=><option key={p}>{p}</option>)}</select></Labeled><Labeled label="Due"><Input name="dueAt" type="datetime-local" /></Labeled><Labeled label="Commitment"><select name="commitmentId" disabled={Boolean(optionsStatus)} className="h-10 rounded-md border bg-surface px-3"><option value="">None</option>{commitments.map((item) => <option key={item.commitment_id} value={item.commitment_id}>{item.title}</option>)}</select></Labeled><Labeled label="Role"><select name="role" className="h-10 rounded-md border bg-surface px-3"><option value="">None</option><option value="follow_up">Follow up</option></select></Labeled></div>{optionsStatus ? <p role="status" className="text-sm text-muted">{optionsStatus}</p> : null}<Labeled label="Origin note" hint="Saved through Quick Capture before the task is attempted."><Textarea name="origin" required /></Labeled><Button type="submit">Create task</Button><p role="status" className="text-sm text-muted">{status}</p></form>;
}

function CommitmentCreate({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState("");
  const [counterparties, setCounterparties] = useState<readonly CounterpartyOption[]>([]);
  const [optionsStatus, setOptionsStatus] = useState("Loading verified counterparties…");
  const [optionsTruncated, setOptionsTruncated] = useState(false);
  const captureAttempt = useRef(createAttemptKey("commitment-origin")); const createAttempt = useRef(createAttemptKey("commitment-create"));
  useEffect(() => {
    const controller = new AbortController();
    void workRequest<{ counterparty_options: readonly CounterpartyOption[]; counterparty_options_truncated?: boolean }>("/api/commitments?pageSize=1", { signal: controller.signal })
      .then((answer) => { setCounterparties(requiredCollection(answer.counterparty_options, "counterparty_options")); setOptionsTruncated(Boolean(answer.counterparty_options_truncated)); setOptionsStatus(""); })
      .catch((error) => { if (!controller.signal.aborted) setOptionsStatus(error instanceof Error ? error.message : "Verified counterparties are unavailable"); });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const note = String(form.get("origin")); const counterpartyPersonId = String(form.get("counterparty") ?? ""); if (!counterparties.some((item) => item.person_id === counterpartyPersonId)) { setStatus("Choose a verified counterparty from the list."); return; } setStatus("Saving evidence…"); try { const origin = await captureEvidence(note, "commitment-origin", captureAttempt.current.forPayload({ note })); setStatus("Creating commitment…"); const payload = { summary: form.get("summary"), counterpartyPersonId, direction: form.get("direction"), dueAt: form.get("dueAt") ? new Date(String(form.get("dueAt"))).toISOString() : undefined, originEvidenceRef: origin }; await workRequest("/api/commitments", { method: "POST", body: JSON.stringify({ ...payload, idempotencyKey: createAttempt.current.forPayload(payload) }) }); captureAttempt.current.succeeded(); createAttempt.current.succeeded(); setStatus("Commitment created."); onDone(); } catch (error) { if (isDefinitiveAttemptFailure(error)) { captureAttempt.current.succeeded(); createAttempt.current.succeeded(); } setStatus(error instanceof Error ? error.message : "Commitment was not created"); } }
  return <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-border bg-surface p-4"><h2 className="font-semibold">Create commitment</h2><Labeled label="Summary"><Input name="summary" required /></Labeled><div className="grid gap-4 sm:grid-cols-2"><Labeled label="Counterparty"><select name="counterparty" required disabled={Boolean(optionsStatus) || counterparties.length === 0} className="h-10 rounded-md border bg-surface px-3"><option value="">Choose a person</option>{counterparties.map((item) => <option key={item.person_id} value={item.person_id}>{item.display_name}</option>)}</select></Labeled><Labeled label="Direction"><select name="direction" className="h-10 rounded-md border bg-surface px-3"><option value="owed_to_principal">Owed to me</option><option value="owed_by_principal">Owed by me</option></select></Labeled><Labeled label="Due"><Input name="dueAt" type="datetime-local" /></Labeled></div>{optionsStatus ? <p role="status" className="text-sm text-muted">{optionsStatus}</p> : counterparties.length === 0 ? <p role="status" className="text-sm text-muted">No verified relationship people are available for selection.</p> : optionsTruncated ? <p role="status" className="text-sm text-muted">Showing the first 100 verified people.</p> : null}<Labeled label="Origin note" hint="Saved through Quick Capture before the commitment is attempted."><Textarea name="origin" required /></Labeled><Button type="submit" disabled={counterparties.length === 0}>Create commitment</Button><p role="status" className="text-sm text-muted">{status}</p></form>;
}
