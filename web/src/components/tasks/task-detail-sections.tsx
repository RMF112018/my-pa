"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { TaskDetail, TaskPriority } from "@/contracts/work";
import {
  civilDayInZone,
  civilDayStartIso,
  formatTaskPlanningDate,
  formatTaskPriority,
  TASK_ARCHIVED_LABEL,
  TASK_CANCEL_ACTION_LABEL,
  TASK_CANCEL_CONFIRM_LABEL,
  TASK_PLANNED_FOR_LABEL,
  TASK_SNOOZED_UNTIL_LABEL,
  TASK_PRIORITY_LABELS,
  type TaskCivilClock,
  type TaskPresentationModel,
} from "@/lib/tasks/presentation";

/**
 * Compact, read-first Task detail (WP-POSTUX-04).
 *
 * Title, description and priority are text until explicitly edited. Status and
 * Due stay immediate. Planning, Context and Administrative remain collapsed.
 * Cancel and Refresh live under More. Every edit is still a bounded field- or
 * section-level mutation intent.
 */

const PRIORITY_TOKENS: readonly TaskPriority[] = ["p1", "p2", "p3", "p4"];
const KEEP_OPEN_LABEL = "Keep open";
const TOUCH_TARGET = "min-h-11 min-w-11";

export type TaskContextFact =
  | { state: "idle" }
  | { state: "absent"; message: string }
  | { state: "loading" }
  | { state: "unavailable"; message: string }
  | { state: "ready"; label: string };

function escapeCancelsEditor(event: KeyboardEvent<HTMLElement>, cancel: () => void) {
  if (event.key !== "Escape") return;
  if (event.nativeEvent.isComposing) return;
  event.preventDefault();
  event.stopPropagation();
  cancel();
}

/** Collapsed-by-default progressive section. */
function ProgressiveSection({
  title,
  children,
  testId,
  onToggle,
}: {
  title: ReactNode;
  children: ReactNode;
  testId: string;
  onToggle?(open: boolean): void;
}) {
  return (
    <details
      data-testid={testId}
      className="rounded-[var(--radius-lg)] border border-border-subtle bg-surface"
      onToggle={(event) => onToggle?.(event.currentTarget.open)}
    >
      <summary className="flex min-h-11 cursor-pointer items-center px-4 font-semibold text-text-primary">
        {title}
      </summary>
      <div className="border-t border-border-subtle p-4">{children}</div>
    </details>
  );
}

function TaskCancelUnderMore({
  taskTitle,
  disabled,
  pending,
  onCancelTask,
}: {
  taskTitle: string;
  disabled: boolean;
  pending: boolean;
  onCancelTask(): void;
}) {
  const [confirming, setConfirming] = useState(false);
  const restoreFocusRef = useRef(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const keepOpenRef = useRef<HTMLButtonElement | null>(null);
  const baseId = useId();
  const titleId = `${baseId}-title`;
  const descriptionId = `${baseId}-description`;

  useEffect(() => {
    if (confirming) {
      keepOpenRef.current?.focus();
      return;
    }
    if (!restoreFocusRef.current) return;
    restoreFocusRef.current = false;
    triggerRef.current?.focus();
  }, [confirming]);

  function dismiss() {
    restoreFocusRef.current = true;
    setConfirming(false);
  }

  return (
    <div className="flex flex-col gap-3">
      <Button
        ref={triggerRef}
        variant="ghost"
        disabled={disabled}
        data-prominence="secondary"
        data-testid="task-cancel-trigger"
        className={TOUCH_TARGET}
        aria-expanded={confirming}
        onClick={() => {
          if (disabled) return;
          setConfirming(true);
        }}
      >
        {TASK_CANCEL_ACTION_LABEL}
      </Button>
      {confirming ? (
        <div
          role="alertdialog"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          data-testid="task-cancel-confirmation"
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            dismiss();
          }}
          className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3"
        >
          <p id={titleId} className="text-sm font-medium text-text-primary">
            {TASK_CANCEL_ACTION_LABEL}
          </p>
          <p id={descriptionId} className="text-sm text-text-secondary">
            {`\u201C${taskTitle}\u201D will be cancelled, not closed.`}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              ref={keepOpenRef}
              variant="secondary"
              className={TOUCH_TARGET}
              data-testid="task-cancel-keep-open"
              onClick={dismiss}
            >
              {KEEP_OPEN_LABEL}
            </Button>
            <Button
              variant="danger"
              pending={pending}
              className={TOUCH_TARGET}
              data-testid="task-cancel-confirm"
              onClick={() => {
                if (pending) return;
                onCancelTask();
              }}
            >
              {TASK_CANCEL_CONFIRM_LABEL}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export interface TaskHeaderSectionProps {
  model: TaskPresentationModel;
  title: string;
  committedTitle: string;
  titleDirty: boolean;
  priority: TaskPriority | null;
  disabled: boolean;
  pending: boolean;
  statusControl: ReactNode;
  dueControl: ReactNode;
  closeControl: ReactNode;
  refreshControl: ReactNode;
  onTitleChange(next: string): void;
  onTitleSave(): void;
  onPriorityChange(next: TaskPriority | null): void;
  onCancelTask?(): void;
}

export function TaskHeaderSection({
  model,
  title,
  committedTitle,
  titleDirty,
  priority,
  disabled,
  pending,
  statusControl,
  dueControl,
  closeControl,
  refreshControl,
  onTitleChange,
  onTitleSave,
  onPriorityChange,
  onCancelTask,
}: TaskHeaderSectionProps) {
  const titleId = useId();
  const priorityId = useId();
  const [editingTitle, setEditingTitle] = useState(titleDirty);
  const [editingPriority, setEditingPriority] = useState(false);
  const titleEditRef = useRef<HTMLButtonElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const focusTitleEdit = useRef(false);
  const showTitleEditor = editingTitle || titleDirty;
  const terminal = Boolean(model.terminalSummary);

  useEffect(() => {
    if (showTitleEditor) titleInputRef.current?.focus();
  }, [showTitleEditor]);

  useEffect(() => {
    if (showTitleEditor || !focusTitleEdit.current) return;
    focusTitleEdit.current = false;
    titleEditRef.current?.focus();
  }, [showTitleEditor]);

  function cancelTitle() {
    if (title !== committedTitle) onTitleChange(committedTitle);
    focusTitleEdit.current = true;
    setEditingTitle(false);
  }

  const priorityEditor = editingPriority ? (
    <div className="grid gap-1">
      <label htmlFor={priorityId} className="text-sm font-medium text-text-primary">
        Priority
      </label>
      <Select
        id={priorityId}
        className="min-h-11"
        value={priority ?? ""}
        disabled={disabled || pending}
        autoFocus
        onChange={(event) => {
          onPriorityChange(event.target.value === "" ? null : (event.target.value as TaskPriority));
          setEditingPriority(false);
        }}
      >
        <option value="">{formatTaskPriority(null)}</option>
        {PRIORITY_TOKENS.map((token) => (
          <option key={token} value={token}>
            {TASK_PRIORITY_LABELS[token]}
          </option>
        ))}
      </Select>
    </div>
  ) : (
    <div className="grid gap-1">
      <p className="text-sm font-medium text-text-primary">Priority</p>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-text-secondary">{formatTaskPriority(priority)}</p>
        <Button
          size="sm"
          variant="secondary"
          className="min-h-11"
          disabled={disabled}
          data-testid="task-edit-priority"
          onClick={() => setEditingPriority(true)}
        >
          Edit priority
        </Button>
      </div>
    </div>
  );

  return (
    <header data-testid="task-summary" className="grid gap-4">
      {showTitleEditor ? (
        <div className="grid gap-2" onKeyDown={(event) => escapeCancelsEditor(event, cancelTitle)}>
          <h1 className="sr-only">{title}</h1>
          <label htmlFor={titleId} className="text-sm font-medium text-text-primary">
            Title
          </label>
          <Input
            ref={titleInputRef}
            id={titleId}
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            disabled={pending}
            className="min-h-11 text-2xl font-semibold"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              className="min-h-11"
              pending={pending}
              disabled={disabled || title.trim().length === 0}
              onClick={() => {
                focusTitleEdit.current = true;
                setEditingTitle(false);
                onTitleSave();
              }}
            >
              Save title
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="min-h-11"
              disabled={pending}
              onClick={cancelTitle}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-3">
          <h1 className="text-2xl font-semibold text-text-primary">{title}</h1>
          <Button
            ref={titleEditRef}
            size="sm"
            variant="secondary"
            className="min-h-11"
            disabled={disabled}
            data-testid="task-edit-title"
            onClick={() => setEditingTitle(true)}
          >
            Edit title
          </Button>
        </div>
      )}

      {terminal ? (
        <div className="grid gap-2 text-sm">
          <p>
            <span className="font-medium text-text-primary">Status</span>{" "}
            <span className="text-text-secondary">{model.statusLabel}</span>
          </p>
          <p>
            <span className="font-medium text-text-primary">Due</span>{" "}
            <span className="text-text-secondary">{model.due.phrase}</span>
          </p>
          {priorityEditor}
          <p className="text-sm text-muted" data-testid="task-terminal-summary">
            {model.terminalSummary}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-4">
          {statusControl}
          {dueControl}
          {priorityEditor}
        </div>
      )}

      {terminal ? (
        <details data-testid="task-more-actions">
          <summary className="flex min-h-11 cursor-pointer items-center font-medium text-text-primary">
            More
          </summary>
          <div className="mt-2 grid gap-3">{refreshControl}</div>
        </details>
      ) : (
        <div className="flex flex-wrap items-start gap-3">
          {closeControl}
          <details data-testid="task-more-actions">
            <summary className="flex min-h-11 cursor-pointer items-center font-medium text-text-primary">
              More
            </summary>
            <div className="mt-2 grid gap-3">
              {onCancelTask ? (
                <TaskCancelUnderMore
                  taskTitle={committedTitle}
                  disabled={disabled}
                  pending={pending}
                  onCancelTask={onCancelTask}
                />
              ) : null}
              {refreshControl}
            </div>
          </details>
        </div>
      )}
    </header>
  );
}

export interface TaskDescriptionSectionProps {
  description: string;
  committedDescription: string;
  descriptionDirty: boolean;
  disabled: boolean;
  pending: boolean;
  onDescriptionChange(next: string): void;
  onDescriptionSave(): void;
}

export function TaskDescriptionSection({
  description,
  committedDescription,
  descriptionDirty,
  disabled,
  pending,
  onDescriptionChange,
  onDescriptionSave,
}: TaskDescriptionSectionProps) {
  const fieldId = useId();
  const empty = description.trim().length === 0 && !descriptionDirty;
  const [editing, setEditing] = useState(descriptionDirty);
  const editRef = useRef<HTMLButtonElement | null>(null);
  const addRef = useRef<HTMLButtonElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const focusDescriptionTrigger = useRef<"add" | "edit" | null>(null);
  const showEditor = editing || descriptionDirty;

  useEffect(() => {
    if (showEditor) textareaRef.current?.focus();
  }, [showEditor]);

  useEffect(() => {
    if (showEditor || !focusDescriptionTrigger.current) return;
    const target = focusDescriptionTrigger.current;
    focusDescriptionTrigger.current = null;
    (target === "add" ? addRef : editRef).current?.focus();
  }, [showEditor]);

  function cancelDescription() {
    if (description !== committedDescription) onDescriptionChange(committedDescription);
    focusDescriptionTrigger.current = committedDescription.trim().length === 0 ? "add" : "edit";
    setEditing(false);
  }

  return (
    <section aria-labelledby="task-description-heading" className="grid gap-2">
      <h2 id="task-description-heading" className="font-semibold text-text-primary">
        Description
      </h2>
      {showEditor ? (
        <div className="grid gap-2" onKeyDown={(event) => escapeCancelsEditor(event, cancelDescription)}>
          <label htmlFor={fieldId} className="sr-only">
            Description
          </label>
          <Textarea
            ref={textareaRef}
            id={fieldId}
            value={description}
            onChange={(event) => onDescriptionChange(event.target.value)}
            disabled={pending}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              className="min-h-11"
              pending={pending}
              disabled={disabled}
              onClick={() => {
                focusDescriptionTrigger.current = empty ? "add" : "edit";
                setEditing(false);
                onDescriptionSave();
              }}
            >
              Save description
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="min-h-11"
              disabled={pending}
              onClick={cancelDescription}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : empty ? (
        <div className="grid gap-2">
          <p className="whitespace-pre-wrap text-sm text-text-secondary">No description.</p>
          <div>
            <Button
              ref={addRef}
              size="sm"
              variant="secondary"
              className="min-h-11"
              disabled={disabled}
              data-testid="task-add-description"
              onClick={() => setEditing(true)}
            >
              Add description
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-2">
          <p className="whitespace-pre-wrap text-sm text-text-primary">{description}</p>
          <div>
            <Button
              ref={editRef}
              size="sm"
              variant="secondary"
              className="min-h-11"
              disabled={disabled}
              data-testid="task-edit-description"
              onClick={() => setEditing(true)}
            >
              Edit description
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function CivilDateField({
  label,
  value,
  clock,
  disabled,
  pending,
  absent,
  onChange,
}: {
  label: string;
  value: string | null;
  clock: TaskCivilClock;
  disabled: boolean;
  pending: boolean;
  absent: string;
  onChange(next: string | null): void;
}) {
  const fieldId = useId();
  const civil = value ? civilDayInZone(value, clock.timezone) : "";
  return (
    <div className="grid gap-1">
      <label htmlFor={fieldId} className="text-sm font-medium text-text-primary">
        {label}
      </label>
      <p className="text-sm text-muted">{formatTaskPlanningDate(value, clock, absent)}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={fieldId}
          type="date"
          className="min-h-11"
          value={civil}
          disabled={disabled || pending}
          onChange={(event) =>
            onChange(event.target.value ? civilDayStartIso(event.target.value, clock.timezone) : null)
          }
        />
        {value ? (
          <Button
            size="sm"
            variant="secondary"
            className="min-h-11"
            disabled={disabled || pending}
            onClick={() => onChange(null)}
          >
            Clear {label.toLowerCase()}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function planningSummary(task: TaskDetail, clock: TaskCivilClock): string {
  const parts = ["Planning"];
  if (task.scheduled_at) {
    parts.push(`${TASK_PLANNED_FOR_LABEL} ${formatTaskPlanningDate(task.scheduled_at, clock, "")}`.trim());
  }
  if (task.deferred_until) {
    parts.push(`${TASK_SNOOZED_UNTIL_LABEL} ${formatTaskPlanningDate(task.deferred_until, clock, "")}`.trim());
  }
  return parts.join(" · ");
}

export interface TaskPlanningSectionProps {
  task: TaskDetail;
  clock: TaskCivilClock;
  disabled: boolean;
  pending: boolean;
  onPlannedForChange(next: string | null): void;
  onSnoozedUntilChange(next: string | null): void;
}

export function TaskPlanningSection({
  task,
  clock,
  disabled,
  pending,
  onPlannedForChange,
  onSnoozedUntilChange,
}: TaskPlanningSectionProps) {
  const [editing, setEditing] = useState(false);
  const planned = formatTaskPlanningDate(task.scheduled_at, clock, "Not planned");
  const snoozed = formatTaskPlanningDate(task.deferred_until, clock, "Not snoozed");

  return (
    <ProgressiveSection
      title={planningSummary(task, clock)}
      testId="task-planning-section"
      onToggle={(open) => {
        if (!open) setEditing(false);
      }}
    >
      <div className="grid gap-4">
        <div className="grid gap-2 text-sm">
          <p>
            <span className="font-medium text-text-primary">{TASK_PLANNED_FOR_LABEL}</span>{" "}
            <span className="text-text-secondary">{planned}</span>
          </p>
          <p>
            <span className="font-medium text-text-primary">{TASK_SNOOZED_UNTIL_LABEL}</span>{" "}
            <span className="text-text-secondary">{snoozed}</span>
          </p>
        </div>
        {editing ? (
          <>
            <CivilDateField
              label={TASK_PLANNED_FOR_LABEL}
              value={task.scheduled_at}
              clock={clock}
              disabled={disabled}
              pending={pending}
              absent="Not planned"
              onChange={onPlannedForChange}
            />
            <CivilDateField
              label={TASK_SNOOZED_UNTIL_LABEL}
              value={task.deferred_until}
              clock={clock}
              disabled={disabled}
              pending={pending}
              absent="Not snoozed"
              onChange={onSnoozedUntilChange}
            />
          </>
        ) : (
          <div>
            <Button
              size="sm"
              variant="secondary"
              className="min-h-11"
              disabled={disabled}
              onClick={() => setEditing(true)}
            >
              Edit planning
            </Button>
          </div>
        )}
      </div>
    </ProgressiveSection>
  );
}

function contextFactCopy(fact: TaskContextFact): string {
  if (fact.state === "ready") return fact.label;
  if (fact.state === "absent" || fact.state === "unavailable") return fact.message;
  if (fact.state === "loading" || fact.state === "idle") return "Loading…";
  return "";
}

/** One Context entry: a human label when available, a stated absence otherwise. Never a raw ID. */
function ContextEntry({ term, fact }: { term: string; fact: TaskContextFact }) {
  return (
    <div>
      <dt className="text-muted">{term}</dt>
      <dd>{contextFactCopy(fact)}</dd>
    </div>
  );
}

export interface TaskContextSectionProps {
  project: TaskContextFact;
  situation: TaskContextFact;
  commitment: TaskContextFact;
  role: TaskContextFact;
  onOpen?(): void;
}

export function TaskContextSection({
  project,
  situation,
  commitment,
  role,
  onOpen,
}: TaskContextSectionProps) {
  const opened = useRef(false);
  const [open, setOpen] = useState(false);
  return (
    <ProgressiveSection
      title="Context"
      testId="task-context-section"
      onToggle={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen || opened.current) return;
        opened.current = true;
        onOpen?.();
      }}
    >
      {open ? (
        <dl className="grid gap-3 text-sm">
          <ContextEntry term="Project" fact={project} />
          <ContextEntry term="Situation" fact={situation} />
          <ContextEntry term="Commitment" fact={commitment} />
          <ContextEntry term="Role" fact={role} />
        </dl>
      ) : null}
    </ProgressiveSection>
  );
}

export interface TaskAdministrativeSectionProps {
  archived: boolean;
  disabled: boolean;
  pending: boolean;
  onArchivedChange(next: boolean): void;
}

export function TaskAdministrativeSection({
  archived,
  disabled,
  pending,
  onArchivedChange,
}: TaskAdministrativeSectionProps) {
  const fieldId = useId();
  return (
    <ProgressiveSection
      title={archived ? "Administrative · Archived" : "Administrative"}
      testId="task-administrative-section"
    >
      <label htmlFor={fieldId} className="flex min-h-11 items-center gap-2 text-sm text-text-primary">
        <input
          id={fieldId}
          type="checkbox"
          checked={archived}
          disabled={disabled || pending}
          onChange={(event) => onArchivedChange(event.target.checked)}
        />
        {TASK_ARCHIVED_LABEL}
      </label>
    </ProgressiveSection>
  );
}

export interface TaskDetailSectionsProps {
  model: TaskPresentationModel;
  task: TaskDetail;
  clock: TaskCivilClock;
  title: string;
  titleDirty: boolean;
  priority: TaskPriority | null;
  disabled: boolean;
  pending: boolean;
  statusControl: ReactNode;
  dueControl: ReactNode;
  closeControl: ReactNode;
  refreshControl: ReactNode;
  description: string;
  descriptionDirty: boolean;
  comments: ReactNode;
  technicalDetails: ReactNode;
  project: TaskContextFact;
  situation: TaskContextFact;
  commitment: TaskContextFact;
  role: TaskContextFact;
  onTitleChange(next: string): void;
  onTitleSave(): void;
  onPriorityChange(next: TaskPriority | null): void;
  onDescriptionChange(next: string): void;
  onDescriptionSave(): void;
  onPlannedForChange(next: string | null): void;
  onSnoozedUntilChange(next: string | null): void;
  onArchivedChange(next: boolean): void;
  onCancelTask?(): void;
  onContextOpen?(): void;
}

export function TaskDetailSections(props: TaskDetailSectionsProps) {
  const {
    model,
    task,
    clock,
    title,
    titleDirty,
    priority,
    disabled,
    pending,
    statusControl,
    dueControl,
    closeControl,
    refreshControl,
    description,
    descriptionDirty,
    comments,
    technicalDetails,
    project,
    situation,
    commitment,
    role,
    onTitleChange,
    onTitleSave,
    onPriorityChange,
    onDescriptionChange,
    onDescriptionSave,
    onPlannedForChange,
    onSnoozedUntilChange,
    onArchivedChange,
    onCancelTask,
    onContextOpen,
  } = props;

  return (
    <div data-testid="task-detail-sections" className="flex flex-col gap-6">
      <TaskHeaderSection
        model={model}
        title={title}
        committedTitle={task.title}
        titleDirty={titleDirty}
        priority={priority}
        disabled={disabled}
        pending={pending}
        statusControl={statusControl}
        dueControl={dueControl}
        closeControl={closeControl}
        refreshControl={refreshControl}
        onTitleChange={onTitleChange}
        onTitleSave={onTitleSave}
        onPriorityChange={onPriorityChange}
        onCancelTask={onCancelTask}
      />
      <TaskDescriptionSection
        description={description}
        committedDescription={task.description ?? ""}
        descriptionDirty={descriptionDirty}
        disabled={disabled}
        pending={pending}
        onDescriptionChange={onDescriptionChange}
        onDescriptionSave={onDescriptionSave}
      />
      <section aria-labelledby="task-comments-heading" className="grid gap-2">
        <h2 id="task-comments-heading" className="font-semibold text-text-primary">
          Comments
        </h2>
        {comments}
      </section>
      <TaskPlanningSection
        task={task}
        clock={clock}
        disabled={disabled}
        pending={pending}
        onPlannedForChange={onPlannedForChange}
        onSnoozedUntilChange={onSnoozedUntilChange}
      />
      <TaskContextSection
        project={project}
        situation={situation}
        commitment={commitment}
        role={role}
        onOpen={onContextOpen}
      />
      <TaskAdministrativeSection
        archived={Boolean(task.archived_at)}
        disabled={disabled}
        pending={pending}
        onArchivedChange={onArchivedChange}
      />
      {technicalDetails}
    </div>
  );
}
