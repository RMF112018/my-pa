"use client";

/**
 * The Overview: the Project's Constraint position, as the backend reported it.
 *
 * **Every number on this page is rendered, not computed.** `totalOpen`,
 * `overdue`, `dueSoon`, `inMyCourt`, `onHold`, `needsAttention`, `draft`,
 * `recentlyChanged`, `recentlyClosed`, `averageOpenAgeBusinessDays` and the
 * per-Category open counts arrive as fields and are printed. None of them is
 * reconstructed by filtering Register rows, and the reason is not purity: a
 * Register page is bounded, so a tally over it would be an answer about the
 * rows that happened to load, presented as an answer about the Project
 * (`CM-FE-AC-010`).
 *
 * The same rule governs the Due Soon window. `dueSoonThrough` is displayed as
 * supplied; the seven-business-day rule that produced it is the backend's, and
 * adding days here would produce a second window that could disagree with the
 * one the count was computed against (`CM-FE-AC-012`).
 *
 * **The canonical names are used as names.** `averageOpenAgeBusinessDays` and
 * `syncHealth` are read directly off the projection. `averageOpenAge` and
 * `synchronizationHealth` appear nowhere in this feature, are not accepted as
 * fallbacks, and a payload carrying only those would fail to type-check rather
 * than quietly render (`CM-FE-AC-019`).
 *
 * **Two KPIs are deliberately not clickable.** Recently Changed and Recently
 * Closed have no Register filter at this head whose window is the same one the
 * metric was measured over. Making them navigate would mean inventing a date
 * range, which is exactly the thing the accepted specification forbids; they
 * are shown as figures and say why they do not navigate.
 */
import type {
  ConstraintCategoryOpenCount,
  ConstraintListEntry,
  ConstraintOverview,
} from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import type { ConstraintKpiTarget, ConstraintUrlState } from "./constraint-url-state";
import { codeLabel, dateLabel, isSyncException, partyLabel, syncLabel, urgencyLabels } from "./presentation";

function MetricButton({
  label,
  value,
  detail,
  target,
  onNavigate,
  testId,
}: {
  readonly label: string;
  readonly value: string;
  readonly detail?: string;
  readonly target: ConstraintKpiTarget;
  readonly onNavigate: (target: ConstraintKpiTarget) => void;
  readonly testId: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={() => onNavigate(target)}
      className="min-h-11 rounded-lg border border-border bg-surface p-3 text-left hover:bg-surface-subtle"
    >
      <span className="block text-2xl font-semibold text-moss-slate">{value}</span>
      <span className="block text-sm font-medium text-moss-slate">{label}</span>
      {detail ? <span className="mt-1 block text-xs text-muted">{detail}</span> : null}
      <span className="mt-1 block text-xs text-muted">Open in the Register</span>
    </button>
  );
}

function MetricFigure({
  label,
  value,
  detail,
  testId,
}: {
  readonly label: string;
  readonly value: string;
  readonly detail?: string;
  readonly testId: string;
}) {
  return (
    <div data-testid={testId} className="rounded-lg border border-border bg-surface p-3">
      <span className="block text-2xl font-semibold text-moss-slate">{value}</span>
      <span className="block text-sm font-medium text-moss-slate">{label}</span>
      {detail ? <span className="mt-1 block text-xs text-muted">{detail}</span> : null}
    </div>
  );
}

export interface ConstraintsOverviewProps {
  readonly overview: ConstraintOverview;
  readonly categoryOpenCounts: readonly ConstraintCategoryOpenCount[];
  readonly oldestOpen: readonly ConstraintListEntry[];
  readonly state: ConstraintUrlState;
  readonly onKpiNavigate: (target: ConstraintKpiTarget) => void;
  readonly onCategoryNavigate: (categoryId: string) => void;
  readonly onSelect: (constraintId: string) => void;
}

export function ConstraintsOverview({
  overview,
  categoryOpenCounts,
  oldestOpen,
  onKpiNavigate,
  onCategoryNavigate,
  onSelect,
}: ConstraintsOverviewProps) {
  const widest = categoryOpenCounts.reduce((max, row) => Math.max(max, row.openCount), 0);
  return (
    <section aria-label="Constraint Overview" className="grid gap-4">
      <p className="text-sm text-muted" data-testid="overview-as-of">
        Backend figures as at {overview.asOf}. Project date {overview.projectToday} (
        {overview.projectTimezone}).
      </p>

      <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="Primary metrics">
        <MetricButton
          testId="kpi-overdue"
          label="Overdue"
          value={String(overview.overdue)}
          target="overdue"
          onNavigate={onKpiNavigate}
        />
        <MetricButton
          testId="kpi-dueSoon"
          label="Due Soon"
          value={String(overview.dueSoon)}
          detail={`Through ${overview.dueSoonThrough}, on the Project's own calendar.`}
          target="dueSoon"
          onNavigate={onKpiNavigate}
        />
        <MetricButton
          testId="kpi-inMyCourt"
          label="In My Court"
          value={String(overview.inMyCourt)}
          target="inMyCourt"
          onNavigate={onKpiNavigate}
        />
      </div>

      <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="Secondary metrics">
        <MetricButton
          testId="kpi-needsAttention"
          label="Needs Attention"
          value={String(overview.needsAttention)}
          target="needsAttention"
          onNavigate={onKpiNavigate}
        />
        <MetricButton
          testId="kpi-totalOpen"
          label="Total Open"
          value={String(overview.totalOpen)}
          target="totalOpen"
          onNavigate={onKpiNavigate}
        />
        <MetricButton
          testId="kpi-onHold"
          label="On Hold"
          value={String(overview.onHold)}
          target="onHold"
          onNavigate={onKpiNavigate}
        />
      </div>

      <div className="grid gap-2 sm:grid-cols-4" role="group" aria-label="Supporting figures">
        <MetricFigure
          testId="kpi-averageOpenAgeBusinessDays"
          label="Average Open Age"
          value={
            overview.averageOpenAgeBusinessDays === null
              ? "—"
              : String(overview.averageOpenAgeBusinessDays)
          }
          detail={
            overview.averageOpenAgeBusinessDays === null
              ? "No open Constraints qualify, so there is no average."
              : "business days, measured by the backend"
          }
        />
        <MetricFigure
          testId="kpi-recentlyChanged"
          label="Recently Changed"
          value={String(overview.recentlyChanged)}
          detail="No Register filter shares this window yet, so this figure does not navigate."
        />
        <MetricFigure
          testId="kpi-recentlyClosed"
          label="Recently Closed"
          value={String(overview.recentlyClosed)}
          detail="No Register filter shares this window yet, so this figure does not navigate."
        />
        <MetricButton
          testId="kpi-draft"
          label="Draft"
          value={String(overview.draft)}
          detail="Persisted canonical Drafts, not unsaved forms."
          target="draft"
          onNavigate={onKpiNavigate}
        />
      </div>

      <Card data-testid="overview-sync-health">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Workbook synchronisation</CardTitle>
          <Badge tone={isSyncException(overview.syncHealth.state) ? "coral" : "neutral"}>
            {syncLabel(overview.syncHealth.state)}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-muted">
          {overview.syncHealth.openConflictCount} open conflict
          {overview.syncHealth.openConflictCount === 1 ? "" : "s"}. Last verified{" "}
          {overview.syncHealth.lastVerifiedAt ?? "never"}.
        </p>
        <p className="mt-1 text-sm text-muted">
          Synchronisation is subordinate to the canonical record. A pending Excel update does not
          mean a save failed.
        </p>
      </Card>

      <Card data-testid="overview-by-category">
        <CardTitle>Open Constraints by Category</CardTitle>
        <ul className="mt-2 grid gap-1">
          {categoryOpenCounts.map((row) => (
            <li key={row.categoryId}>
              <button
                type="button"
                data-testid={`overview-category-${row.categoryId}`}
                onClick={() => onCategoryNavigate(row.categoryId)}
                className="flex min-h-11 w-full items-center gap-2 rounded px-1 text-left text-sm hover:bg-surface-subtle"
              >
                <span className="w-56 shrink-0 truncate">{row.title}</span>
                <span
                  aria-hidden="true"
                  className="h-2 rounded bg-moss-green/40"
                  style={{ width: `${widest === 0 ? 0 : (row.openCount / widest) * 100}%` }}
                />
                <span className="ml-auto tabular-nums">{row.openCount} open</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <Card data-testid="overview-oldest-open">
        <CardTitle>Oldest open Constraints</CardTitle>
        <ul className="mt-2 grid gap-2 text-sm">
          {oldestOpen.map((entry) => (
            <li key={entry.constraintId} className="flex flex-wrap items-baseline gap-2">
              <button
                type="button"
                data-testid={`overview-oldest-${entry.constraintId}`}
                onClick={() => onSelect(entry.constraintId)}
                className="min-h-11 rounded font-medium text-moss-green underline"
              >
                {codeLabel(entry.constraintCode)}
              </button>
              <span className="min-w-0 flex-1 truncate">{entry.description ?? "Not recorded"}</span>
              <span className="text-muted">
                {entry.daysElapsed === null ? "days open not recorded" : `${entry.daysElapsed} days open`}
              </span>
              <span className="text-muted">BIC {partyLabel(entry.bic)}</span>
              <span className="text-muted">Due {dateLabel(entry.dueDate)}</span>
              {urgencyLabels(entry).map((label) => (
                <Badge key={label} tone={label === "Overdue" ? "coral" : "gold"}>
                  {label}
                </Badge>
              ))}
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
