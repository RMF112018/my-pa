"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { SurfaceState } from "@/components/ui/surface-state";
import { Textarea } from "@/components/ui/textarea";
import { CommitmentDetailView, TaskDetailView } from "@/components/work/work-detail";
import { WorkPerspectives } from "@/components/work/work-perspectives";
import { browserWorkClock, captureEvidence, createAttemptKey, isDefinitiveAttemptFailure, workRequest, type ApiFailure } from "@/lib/api/work-client";
import { parseWorkUrlState, WORK_PERSPECTIVES, WORK_VIEWS, type WorkPerspective, type WorkUrlState, type WorkView } from "@/lib/api/work-url";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type {
  CommitmentRow,
  CounterpartyOption,
  TaskBulkConfirmReceipt,
  TaskBulkMutation,
  TaskBulkPreviewReceipt,
  TaskDetail,
  TaskLifecycle,
  TaskPriority,
  TaskRow,
  WaitingOnRow,
} from "@/contracts/work";

type ReadFailureKind = "authentication" | "authorization" | "not_found" | "validation" | "offline" | "unavailable";

function classifyReadFailure(error: unknown): ReadFailureKind {
  const failure = error as ApiFailure;
  if (failure.status === 401 || failure.errorClass === "authentication") return "authentication";
  if (failure.status === 403 || failure.errorClass === "authorization" || failure.errorClass === "policy_denied") return "authorization";
  if (failure.status === 404 || failure.errorClass === "not_found") return "not_found";
  if (failure.status === 400 || failure.status === 422 || failure.errorClass === "validation") return "validation";
  if (failure.status === undefined) return "offline";
  return "unavailable";
}

const FAILURE_TITLE: Record<ReadFailureKind, string> = {
  authentication: "Session expired",
  authorization: "Work access was refused",
  not_found: "Work record was not found",
  validation: "Work filters were not valid",
  offline: "You appear to be offline",
  unavailable: "Work is unavailable",
};

function Labeled({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="grid gap-1 text-sm font-medium text-moss-slate"><span>{label}</span>{children}{hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}</label>;
}

const LABEL: Record<WorkView, string> = { overdue: "Overdue", today: "Today", upcoming: "Upcoming", unscheduled: "Unscheduled", waiting: "Waiting", blocked: "Blocked", "recently-updated": "Recently updated", "all-open": "All open", completed: "Completed", commitments: "Commitments" };
const PERSPECTIVE_LABEL: Record<WorkPerspective, string> = { list: "List", board: "Board", calendar: "Calendar" };
const DEFAULT_STATE = parseWorkUrlState({});

export function Workbench({ initialState = DEFAULT_STATE }: { initialState?: WorkUrlState }) {
  const [view, setView] = useState<WorkView>(initialState.view);
  const [perspective, setPerspective] = useState<WorkPerspective>(initialState.perspective);
  const [rows, setRows] = useState<readonly TaskRow[] | readonly CommitmentRow[] | readonly WaitingOnRow[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "failed">("loading");
  const [message, setMessage] = useState("");
  const [failureKind, setFailureKind] = useState<ReadFailureKind>("unavailable");
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
  const [selectedTaskIds, setSelectedTaskIds] = useState<readonly string[]>([]);
  const [detail, setDetail] = useState<{ type: "task" | "commitment"; id: string; title: string } | undefined>(
    initialState.task ? { type: "task", id: initialState.task, title: "Task detail" }
      : initialState.commitmentId ? { type: "commitment", id: initialState.commitmentId, title: "Commitment detail" }
      : undefined,
  );
  const readGeneration = useRef(0);
  const activeRead = useRef<AbortController | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);
  const transitionAttempts = useRef(new Map<string, ReturnType<typeof createAttemptKey>>());

  const load = useCallback(async () => {
    activeRead.current?.abort();
    const controller = new AbortController();
    activeRead.current = controller;
    const generation = ++readGeneration.current;
    setState("loading"); setMessage("");
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
        const found = data.commitments ?? data.waiting_on ?? [];
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
        setRows(data.tasks ?? []); setDisclosure(data.disclosure); setNextCursor(data.disclosure?.nextCursor ?? ""); setPartial(data.disclosure?.coverage === "partial" || data.disclosure?.truncated === true); setState((data.tasks ?? []).length ? "ready" : "empty");
      }
    } catch (error) {
      if (generation !== readGeneration.current || controller.signal.aborted) return;
      setFailureKind(classifyReadFailure(error)); setMessage(error instanceof Error ? error.message : "Work could not be read"); setState("failed");
    }
  }, [archiveMode, commitmentFilter, committedQuery, cursor, timezone, view]);
  useEffect(() => {
    void Promise.resolve().then(load);
    return () => activeRead.current?.abort();
  }, [load]);

  function select(next: WorkView) {
    setState("loading"); setRows([]); setView(next); setCursor("");
    const url = new URL(window.location.href); url.searchParams.set("view", next); url.searchParams.delete("cursor"); history.replaceState(null, "", url);
  }

  function sync(parameters: Record<string, string | undefined>) {
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(parameters)) {
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
    }
    history.replaceState(null, "", url);
  }

  function choosePerspective(next: WorkPerspective) {
    setPerspective(next);
    sync({ perspective: next === "list" ? undefined : next });
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

  async function moveTask(task: TaskRow, toState: TaskLifecycle) {
    if (task.lifecycle_state === toState) return;
    setMessage(`Reading the current version before moving ${task.title}…`);
    try {
      const current = await workRequest<{ task: TaskDetail }>(`/api/tasks/${encodeURIComponent(task.task_id)}`);
      if (current.task.lifecycle_state === toState) {
        transitionAttempts.current.delete(`${task.task_id}:${toState}`);
        setMessage(`${task.title} is already ${toState.replaceAll("_", " ")} in canonical state.`);
        await load();
        return;
      }
      const key = `${task.task_id}:${toState}`;
      const attempt = transitionAttempts.current.get(key) ?? createAttemptKey("task-board-transition");
      transitionAttempts.current.set(key, attempt);
      const material = { toState, expectedVersion: current.task.version };
      const answer = await workRequest<{ replayed?: boolean }>(`/api/tasks/${encodeURIComponent(task.task_id)}/transition`, {
        method: "POST",
        body: JSON.stringify({ ...material, idempotencyKey: attempt.forPayload(material) }),
      });
      attempt.succeeded(); transitionAttempts.current.delete(key);
      setMessage(`${answer.replayed ? "Replayed" : "Persisted"} lifecycle move to ${toState.replaceAll("_", " ")}.`);
      await load();
    } catch (error) {
      if (isDefinitiveAttemptFailure(error)) transitionAttempts.current.delete(`${task.task_id}:${toState}`);
      const problem = error as ApiFailure;
      setMessage(problem.status === 409
        ? "The Task changed on the server. Its original column remains canonical; open detail to compare and deliberately reapply."
        : problem.message || "The lifecycle move was not persisted; the original column remains canonical.");
    }
  }

  return <section aria-labelledby="work-heading" className="mx-auto max-w-5xl">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 id="work-heading" className="text-2xl font-semibold text-moss-slate">Work</h1><p className="mt-1 max-w-2xl text-sm text-muted">Tasks and commitments remain evidence-backed, versioned, and owned by the authenticated Work plane.</p></div>
      <Button onClick={() => setCreating((open) => !open)}>{creating ? "Cancel" : view === "commitments" ? "New commitment" : "New task"}</Button>
    </div>
    <nav aria-label="Work views" className="mt-6 flex gap-2 overflow-x-auto pb-2">
      {WORK_VIEWS.map((item) => <Button key={item} variant={view === item ? "primary" : "secondary"} onClick={() => select(item)} aria-current={view === item ? "page" : undefined}>{LABEL[item]}</Button>)}
    </nav>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-y border-moss-slate/10 py-3">
      <div role="group" aria-label="Work perspective" className="flex gap-2">{WORK_PERSPECTIVES.map((item) => <Button key={item} variant={perspective === item ? "primary" : "secondary"} onClick={() => choosePerspective(item)} aria-pressed={perspective === item}>{PERSPECTIVE_LABEL[item]}</Button>)}</div>
      <p className="text-xs text-muted">{selectedTaskIds.length ? `${selectedTaskIds.length} Task${selectedTaskIds.length === 1 ? "" : "s"} selected across perspectives` : "Select Tasks for admitted bulk actions"}</p>
    </div>
    {creating ? (view === "commitments" ? <CommitmentCreate onDone={() => { setCreating(false); void load(); }} /> : <TaskCreate onDone={() => { setCreating(false); void load(); }} />) : null}
    <div className="mt-5 flex flex-wrap items-end gap-3"><Labeled label={view === "commitments" ? "Search commitments" : "Search tasks"} hint={view === "commitments" && commitmentFilter === "waiting-on" ? "Search is unavailable for the dedicated Waiting On view." : undefined}><Input aria-label={view === "commitments" ? "Search commitments" : "Search tasks"} value={queryDraft} disabled={view === "commitments" && commitmentFilter === "waiting-on"} onChange={(event) => setQueryDraft(event.target.value)} placeholder={view === "commitments" ? "Search commitments" : "Search tasks"}/></Labeled><Button variant="secondary" disabled={view === "commitments" && commitmentFilter === "waiting-on"} onClick={() => { sync({ q: queryDraft || undefined, cursor: undefined }); setCursor(""); setCommittedQuery(queryDraft); }}>Search</Button>{view === "commitments" ? <Labeled label="Commitment focus"><select aria-label="Commitment filter" value={commitmentFilter} onChange={(event) => { const value = event.target.value as typeof commitmentFilter; sync({ commitment: value, cursor: undefined, q: value === "waiting-on" ? undefined : committedQuery || undefined }); setCommitmentFilter(value); setCursor(""); if (value === "waiting-on") { setQueryDraft(""); setCommittedQuery(""); } }} className="h-10 rounded-md border bg-surface px-3"><option value="all-open">Open</option><option value="due">Commitments due</option><option value="recently-updated">Recently updated</option><option value="waiting-on">Waiting on</option><option value="closed">Closed</option><option value="all">All</option></select></Labeled> : <Labeled label="Archive"><select aria-label="Archive" value={archiveMode} onChange={(event) => { const value = event.target.value as typeof archiveMode; sync({ archived: value, cursor: undefined }); setArchiveMode(value); setCursor(""); }} className="h-10 rounded-md border bg-surface px-3"><option value="exclude">Active only</option><option value="only">Archived only</option></select></Labeled>}</div>
    {message ? <p role="status" className="mt-4 rounded-lg border border-moss-slate/15 bg-surface p-3 text-sm text-muted">{message}</p> : null}
    <div className="mt-5" aria-live="polite">
      {state === "loading" ? <p role="status" className="rounded-xl border border-moss-slate/15 bg-surface p-4 text-sm text-muted">Reading the canonical Work plane…</p> : null}
      {state === "failed" ? <SurfaceState kind="unavailable" title={FAILURE_TITLE[failureKind]} detail={message}><Button className="mt-3" variant="secondary" onClick={() => void load()}>Retry Work read</Button></SurfaceState> : null}
      {state === "empty" ? <SurfaceState kind="empty" title={`${committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open") ? "No matching" : "No"} ${view === "commitments" ? "commitments" : LABEL[view].toLowerCase() + " tasks"}`} detail={committedQuery || archiveMode === "only" || (view === "commitments" && commitmentFilter !== "all-open") ? "The filtered read completed successfully, but no records matched these exact filters." : "The read completed and returned no records."} /> : null}
      {state === "ready" ? <WorkPerspectives perspective={perspective} rows={rows} commitments={view === "commitments"} selectedTaskIds={selectedTaskIds} onSelectTask={toggleTask} onOpen={openDetail} onMoveTask={(task, next) => void moveTask(task, next)} /> : null}
    </div>
    {disclosure && state !== "failed" ? <Disclosure details={disclosure} /> : null}
    {partial ? <SurfaceState kind="degraded" title="More Work is available" detail="This is a bounded canonical page. Continue to read the next page." /> : null}
    {nextCursor ? <Button variant="secondary" onClick={() => { sync({ cursor: nextCursor }); setCursor(nextCursor); }}>Next page</Button> : null}
    {view !== "commitments" && selectedTaskIds.length > 0 ? <BulkTaskEditor key={selectedTaskIds.join("|")} taskIds={selectedTaskIds} onConfirmed={() => { void load(); }} /> : null}
    <Sheet open={Boolean(detail)} onOpenChange={(open) => { if (!open) closeDetail(); }} title={detail?.title ?? "Work detail"} description="Canonical detail. Closing restores the Work query, selection, scroll, and focus context.">
      {detail?.type === "task" ? <TaskDetailView taskId={detail.id} embedded /> : null}
      {detail?.type === "commitment" ? <CommitmentDetailView commitmentId={detail.id} embedded /> : null}
    </Sheet>
  </section>;
}

function Disclosure({ details }: { details: DisclosureEnvelope }) {
  return <aside aria-label="Work answer disclosure" className="mt-4 rounded-lg border border-moss-slate/15 bg-surface p-3 text-xs text-muted">
    <p><span className="font-medium text-moss-slate">Authority:</span> {details.authority.replaceAll("_", " ")} · <span className="font-medium text-moss-slate">Coverage:</span> {details.coverage}</p>
    <p className="mt-1"><span className="font-medium text-moss-slate">Freshness:</span> {details.freshnessAt ? new Date(details.freshnessAt).toLocaleString() : "not disclosed"} · <span className="font-medium text-moss-slate">Truncation:</span> {details.truncated ? "yes" : "no"}</p>
    {details.limitations.length ? <ul className="mt-1 list-inside list-disc">{details.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul> : <p className="mt-1">No additional limitations were disclosed.</p>}
  </aside>;
}

function BulkTaskEditor({ taskIds, onConfirmed }: { taskIds: readonly string[]; onConfirmed: () => void }) {
  const [kind, setKind] = useState<"priority" | "transition">("priority");
  const [value, setValue] = useState("p1");
  const [status, setStatus] = useState("Ready to preview. No Task has changed.");
  const [preview, setPreview] = useState<TaskBulkPreviewReceipt>();
  const [mutations, setMutations] = useState<readonly TaskBulkMutation[]>();
  const [busy, setBusy] = useState(false);
  const previewAttempt = useRef(createAttemptKey("task-bulk-preview"));
  const confirmAttempt = useRef(createAttemptKey("task-bulk-confirm"));

  function failureMessage(error: unknown, phase: "preview" | "confirm") {
    const failure = error as { status?: number; code?: string; message?: string };
    if (failure.status === 409) {
      return phase === "confirm"
        ? "Confirmation was refused because the preview expired or canonical Task versions drifted. Nothing was applied; preview the retained selection again."
        : "Preview conflicted with current Task versions. Nothing was applied; the selection and action are retained."
    }
    if (failure.status === 503) return "The Work plane is unavailable. Nothing was applied; the selection and action are retained.";
    return failure.message ?? `Bulk ${phase} failed. Nothing was applied.`;
  }

  async function previewChanges() {
    setBusy(true); setPreview(undefined); setMutations(undefined); setStatus("Reading canonical Task versions before preview…");
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
      setStatus("Persisting a content-free preview receipt…");
      const receipt = await workRequest<TaskBulkPreviewReceipt>("/api/tasks/bulk/preview", {
        method: "POST",
        body: JSON.stringify({ mutations: normalized, idempotencyKey: previewAttempt.current.forPayload(normalized) }),
      });
      previewAttempt.current.succeeded(); setMutations(normalized); setPreview(receipt);
      setStatus(`${receipt.replayed ? "Replayed" : "Persisted"} preview: ${receipt.affected} affected, ${receipt.no_op} no-op, ${receipt.rejected} rejected. No Task has changed.`);
    } catch (error) { if (isDefinitiveAttemptFailure(error)) previewAttempt.current.succeeded(); setStatus(failureMessage(error, "preview")); }
    finally { setBusy(false); }
  }

  async function confirmChanges() {
    if (!preview || !mutations) return;
    if (Date.now() >= new Date(preview.expires_at).getTime()) {
      setPreview(undefined);
      setMutations(undefined);
      confirmAttempt.current.succeeded();
      setStatus("The preview expired before confirmation. Nothing was applied; preview the retained selection again.");
      return;
    }
    setBusy(true); setStatus("Confirming the exact previewed mutation set atomically…");
    try {
      const receipt = await workRequest<TaskBulkConfirmReceipt>("/api/tasks/bulk/confirm", {
        method: "POST",
        body: JSON.stringify({ bulkOperationId: preview.bulk_operation_id, idempotencyKey: confirmAttempt.current.forPayload({ bulkOperationId: preview.bulk_operation_id, mutations }), mutations }),
      });
      confirmAttempt.current.succeeded(); setPreview(undefined); setMutations(undefined); setStatus(`${receipt.replayed ? "Replayed" : "Persisted"} confirmation: ${receipt.affected} affected, ${receipt.no_op} no-op, ${receipt.rejected} rejected; ${receipt.history_ids.length} history receipts.`);
      onConfirmed();
    } catch (error) {
      const responseStatus = (error as { status?: number }).status;
      const definitive = responseStatus !== undefined && [400, 401, 403, 404, 409, 410, 422].includes(responseStatus);
      if (definitive) { confirmAttempt.current.succeeded(); setPreview(undefined); setMutations(undefined); }
      setStatus(failureMessage(error, "confirm"));
    } finally { setBusy(false); }
  }

  function changeKind(next: "priority" | "transition") {
    setKind(next); setValue(next === "priority" ? "p1" : "open"); setPreview(undefined); setMutations(undefined);
    setStatus("Action changed. Preview the retained selection before confirmation.");
  }

  return <section aria-labelledby="bulk-heading" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="bulk-heading" className="font-semibold text-moss-slate">Bulk change</h2><span className="text-sm text-muted">{taskIds.length} selected · maximum 100</span></div>
    <div className="mt-4 grid gap-4 sm:grid-cols-2">
      <Labeled label="Action"><select aria-label="Bulk action" value={kind} disabled={busy} onChange={(event) => changeKind(event.target.value as "priority" | "transition")} className="h-10 rounded-md border bg-surface px-3"><option value="priority">Set priority</option><option value="transition">Move lifecycle</option></select></Labeled>
      <Labeled label={kind === "priority" ? "Priority" : "Lifecycle state"}><select aria-label="Bulk value" value={value} disabled={busy} onChange={(event) => { setValue(event.target.value); setPreview(undefined); setMutations(undefined); setStatus("Action changed. Preview the retained selection before confirmation."); }} className="h-10 rounded-md border bg-surface px-3">{kind === "priority" ? <><option value="p1">P1</option><option value="p2">P2</option><option value="p3">P3</option><option value="p4">P4</option><option value="clear">Clear priority</option></> : <><option value="open">Open</option><option value="in_progress">In progress</option><option value="waiting">Waiting</option><option value="blocked">Blocked</option></>}</select></Labeled>
    </div>
    <div className="mt-4 flex flex-wrap gap-2"><Button type="button" variant="secondary" disabled={busy} onClick={() => void previewChanges()}>{busy && !preview ? "Previewing…" : preview ? "Refresh preview" : "Preview change"}</Button><Button type="button" disabled={busy || !preview} onClick={() => void confirmChanges()}>{busy && preview ? "Confirming…" : "Confirm exact preview"}</Button></div>
    {preview ? <p className="mt-3 text-xs text-muted">Preview {preview.bulk_operation_id} expires <time dateTime={preview.expires_at}>{new Date(preview.expires_at).toLocaleString()}</time>.</p> : null}
    <p role="status" className="mt-3 text-sm text-muted">{status}</p>
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
      .then((answer) => { setCommitments(answer.commitments ?? []); setOptionsStatus(""); })
      .catch((error) => { if (!controller.signal.aborted) setOptionsStatus(error instanceof Error ? error.message : "Verified commitments are unavailable"); });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setStatus("Saving evidence…"); const form = new FormData(event.currentTarget);
    const note = String(form.get("origin"));
    const commitmentId = String(form.get("commitmentId") ?? "");
    if (commitmentId && !commitments.some((item) => item.commitment_id === commitmentId)) { setStatus("Choose a verified commitment from the list."); return; }
    try { const origin = await captureEvidence(note, "task-origin", captureAttempt.current.forPayload({ note })); setStatus("Creating task…"); const payload = { title: form.get("title"), description: form.get("description") || undefined, priority: form.get("priority") || undefined, dueAt: form.get("dueAt") ? new Date(String(form.get("dueAt"))).toISOString() : undefined, commitmentId: commitmentId || undefined, role: form.get("role") || undefined, originEvidenceRef: origin }; await workRequest("/api/tasks", { method: "POST", body: JSON.stringify({ ...payload, idempotencyKey: createAttempt.current.forPayload(payload) }) }); captureAttempt.current.succeeded(); createAttempt.current.succeeded(); setStatus("Task persisted."); onDone(); } catch (error) { if (isDefinitiveAttemptFailure(error)) { captureAttempt.current.succeeded(); createAttempt.current.succeeded(); } setStatus(error instanceof Error ? error.message : "Task was not created"); }
  }
  return <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-moss-slate/15 bg-surface p-4"><h2 className="font-semibold">Create task</h2><Labeled label="Title"><Input name="title" required /></Labeled><Labeled label="Description"><Textarea name="description" /></Labeled><div className="grid gap-4 sm:grid-cols-2"><Labeled label="Priority"><select name="priority" className="h-10 rounded-md border bg-surface px-3"><option value="">Unset</option>{["p1","p2","p3","p4"].map((p)=><option key={p}>{p}</option>)}</select></Labeled><Labeled label="Due"><Input name="dueAt" type="datetime-local" /></Labeled><Labeled label="Commitment"><select name="commitmentId" disabled={Boolean(optionsStatus)} className="h-10 rounded-md border bg-surface px-3"><option value="">None</option>{commitments.map((item) => <option key={item.commitment_id} value={item.commitment_id}>{item.title}</option>)}</select></Labeled><Labeled label="Role"><select name="role" className="h-10 rounded-md border bg-surface px-3"><option value="">None</option><option value="follow_up">Follow up</option></select></Labeled></div>{optionsStatus ? <p role="status" className="text-sm text-muted">{optionsStatus}</p> : null}<Labeled label="Origin note" hint="Saved through Quick Capture before the task is attempted."><Textarea name="origin" required /></Labeled><Button type="submit">Create task</Button><p role="status" className="text-sm text-muted">{status}</p></form>;
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
      .then((answer) => { setCounterparties(answer.counterparty_options ?? []); setOptionsTruncated(Boolean(answer.counterparty_options_truncated)); setOptionsStatus(""); })
      .catch((error) => { if (!controller.signal.aborted) setOptionsStatus(error instanceof Error ? error.message : "Verified counterparties are unavailable"); });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const note = String(form.get("origin")); const counterpartyPersonId = String(form.get("counterparty") ?? ""); if (!counterparties.some((item) => item.person_id === counterpartyPersonId)) { setStatus("Choose a verified counterparty from the list."); return; } setStatus("Saving evidence…"); try { const origin = await captureEvidence(note, "commitment-origin", captureAttempt.current.forPayload({ note })); setStatus("Creating commitment…"); const payload = { summary: form.get("summary"), counterpartyPersonId, direction: form.get("direction"), dueAt: form.get("dueAt") ? new Date(String(form.get("dueAt"))).toISOString() : undefined, originEvidenceRef: origin }; await workRequest("/api/commitments", { method: "POST", body: JSON.stringify({ ...payload, idempotencyKey: createAttempt.current.forPayload(payload) }) }); captureAttempt.current.succeeded(); createAttempt.current.succeeded(); setStatus("Commitment persisted."); onDone(); } catch (error) { if (isDefinitiveAttemptFailure(error)) { captureAttempt.current.succeeded(); createAttempt.current.succeeded(); } setStatus(error instanceof Error ? error.message : "Commitment was not created"); } }
  return <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-moss-slate/15 bg-surface p-4"><h2 className="font-semibold">Create commitment</h2><Labeled label="Summary"><Input name="summary" required /></Labeled><div className="grid gap-4 sm:grid-cols-2"><Labeled label="Counterparty"><select name="counterparty" required disabled={Boolean(optionsStatus) || counterparties.length === 0} className="h-10 rounded-md border bg-surface px-3"><option value="">Choose a person</option>{counterparties.map((item) => <option key={item.person_id} value={item.person_id}>{item.display_name}</option>)}</select></Labeled><Labeled label="Direction"><select name="direction" className="h-10 rounded-md border bg-surface px-3"><option value="owed_to_principal">Owed to me</option><option value="owed_by_principal">Owed by me</option></select></Labeled><Labeled label="Due"><Input name="dueAt" type="datetime-local" /></Labeled></div>{optionsStatus ? <p role="status" className="text-sm text-muted">{optionsStatus}</p> : counterparties.length === 0 ? <p role="status" className="text-sm text-muted">No verified relationship people are available for selection.</p> : optionsTruncated ? <p role="status" className="text-sm text-muted">Showing the first 100 verified people.</p> : null}<Labeled label="Origin note" hint="Saved through Quick Capture before the commitment is attempted."><Textarea name="origin" required /></Labeled><Button type="submit" disabled={counterparties.length === 0}>Create commitment</Button><p role="status" className="text-sm text-muted">{status}</p></form>;
}
