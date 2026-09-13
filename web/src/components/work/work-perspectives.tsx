"use client";

/**
 * Work perspectives: List, Board and Calendar (WP-TUX-06).
 *
 * Board and Calendar are operational surfaces, not read-only renderings of the
 * same page. Both drive the *shared* Task-operation machinery extracted in this
 * package's Phase 0 — `useTaskRowOperations` for the binder, awaited-intent
 * confirmation and focus return, and `task-operation-controls` for the
 * affordances themselves — so there is exactly one mutation path, one
 * confirmation model and one focus model across all three perspectives. Nothing
 * in this file fetches, retries, keys an idempotent attempt or reconciles a
 * version.
 *
 * The row each surface holds is a display projection, never write authority. The
 * binder canonical-hydrates at the first versioned write and sends that version,
 * so a stale board or calendar version can never reach the server — and neither
 * surface pays one detail read per card to make its controls usable.
 */

import {
  stopPropagation,
  TaskConflictPanel,
  TaskDueOperationControl,
  TaskStatusOperationControl,
  TaskTerminalActions,
} from "@/components/tasks/task-operation-controls";
import { useTaskRowOperations } from "@/components/tasks/use-task-row-operations";
import { TaskListRow } from "@/components/work/task-list-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { CommitmentRow, TaskRow, WaitingOnRow } from "@/contracts/work";
import type { WorkPerspective } from "@/lib/api/work-url";
import {
  formatTaskDue,
  formatTaskPriority,
  formatTaskStatus,
  TASK_ACTIVE_STATUSES,
  TASK_DUE_FIELD_LABEL,
  TASK_PLANNED_FOR_LABEL,
  TASK_SNOOZED_UNTIL_LABEL,
  type TaskActiveStatus,
} from "@/lib/tasks/presentation";

type CommitmentLike = CommitmentRow | WaitingOnRow;

/**
 * The Board's permanent columns.
 *
 * Exactly the four active lifecycle states, and deliberately not the two
 * terminal ones. A closed or cancelled Task is finished work; standing a
 * permanent column for it turns the board into an archive the Principal has to
 * read past every time, and the Completed Work view already answers that
 * question properly. A Task that becomes terminal therefore leaves the board
 * rather than moving to a "done" pile — there is no such column to move to.
 */
const BOARD_COLUMNS: readonly TaskActiveStatus[] = TASK_ACTIVE_STATUSES;

/** Test-id namespaces for the shared affordances rendered in these surfaces. */
const BOARD_CARD_TEST_ID = "task-board-card";
const CALENDAR_MARKER_TEST_ID = "task-calendar-marker";

/** Product copy owned by these surfaces. Everything else comes from the shared modules. */
const COMMENT_ACTION_LABEL = "Comment";

function words(value: string) {
  return value.replaceAll("_", " ");
}

function dateText(value: string) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function obligation(row: CommitmentLike) {
  if (!("direction" in row)) return "Waiting on a verified counterparty";
  const person = row.counterparty?.display_name ?? "Unresolved counterparty";
  return row.direction === "owed_by_principal" ? `You owe ${person}` : `${person} owes you`;
}

/* ------------------------------------------------------------------ *
 * Board
 * ------------------------------------------------------------------ */

interface BoardTaskCardProps {
  task: TaskRow;
  selected: boolean;
  onSelect(taskId: string): void;
  onOpen(type: "task", id: string, title: string, trigger: HTMLElement): void;
  onOpenActivity?(taskId: string, title: string, trigger: HTMLElement): void;
  onMutationConfirmed?(input: { taskId: string; kind: string }): void;
}

function BoardTaskCard({
  task,
  selected,
  onSelect,
  onOpen,
  onOpenActivity,
  onMutationConfirmed,
}: BoardTaskCardProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLDivElement>({
    taskId: task.task_id,
    task,
    onMutationConfirmed,
  });
  const { ops, civilClock, rowRef, busy } = operations;

  /*
    Every word the card says about this Task comes from the display base, not
    from the held canonical snapshot alone. The snapshot is a reading of one
    moment and the card does not remount while the Task stays listed, so reading
    the name from it would pin the card to whatever was true at mount: rename the
    Task from its own detail sheet and the board would go on showing the old name
    in its link and in every control's accessible name. This is exactly how the
    List row derives its identity.
  */
  const title = ops.display?.title ?? task.title;
  const priority = ops.display?.priority ?? task.priority;
  /*
    Due is read from the binder rather than the projection so the phrase follows
    an optimistic change and its rollback, instead of contradicting the Due
    control sitting beside it.
  */
  const due = formatTaskDue(ops.due.value, civilClock);

  return (
    <div
      ref={rowRef}
      data-testid={BOARD_CARD_TEST_ID}
      data-work-item={task.task_id}
      aria-busy={busy || undefined}
      className="flex min-w-0 flex-col gap-2 rounded-[var(--radius-md)] border border-border-subtle bg-surface p-3"
    >
      {/* Line one: selection and identity. The card's only link lives here. */}
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
          data-testid="task-board-card-title"
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
          <span className="shrink-0 self-center text-sm text-text-muted">
            {formatTaskPriority(priority)}
          </span>
        ) : null}
      </div>

      {/*
        The Due phrase, where it is the thing the Principal needs at a glance.
        A board is scanned, not read, so a Task that is already late or due today
        says so on the face of the card; anything further out is left to the Due
        control below rather than restated twice on one card.
      */}
      {due.tone === "overdue" || due.tone === "today" ? (
        <p data-testid="task-board-card-due-phrase" className="min-w-0 text-sm text-text-muted">
          {due.phrase}
        </p>
      ) : null}

      {/* Line two: the two inline field edits. */}
      <div className="flex min-w-0 flex-wrap items-start gap-3">
        <TaskStatusOperationControl taskTitle={title} operations={operations} />
        <TaskDueOperationControl taskTitle={title} operations={operations} />
      </div>

      {/* Line three: Comment, Close, and More (which holds Cancel). */}
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <Button
          variant="ghost"
          className="min-h-11 min-w-11"
          data-testid="task-board-card-comment"
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

        <TaskTerminalActions
          taskTitle={title}
          operations={operations}
          testIdPrefix={BOARD_CARD_TEST_ID}
        />
      </div>

      <TaskConflictPanel
        taskTitle={title}
        operations={operations}
        testIdPrefix={BOARD_CARD_TEST_ID}
      />
    </div>
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
              <TaskListRow
                task={task}
                selected={props.selectedTaskIds.includes(task.task_id)}
                onSelect={props.onSelectTask}
                onOpen={props.onOpen}
                onOpenActivity={props.onOpenActivity}
                onMutationConfirmed={props.onTaskMutationConfirmed}
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
    /*
      A vertical stack of columns, never a horizontal strip: the board must not
      grow `overflow-x` or scroll-snap, which would put Work behind a sideways
      carousel on the surface it is read on most.
    */
    <div role="region" aria-label="Task lifecycle board" className="grid gap-4">
      {BOARD_COLUMNS.map((lifecycle) => {
        /*
          Column membership follows the projection the server last answered with,
          never a client-side optimistic derivation. Moving a card between columns
          while its own write is still in flight would reparent it, React would
          unmount and remount it, and the card would lose the very write it was
          showing — no rollback on a refusal, and nowhere to put a 409. The
          optimistic answer the user needs is on the card's own Status control;
          the move itself lands when the confirmed mutation revalidates the page.
        */
        const members = rows.filter((task) => task.lifecycle_state === lifecycle);
        return (
          <section key={lifecycle} aria-labelledby={`task-column-${lifecycle}`} className="rounded-xl bg-surface-subtle p-3">
            <h2 id={`task-column-${lifecycle}`} className="mb-3 font-semibold">
              {formatTaskStatus(lifecycle)} <span className="text-sm text-muted">({members.length})</span>
            </h2>
            <div className="grid gap-3">
              {members.map((task) => (
                <BoardTaskCard
                  key={task.task_id}
                  task={task}
                  selected={props.selectedTaskIds.includes(task.task_id)}
                  onSelect={props.onSelectTask}
                  onOpen={props.onOpen}
                  onOpenActivity={props.onOpenActivity}
                  onMutationConfirmed={props.onTaskMutationConfirmed}
                />
              ))}
            </div>
            {members.length === 0 ? <p className="text-sm text-muted">No matching tasks in this column.</p> : null}
          </section>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Calendar
 * ------------------------------------------------------------------ */

interface TaskMarker {
  readonly key: string;
  readonly at: string;
  readonly label: string;
  readonly title: string;
  readonly type: "task";
  readonly id: string;
  /** Present only on the Due marker, which is the one dated field a user may move. */
  readonly task: TaskRow | null;
}

interface CommitmentMarker {
  readonly key: string;
  readonly at: string;
  readonly label: string;
  readonly title: string;
  readonly type: "commitment";
  readonly id: string;
  readonly task: null;
}

type Marker = TaskMarker | CommitmentMarker;

function MarkerLink({ marker, onOpen }: {
  marker: Marker;
  onOpen: WorkPerspectivesProps["onOpen"];
}) {
  return (
    <a
      href={`/work/${marker.type === "task" ? "tasks" : "commitments"}/${encodeURIComponent(marker.id)}`}
      className="text-left focus-visible:rounded focus-visible:outline focus-visible:outline-2"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onOpen(marker.type, marker.id, marker.title, event.currentTarget);
      }}
    >
      <Badge tone={marker.type === "task" ? "green" : "coral"}>{marker.label}</Badge>
      <span className="ml-2 font-medium text-text-primary">{marker.title}</span>
    </a>
  );
}

/**
 * The one editable marker on the Calendar.
 *
 * Due is the Principal's own commitment about when work is wanted, so it is
 * movable from where they are reading it. Planned-for and Snoozed-until are not:
 * they answer different questions, and the shared `changeDue` sends due fields
 * alone, so moving a deadline from here can never quietly reschedule planned work
 * or re-arm a snooze.
 */
function CalendarDueMarker({ marker, task, props }: {
  marker: TaskMarker;
  task: TaskRow;
  props: WorkPerspectivesProps;
}) {
  const operations = useTaskRowOperations<HTMLLIElement>({
    taskId: task.task_id,
    task,
    onMutationConfirmed: props.onTaskMutationConfirmed,
  });
  const { ops, rowRef, busy } = operations;
  const title = ops.display?.title ?? task.title;

  return (
    <li
      ref={rowRef}
      data-testid={CALENDAR_MARKER_TEST_ID}
      data-work-item={marker.id}
      aria-busy={busy || undefined}
      className="grid gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-[10rem_1fr]"
    >
      <time className="text-sm font-medium" dateTime={marker.at}>{dateText(marker.at)}</time>
      <div className="flex min-w-0 flex-col gap-2">
        <MarkerLink marker={{ ...marker, title }} onOpen={props.onOpen} />
        <div className="flex min-w-0 flex-wrap items-start gap-2">
          <TaskDueOperationControl taskTitle={title} operations={operations} />
        </div>
        <TaskConflictPanel
          taskTitle={title}
          operations={operations}
          testIdPrefix={CALENDAR_MARKER_TEST_ID}
        />
      </div>
    </li>
  );
}

function CalendarPerspective(props: WorkPerspectivesProps) {
  const markers: readonly Marker[] = props.commitments
    ? (props.rows as readonly CommitmentLike[]).flatMap<Marker>((row) => row.due_date
        ? [{ key: `${row.commitment_id}-due`, at: row.due_date, label: "Obligation due", title: row.title, type: "commitment", id: row.commitment_id, task: null }]
        : [])
    : (props.rows as readonly TaskRow[]).flatMap<Marker>((task) => [
        /*
          One marker per dated field, each said in the language the field
          actually means. `Due` is the deadline, `Planned for` is when the work
          is meant to happen, `Snoozed until` is when it comes back — the old
          `Deadline` / `Planned work` / `Available after` wording described three
          different things in three vocabularies none of the rest of Tasks uses.
        */
        task.due_at ? { key: `${task.task_id}-due`, at: task.due_at, label: TASK_DUE_FIELD_LABEL, title: task.title, type: "task" as const, id: task.task_id, task } : null,
        task.scheduled_at ? { key: `${task.task_id}-scheduled`, at: task.scheduled_at, label: TASK_PLANNED_FOR_LABEL, title: task.title, type: "task" as const, id: task.task_id, task: null } : null,
        task.deferred_until ? { key: `${task.task_id}-deferred`, at: task.deferred_until, label: TASK_SNOOZED_UNTIL_LABEL, title: task.title, type: "task" as const, id: task.task_id, task: null } : null,
      ].filter((item): item is TaskMarker => item !== null));
  const ordered = [...markers].sort((left, right) => left.at.localeCompare(right.at) || left.key.localeCompare(right.key));
  return (
    <section aria-labelledby="calendar-heading">
      <h2 id="calendar-heading" className="text-lg font-semibold">Work calendar</h2>
      <p className="mt-1 text-sm text-muted">Dates keep their original meaning. This view rearranges the current page; it does not add or hide work.</p>
      {ordered.length ? (
        <ol className="mt-4 grid gap-2">
          {ordered.map((marker) => marker.task
            ? <CalendarDueMarker key={marker.key} marker={marker} task={marker.task} props={props} />
            : (
              <li key={marker.key} data-work-item={marker.id} className="grid gap-2 rounded-lg border bg-surface p-3 sm:grid-cols-[10rem_1fr]">
                <time className="text-sm font-medium" dateTime={marker.at}>{dateText(marker.at)}</time>
                <MarkerLink marker={marker} onOpen={props.onOpen} />
              </li>
            ))}
        </ol>
      ) : <p className="mt-4 rounded-lg border bg-surface p-4 text-sm text-muted">No dated items on this page.</p>}
    </section>
  );
}

export interface WorkPerspectivesProps {
  perspective: WorkPerspective;
  rows: readonly TaskRow[] | readonly CommitmentLike[];
  commitments: boolean;
  selectedTaskIds: readonly string[];
  onSelectTask: (taskId: string) => void;
  onOpen: (type: "task" | "commitment", id: string, title: string, trigger: HTMLElement) => void;
  /** Opens the Task Activity surface. */
  onOpenActivity?: (taskId: string, title: string, trigger: HTMLElement) => void;
  /** A confirmed Task mutation, so Work can reconcile the query. */
  onTaskMutationConfirmed?: (input: { taskId: string; kind: string }) => void;
}

export function WorkPerspectives(props: WorkPerspectivesProps) {
  if (props.perspective === "board") return <BoardPerspective {...props} />;
  if (props.perspective === "calendar") return <CalendarPerspective {...props} />;
  return <ListPerspective {...props} />;
}
