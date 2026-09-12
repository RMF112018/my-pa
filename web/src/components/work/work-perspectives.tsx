"use client";

import { TaskListRow } from "@/components/work/task-list-row";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { CommitmentRow, TaskLifecycle, TaskRow, WaitingOnRow } from "@/contracts/work";
import type { WorkPerspective } from "@/lib/api/work-url";

type CommitmentLike = CommitmentRow | WaitingOnRow;

const LIFECYCLES: readonly TaskLifecycle[] = [
  "open",
  "in_progress",
  "waiting",
  "blocked",
  "completed",
  "cancelled",
];

function words(value: string) {
  return value.replaceAll("_", " ");
}

function dateText(value: string) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function TaskDates({ task }: { task: TaskRow }) {
  return (
    <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
      {task.due_at ? <span>Deadline: {dateText(task.due_at)}</span> : null}
      {task.scheduled_at ? <span>Planned work: {dateText(task.scheduled_at)}</span> : null}
      {task.deferred_until ? <span>Available after: {dateText(task.deferred_until)}</span> : null}
      {!task.due_at && !task.scheduled_at && !task.deferred_until ? <span>No work date set</span> : null}
    </span>
  );
}

function obligation(row: CommitmentLike) {
  if (!("direction" in row)) return "Waiting on a verified counterparty";
  const person = row.counterparty?.display_name ?? "Unresolved counterparty";
  return row.direction === "owed_by_principal" ? `You owe ${person}` : `${person} owes you`;
}

function TaskCard({ task, selected, onSelect, onOpen }: {
  task: TaskRow;
  selected: boolean;
  onSelect: (taskId: string) => void;
  onOpen: (type: "task", id: string, title: string, trigger: HTMLElement) => void;
}) {
  const terminalMeaning = task.lifecycle_state === "cancelled"
    ? "terminal cancellation"
    : task.lifecycle_state === "completed"
      ? "terminal completion"
      : undefined;
  return (
    <Card className="min-w-0" data-work-item={task.task_id}>
      <div className="flex items-start gap-2">
        <input type="checkbox" className="mt-1 size-5 accent-[var(--interactive)]" aria-label={`Select ${task.title}`} checked={selected} onChange={() => onSelect(task.task_id)} />
        <a href={`/work/tasks/${encodeURIComponent(task.task_id)}`} className="min-w-0 flex-1 text-left focus-visible:rounded focus-visible:outline focus-visible:outline-2" onClick={(event) => { event.preventDefault(); onOpen("task", task.task_id, task.title, event.currentTarget); }}>
          <span className="flex flex-wrap items-center gap-2"><Badge tone="green">Task</Badge><span className="font-medium text-text-primary">{task.title}</span></span>
          <span className="mt-2 flex flex-wrap gap-2"><Badge>{words(task.lifecycle_state)}</Badge>{terminalMeaning ? <span className="text-sm text-muted">{terminalMeaning}</span> : null}{task.priority ? <Badge tone="gold">Priority {task.priority.toUpperCase()}</Badge> : null}</span>
          <TaskDates task={task} />
          <span className="mt-1 block text-xs text-muted">Updated {dateText(task.updated_at)}</span>
        </a>
      </div>
    </Card>
  );
}

function CommitmentCard({ row, onOpen }: {
  row: CommitmentLike;
  onOpen: (type: "commitment", id: string, title: string, trigger: HTMLElement) => void;
}) {
  const waiting = "follow_up_task_id" in row ? row : undefined;
  const counterparty = row.counterparty?.display_name ?? "Counterparty not resolved";
  return (
    <Card data-work-item={row.commitment_id}>
      <a href={`/work/commitments/${encodeURIComponent(row.commitment_id)}`} className="block w-full text-left focus-visible:rounded focus-visible:outline focus-visible:outline-2" onClick={(event) => { event.preventDefault(); onOpen("commitment", row.commitment_id, row.title, event.currentTarget); }}>
        <span className="flex flex-wrap items-center gap-2"><Badge tone="coral">Commitment</Badge><span className="font-medium text-text-primary">{row.title}</span></span>
        <span className="mt-2 block text-sm text-muted">{waiting ? `${counterparty} · waiting on` : obligation(row)} · {row.state}</span>
        {row.due_date ? <span className="mt-1 block text-xs text-muted">Obligation due: {dateText(row.due_date)}</span> : <span className="mt-1 block text-xs text-muted">No obligation deadline</span>}
        {waiting ? <span className="mt-1 block text-sm text-muted">Follow-up: {waiting.follow_up_task_title ?? "No linked follow-up Task"}{waiting.follow_up_task_state ? ` · ${words(waiting.follow_up_task_state)}` : ""}</span> : null}
      </a>
    </Card>
  );
}

function ListPerspective(props: WorkPerspectivesProps) {
  const taskRows = props.rows as readonly TaskRow[];
  const commitmentRows = props.rows as readonly CommitmentLike[];
  return (
    <ul aria-label="Work list" className="grid gap-2">
      {props.commitments
        ? commitmentRows.map((row) => <li key={row.commitment_id}><CommitmentCard row={row} onOpen={props.onOpen} /></li>)
        : taskRows.map((task) => (
            <li key={task.task_id}>
              {/*
                List gets the operational row; Board and Calendar keep the shared
                read-only card. The card is one component across all three
                perspectives, so putting operations on it would hand Board and
                Calendar a surface that belongs to a later package.
              */}
              <TaskListRow
                task={task}
                selected={props.selectedTaskIds.includes(task.task_id)}
                onSelect={props.onSelectTask}
                onOpen={props.onOpen}
                onOpenActivity={props.onOpenActivity}
                onMutationConfirmed={props.onTaskMutationConfirmed}
                onMutationDispatched={props.onTaskMutationDispatched}
              />
            </li>
          ))}
    </ul>
  );
}

function BoardPerspective(props: WorkPerspectivesProps) {
  if (props.commitments) {
    const rows = props.rows as readonly CommitmentLike[];
    return <div role="region" aria-label="Commitment board" className="grid gap-4 md:grid-cols-2">{["open", "closed"].map((state) => <section key={state} aria-labelledby={`commitment-column-${state}`} className="rounded-xl bg-surface-subtle p-3"><h2 id={`commitment-column-${state}`} className="mb-3 font-semibold capitalize">{state} <span className="text-sm text-muted">({rows.filter((row) => row.state === state).length})</span></h2><div className="grid gap-3">{rows.filter((row) => row.state === state).map((row) => <CommitmentCard key={row.commitment_id} row={row} onOpen={props.onOpen} />)}</div></section>)}</div>;
  }
  const rows = props.rows as readonly TaskRow[];
  return (
    <div role="region" aria-label="Task lifecycle board" className="grid gap-4">
      {LIFECYCLES.map((lifecycle) => {
        const members = rows.filter((task) => task.lifecycle_state === lifecycle);
        return <section key={lifecycle} aria-labelledby={`task-column-${lifecycle}`} className="rounded-xl bg-surface-subtle p-3"><h2 id={`task-column-${lifecycle}`} className="mb-3 font-semibold capitalize">{words(lifecycle)} <span className="text-sm text-muted">({members.length})</span></h2><div className="grid gap-3">{members.map((task) => <TaskCard key={task.task_id} task={task} selected={props.selectedTaskIds.includes(task.task_id)} onSelect={props.onSelectTask} onOpen={props.onOpen} />)}</div>{members.length === 0 ? <p className="text-sm text-muted">No matching tasks in this column.</p> : null}</section>;
      })}
    </div>
  );
}

function CalendarPerspective(props: WorkPerspectivesProps) {
  const markers = props.commitments
    ? (props.rows as readonly CommitmentLike[]).flatMap((row) => row.due_date ? [{ key: `${row.commitment_id}-due`, at: row.due_date, label: "Obligation due", title: row.title, type: "commitment" as const, id: row.commitment_id }] : [])
    : (props.rows as readonly TaskRow[]).flatMap((task) => [
        task.due_at ? { key: `${task.task_id}-due`, at: task.due_at, label: "Deadline", title: task.title, type: "task" as const, id: task.task_id } : null,
        task.scheduled_at ? { key: `${task.task_id}-scheduled`, at: task.scheduled_at, label: "Planned work", title: task.title, type: "task" as const, id: task.task_id } : null,
        task.deferred_until ? { key: `${task.task_id}-deferred`, at: task.deferred_until, label: "Available after", title: task.title, type: "task" as const, id: task.task_id } : null,
      ].filter((item): item is NonNullable<typeof item> => item !== null));
  const ordered = [...markers].sort((left, right) => left.at.localeCompare(right.at) || left.key.localeCompare(right.key));
  return <section aria-labelledby="calendar-heading"><h2 id="calendar-heading" className="text-lg font-semibold">Work calendar</h2><p className="mt-1 text-sm text-muted">Dates keep their original meaning. This view rearranges the current page; it does not add or hide work.</p>{ordered.length ? <ol className="mt-4 grid gap-2">{ordered.map((marker) => <li key={marker.key} className="grid gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-[10rem_1fr]"><time className="text-sm font-medium" dateTime={marker.at}>{dateText(marker.at)}</time><a href={`/work/${marker.type === "task" ? "tasks" : "commitments"}/${encodeURIComponent(marker.id)}`} className="text-left focus-visible:rounded focus-visible:outline focus-visible:outline-2" onClick={(event) => { event.preventDefault(); props.onOpen(marker.type, marker.id, marker.title, event.currentTarget); }}><Badge tone={marker.type === "task" ? "green" : "coral"}>{marker.label}</Badge><span className="ml-2 font-medium text-text-primary">{marker.title}</span></a></li>)}</ol> : <p className="mt-4 rounded-lg border bg-surface p-4 text-sm text-muted">No dated items on this page.</p>}</section>;
}

export interface WorkPerspectivesProps {
  perspective: WorkPerspective;
  rows: readonly TaskRow[] | readonly CommitmentLike[];
  commitments: boolean;
  selectedTaskIds: readonly string[];
  onSelectTask: (taskId: string) => void;
  onOpen: (type: "task" | "commitment", id: string, title: string, trigger: HTMLElement) => void;
  /** Opens the Task Activity surface. List only. */
  onOpenActivity?: (taskId: string, title: string, trigger: HTMLElement) => void;
  /** A confirmed Task mutation, so Work can reconcile the query. List only. */
  onTaskMutationConfirmed?: () => void;
  /** A dispatched Task mutation, so Work can capture ordering before anything moves. List only. */
  onTaskMutationDispatched?: (input: { taskId: string; kind: string }) => void;
}

export function WorkPerspectives(props: WorkPerspectivesProps) {
  if (props.perspective === "board") return <BoardPerspective {...props} />;
  if (props.perspective === "calendar") return <CalendarPerspective {...props} />;
  return <ListPerspective {...props} />;
}
