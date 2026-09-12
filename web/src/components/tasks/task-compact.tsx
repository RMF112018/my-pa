"use client";

/**
 * The compact Task unit (WP-TUX-03).
 *
 * This is a semantic composition contract, not one giant card: surfaces (list,
 * board, Work summary, search) render the same Task with the same hierarchy and
 * the same product language, and supply their own inline actions and overflow.
 *
 * Hierarchy, in order: title, due phrase, status label, actions, overflow,
 * priority. Priority is last because most Tasks have none, and a Task without a
 * priority has no priority — it is never silently rendered as `Low`.
 *
 * Boundaries: presentational. No fetch, no mutation, no idempotency or retry
 * logic. All product language arrives pre-resolved on `TaskPresentationModel`
 * from `@/lib/tasks/presentation`; this component never re-derives copy from a
 * backend token, and never renders a raw ID or lifecycle token as visible text.
 */

import type * as React from "react";
import { Badge } from "@/components/ui/badge";
import type { TaskDueTone, TaskPresentationModel } from "@/lib/tasks/presentation";

/**
 * Due tone drives emphasis only. The phrase itself is always rendered, so status
 * and urgency are never conveyed by colour alone.
 */
const DUE_TONE_CLASSES: Readonly<Record<TaskDueTone, string>> = {
  none: "text-text-secondary",
  today: "text-text-primary font-medium",
  tomorrow: "text-text-primary",
  overdue: "text-destructive font-medium",
  scheduled: "text-text-secondary",
};

export interface TaskCompactProps {
  model: TaskPresentationModel;
  /** Dense single-line-title variant for table/board contexts. */
  dense?: boolean;
  href?: string;
  onOpen?(event: React.MouseEvent<HTMLAnchorElement>): void;
  /** Inline primary actions (Status/Due/Close) supplied by the surface. */
  actions?: React.ReactNode;
  /** Overflow slot where Cancel and advanced navigation live. */
  overflow?: React.ReactNode;
}

export function TaskCompact({
  model,
  dense = false,
  href,
  onOpen,
  actions,
  overflow,
}: TaskCompactProps): React.JSX.Element {
  const clamp = dense ? "line-clamp-1" : "line-clamp-2";
  const titleClasses = `${clamp} text-sm font-medium text-text-primary ${
    model.terminal ? "text-text-secondary" : ""
  }`;

  const title = href ? (
    <a href={href} onClick={onOpen} className={`${titleClasses} hover:underline`}>
      {model.title}
    </a>
  ) : (
    <span className={titleClasses}>{model.title}</span>
  );

  return (
    <article
      data-testid="task-compact"
      data-task-id={model.taskId}
      data-task-version={model.version ?? undefined}
      data-dense={dense || undefined}
      className={`flex flex-col gap-1 rounded-[var(--radius-md)] border border-border bg-surface ${
        dense ? "px-3 py-2" : "p-3"
      }`}
    >
      {title}

      {model.contextLabel ? (
        <p className="truncate text-xs text-text-secondary">{model.contextLabel}</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className={DUE_TONE_CLASSES[model.due.tone]} data-task-due-tone={model.due.tone}>
          {model.due.phrase}
        </span>
        <span className="text-text-secondary" data-task-status-label="">
          {model.statusLabel}
        </span>
      </div>

      {actions || overflow ? (
        <div className="flex flex-wrap items-center gap-2">
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
          {overflow ? <div className="ms-auto flex items-center">{overflow}</div> : null}
        </div>
      ) : null}

      {model.hasPriority ? (
        <div className="flex items-center">
          <Badge tone={model.priority === "p1" ? "coral" : "neutral"}>{model.priorityLabel}</Badge>
        </div>
      ) : null}
    </article>
  );
}
