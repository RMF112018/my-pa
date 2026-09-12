"use client";

/**
 * The single Task diagnostic disclosure (WP-TUX-03).
 *
 * One collapsed `<details>` at the bottom of Task detail, not several scattered
 * "Details" blocks. Everything that is legible only to an operator — raw IDs,
 * versions, evidence references, history action codes, disclosure metadata —
 * lives here and nowhere else in the Task surface.
 *
 * It is lazy on purpose: the diagnostic body is not rendered while collapsed and
 * `onExpand` fires exactly once, on first expansion, so opening a Task never
 * eagerly loads technical history.
 *
 * Boundaries: presentational. No fetch, no network import, no mutation. Evidence
 * is never auto-loaded; `onRevealEvidence` hands the existing explicit,
 * server-governed reveal path back to the caller. Only Task metadata passed in
 * on `task`, `history` and `historyDisclosure` is rendered — never session
 * tokens, cookies or credentials.
 */

import type * as React from "react";
import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { TaskDetail, WorkHistoryRow } from "@/contracts/work";
import { formatTaskPlanningDate, type TaskCivilClock } from "@/lib/tasks/presentation";

const ABSENT = "—";
const LOADING_COPY = "Loading technical history…";
const EMPTY_COPY = "No history rows were returned.";

export interface TaskTechnicalDetailsProps {
  task: TaskDetail;
  clock: TaskCivilClock;
  history: readonly WorkHistoryRow[];
  historyDisclosure?: DisclosureEnvelope;
  /** True once the caller has loaded history. */
  historyLoaded?: boolean;
  historyLoading?: boolean;
  /** Called the first time the disclosure is expanded, so the caller can lazily read history. */
  onExpand?(): void;
  onContinueHistory?(): void;
  /** Opens the existing explicit, server-governed evidence reveal path. */
  onRevealEvidence?(ref: string): void;
}

/** Copies one value, guarded so an absent Clipboard API cannot throw. */
function CopyValueButton({ label, value }: { label: string; value: string }): React.JSX.Element {
  const copy = useCallback(() => {
    try {
      void navigator?.clipboard?.writeText?.(value)?.catch?.(() => undefined);
    } catch {
      /* Clipboard unavailable or denied: copying is a convenience, never a gate. */
    }
  }, [value]);
  return (
    <Button variant="ghost" size="sm" aria-label={label} onClick={copy}>
      Copy
    </Button>
  );
}

function Row({
  label,
  value,
  copyLabel,
  children,
}: {
  label: string;
  value: string | null;
  copyLabel?: string;
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2 py-1 text-xs">
      <span className="min-w-40 text-text-secondary">{label}</span>
      <span className="break-all font-mono text-text-primary">{value ?? ABSENT}</span>
      {value && copyLabel ? <CopyValueButton label={copyLabel} value={value} /> : null}
      {children}
    </div>
  );
}

function Group({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <section aria-label={heading} className="border-t border-border pt-3">
      <h3 className="pb-1 text-xs font-semibold text-text-primary">{heading}</h3>
      {children}
    </section>
  );
}

export function TaskTechnicalDetails({
  task,
  clock,
  history,
  historyDisclosure,
  historyLoaded = false,
  historyLoading = false,
  onExpand,
  onContinueHistory,
  onRevealEvidence,
}: TaskTechnicalDetailsProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const announced = useRef(false);

  /**
   * The disclosure is controlled rather than left to native `<details>` toggling so
   * that "expanded" and "body rendered" can never disagree — laziness is the point.
   */
  const handleSummaryClick = useCallback(
    (event: React.MouseEvent<HTMLElement>) => {
      event.preventDefault();
      setOpen((wasOpen) => {
        const nowOpen = !wasOpen;
        if (nowOpen && !announced.current) {
          announced.current = true;
          onExpand?.();
        }
        return nowOpen;
      });
    },
    [onExpand],
  );

  const planning = (value: string | null | undefined) =>
    formatTaskPlanningDate(value, clock, ABSENT);

  const originEvidenceRef = task.origin_evidence_ref;
  const closureEvidenceRef = task.closure_evidence_ref;

  return (
    <details
      data-testid="task-technical-details"
      className="rounded-[var(--radius-md)] border border-border bg-surface p-3"
      open={open}
    >
      <summary
        className="cursor-pointer text-sm font-medium text-text-primary"
        onClick={handleSummaryClick}
      >
        Technical details
      </summary>

      {open ? (
        <div className="mt-3 flex flex-col gap-3">
          <Group heading="Identity">
            <Row label="Task ID" value={task.task_id} copyLabel="Copy Task ID" />
            <Row label="Task version" value={String(task.version)} />
          </Group>

          <Group heading="Timestamps">
            <Row label="Created" value={planning(task.created_at)} />
            <Row label="Updated" value={planning(task.updated_at)} />
            <Row label="Opened" value={planning(task.opened_at)} />
            <Row label="Closed" value={planning(task.closed_at)} />
            <Row label="Archived" value={planning(task.archived_at)} />
          </Group>

          <Group heading="Provenance">
            <Row label="Origin kind" value={task.origin_kind} />
            <Row label="Evidence state" value={task.evidence_state} />
            <Row
              label="Origin evidence ref"
              value={originEvidenceRef}
              copyLabel="Copy origin evidence reference"
            >
              {originEvidenceRef && onRevealEvidence ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onRevealEvidence(originEvidenceRef)}
                >
                  View origin evidence
                </Button>
              ) : null}
            </Row>
            <Row
              label="Closure evidence ref"
              value={closureEvidenceRef}
              copyLabel="Copy closure evidence reference"
            >
              {closureEvidenceRef && onRevealEvidence ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onRevealEvidence(closureEvidenceRef)}
                >
                  View closure evidence
                </Button>
              ) : null}
            </Row>
            <Row
              label="Review decision id"
              value={task.accepted_by_review_decision_id}
              copyLabel="Copy review decision id"
            />
            <Row label="Acceptance kind" value={task.acceptance_kind} />
            <Row
              label="Closure history id"
              value={task.closure_history_id}
              copyLabel="Copy closure history id"
            />
          </Group>

          <Group heading="Relationships">
            <Row label="project_id" value={task.project_id} copyLabel="Copy project_id" />
            <Row label="situation_id" value={task.situation_id} copyLabel="Copy situation_id" />
          </Group>

          <Group heading="History">
            {historyLoading ? (
              <p className="text-xs text-text-secondary">{LOADING_COPY}</p>
            ) : history.length === 0 ? (
              <p className="text-xs text-text-secondary">{historyLoaded ? EMPTY_COPY : LOADING_COPY}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {history.map((row) => (
                  <li key={row.history_id} className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono text-text-primary">{row.action}</span>
                    <span className="text-text-secondary">{row.outcome}</span>
                    <span className="font-mono text-text-secondary">
                      {`v${row.before_version}→v${row.after_version}`}
                    </span>
                    <span className="text-text-secondary">{row.recorded_at}</span>
                    <span className="break-all font-mono text-text-secondary">{row.history_id}</span>
                    {task.closure_history_id === row.history_id ? (
                      <span className="text-text-primary">Closure receipt</span>
                    ) : null}
                    <CopyValueButton
                      label={`Copy history id ${row.history_id}`}
                      value={row.history_id}
                    />
                  </li>
                ))}
              </ul>
            )}
            {historyDisclosure?.nextCursor && onContinueHistory ? (
              <div className="pt-2">
                <Button variant="secondary" size="sm" onClick={onContinueHistory}>
                  Continue history
                </Button>
              </div>
            ) : null}
          </Group>

          {historyDisclosure ? (
            <Group heading="Disclosure">
              <Row label="Authority" value={historyDisclosure.authority} />
              <Row label="Coverage" value={historyDisclosure.coverage} />
              <Row label="Freshness" value={historyDisclosure.freshnessAt} />
              <Row label="Truncated" value={historyDisclosure.truncated ? "Yes" : "No"} />
              {historyDisclosure.limitations.length > 0 ? (
                <ul className="list-disc ps-5 text-xs text-text-secondary">
                  {historyDisclosure.limitations.map((limitation) => (
                    <li key={limitation}>{limitation}</li>
                  ))}
                </ul>
              ) : null}
            </Group>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
