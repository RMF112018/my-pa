"use client";

import { useId, type ReactNode } from "react";

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
  TASK_PLANNED_FOR_LABEL,
  TASK_SNOOZED_UNTIL_LABEL,
  TASK_PRIORITY_LABELS,
  type TaskCivilClock,
  type TaskPresentationModel,
} from "@/lib/tasks/presentation";

/**
 * Progressive Task detail sections (WP-TUX-03).
 *
 * Summary and Description & Activity are primary and always expanded. Planning,
 * Context and Administrative are progressive disclosures, collapsed by default so
 * narrow mobile never opens onto a wall of fields. Technical diagnostics are a
 * separate single disclosure supplied by the caller.
 *
 * Every edit here is a bounded, field- or section-level mutation intent. There is no
 * whole-Task atomic patch form and no generic lifecycle transition form.
 */

const PRIORITY_TOKENS: readonly TaskPriority[] = ["p1", "p2", "p3", "p4"];

function Section({
  title,
  children,
  id,
}: {
  title: string;
  children: ReactNode;
  id?: string;
}) {
  const generated = useId();
  const headingId = id ?? generated;
  return (
    <section
      aria-labelledby={headingId}
      className="mt-6 rounded-[var(--radius-lg)] border border-border-subtle bg-surface p-4"
    >
      <h2 id={headingId} className="font-semibold text-text-primary">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Collapsed-by-default progressive section. */
function ProgressiveSection({
  title,
  children,
  testId,
}: {
  title: string;
  children: ReactNode;
  testId: string;
}) {
  return (
    <details
      data-testid={testId}
      className="mt-4 rounded-[var(--radius-lg)] border border-border-subtle bg-surface"
    >
      <summary className="flex min-h-11 cursor-pointer items-center px-4 font-semibold text-text-primary">
        {title}
      </summary>
      <div className="border-t border-border-subtle p-4">{children}</div>
    </details>
  );
}

export interface TaskSummarySectionProps {
  model: TaskPresentationModel;
  title: string;
  /** True while the title draft diverges from the authoritative snapshot. */
  titleDirty: boolean;
  priority: TaskPriority | null;
  disabled: boolean;
  pending: boolean;
  statusControl: ReactNode;
  dueControl: ReactNode;
  closeControl: ReactNode;
  onTitleChange(next: string): void;
  onTitleSave(): void;
  onPriorityChange(next: TaskPriority | null): void;
}

export function TaskSummarySection({
  model,
  title,
  titleDirty,
  priority,
  disabled,
  pending,
  statusControl,
  dueControl,
  closeControl,
  onTitleChange,
  onTitleSave,
  onPriorityChange,
}: TaskSummarySectionProps) {
  const priorityId = useId();

  return (
    <Section title="Summary" id="task-summary-heading">
      <div className="mt-3 grid gap-4" data-testid="task-summary">
        <div className="grid gap-2">
          <label htmlFor={`${priorityId}-title`} className="text-sm font-medium text-text-primary">
            Title
          </label>
          <Input
            id={`${priorityId}-title`}
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            disabled={pending}
            className="min-h-11"
          />
          {titleDirty ? (
            <div>
              <Button
                size="sm"
                pending={pending}
                disabled={disabled || title.trim().length === 0}
                onClick={onTitleSave}
              >
                Save title
              </Button>
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-end gap-4">
          {statusControl}
          {dueControl}
          <div className="grid gap-1">
            <label htmlFor={priorityId} className="text-sm font-medium text-text-primary">
              Priority
            </label>
            <Select
              id={priorityId}
              className="min-h-11"
              value={priority ?? ""}
              disabled={disabled || pending}
              onChange={(event) =>
                onPriorityChange(event.target.value === "" ? null : (event.target.value as TaskPriority))
              }
            >
              <option value="">{formatTaskPriority(null)}</option>
              {PRIORITY_TOKENS.map((token) => (
                <option key={token} value={token}>
                  {TASK_PRIORITY_LABELS[token]}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {model.terminalSummary ? (
          <p className="text-sm text-muted" data-testid="task-terminal-summary">
            {model.terminalSummary}
          </p>
        ) : (
          closeControl
        )}
      </div>
    </Section>
  );
}

export interface TaskActivitySectionProps {
  description: string;
  /** True while the description draft diverges from the authoritative snapshot. */
  descriptionDirty: boolean;
  disabled: boolean;
  pending: boolean;
  comments: ReactNode;
  onDescriptionChange(next: string): void;
  onDescriptionSave(): void;
}

export function TaskActivitySection({
  description,
  descriptionDirty,
  disabled,
  pending,
  comments,
  onDescriptionChange,
  onDescriptionSave,
}: TaskActivitySectionProps) {
  const fieldId = useId();

  return (
    <Section title="Description & Activity" id="task-activity-heading">
      <div className="mt-3 grid gap-2">
        <label htmlFor={fieldId} className="text-sm font-medium text-text-primary">
          Description
        </label>
        <Textarea
          id={fieldId}
          value={description}
          onChange={(event) => onDescriptionChange(event.target.value)}
          disabled={pending}
        />
        {descriptionDirty ? (
          <div>
            <Button size="sm" pending={pending} disabled={disabled} onClick={onDescriptionSave}>
              Save description
            </Button>
          </div>
        ) : null}
      </div>
      <div className="mt-5 border-t border-border-subtle pt-4">{comments}</div>
    </Section>
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
  return (
    <ProgressiveSection title="Planning" testId="task-planning-section">
      <div className="grid gap-4">
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
      </div>
    </ProgressiveSection>
  );
}

/** One Context entry: a human label when available, a stated absence otherwise. Never a raw ID. */
function ContextEntry({ term, label }: { term: string; label: string | null }) {
  return (
    <div>
      <dt className="text-muted">{term}</dt>
      <dd>{label ?? `${term} details unavailable`}</dd>
    </div>
  );
}

export interface TaskContextSectionProps {
  projectLabel: string | null;
  situationLabel: string | null;
  commitmentLabel: string | null;
  roleLabel: string | null;
}

export function TaskContextSection({
  projectLabel,
  situationLabel,
  commitmentLabel,
  roleLabel,
}: TaskContextSectionProps) {
  return (
    <ProgressiveSection title="Context" testId="task-context-section">
      <dl className="grid gap-3 text-sm">
        <ContextEntry term="Project" label={projectLabel} />
        <ContextEntry term="Situation" label={situationLabel} />
        <ContextEntry term="Commitment" label={commitmentLabel} />
        <ContextEntry term="Role" label={roleLabel} />
      </dl>
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
    <ProgressiveSection title="Administrative" testId="task-administrative-section">
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

export interface TaskDetailSectionsProps
  extends Omit<TaskSummarySectionProps, "model">,
    Pick<TaskPlanningSectionProps, "task" | "clock" | "onPlannedForChange" | "onSnoozedUntilChange">,
    TaskContextSectionProps {
  model: TaskPresentationModel;
  description: string;
  descriptionDirty: boolean;
  comments: ReactNode;
  technicalDetails: ReactNode;
  onDescriptionChange(next: string): void;
  onDescriptionSave(): void;
  onArchivedChange(next: boolean): void;
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
    description,
    descriptionDirty,
    comments,
    technicalDetails,
    projectLabel,
    situationLabel,
    commitmentLabel,
    roleLabel,
    onTitleChange,
    onTitleSave,
    onPriorityChange,
    onDescriptionChange,
    onDescriptionSave,
    onPlannedForChange,
    onSnoozedUntilChange,
    onArchivedChange,
  } = props;

  return (
    <div data-testid="task-detail-sections">
      <TaskSummarySection
        model={model}
        title={title}
        titleDirty={titleDirty}
        priority={priority}
        disabled={disabled}
        pending={pending}
        statusControl={statusControl}
        dueControl={dueControl}
        closeControl={closeControl}
        onTitleChange={onTitleChange}
        onTitleSave={onTitleSave}
        onPriorityChange={onPriorityChange}
      />
      <TaskActivitySection
        description={description}
        descriptionDirty={descriptionDirty}
        disabled={disabled}
        pending={pending}
        comments={comments}
        onDescriptionChange={onDescriptionChange}
        onDescriptionSave={onDescriptionSave}
      />
      <TaskPlanningSection
        task={task}
        clock={clock}
        disabled={disabled}
        pending={pending}
        onPlannedForChange={onPlannedForChange}
        onSnoozedUntilChange={onSnoozedUntilChange}
      />
      <TaskContextSection
        projectLabel={projectLabel}
        situationLabel={situationLabel}
        commitmentLabel={commitmentLabel}
        roleLabel={roleLabel}
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
