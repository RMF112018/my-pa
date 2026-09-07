"use client";

/**
 * The Register's rows, in the three presentations the accepted package asks for.
 *
 * **A real `<table>`, and not an ARIA grid.** There is no table primitive in
 * `components/ui/`, and this work package does not create one: the accepted
 * plan says build it inside the feature rather than inventing a shared layer
 * nobody else has asked for yet. What matters is that it is semantic HTML —
 * `<table>`, `<thead>`, `<th scope="col">`, `<th scope="row">`, `<caption>` —
 * so a screen reader gets row and column association from the platform. A
 * custom ARIA spreadsheet would owe the reader full grid keyboard semantics,
 * which v1 does not require and which a half-implementation of makes *worse*
 * than a table (`CM-FE-AC-134`, `CM-FE-AC-038`, `04` §18).
 *
 * **Sorting is announced on the header, not implied by an arrow.** Each
 * sortable header carries `aria-sort` and its button names the column, so the
 * current order is available without seeing the glyph.
 *
 * **Column reduction, not horizontal scrolling, is the responsive strategy.**
 * Tablet keeps Code, Description, Status, BIC and Due — the five
 * `CM-FE-AC-131` names — and moves the rest into the row's secondary line.
 * Mobile leaves the table entirely for a list of cards, because a dense
 * spreadsheet reproduced at 390px is not a mobile experience of it
 * (`CM-FE-AC-133`).
 *
 * **Nothing in this file computes a state.** Urgency words come from
 * `isOverdue`/`isDueSoon`; the status word comes from `status`; the attention
 * marker comes from `needsAttention`. There is no date arithmetic here.
 */
import type { ConstraintListEntry } from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import type { ConstraintUrlState } from "./constraint-url-state";
import type { ConstraintViewport } from "./use-viewport";
import {
  codeLabel,
  dateLabel,
  isSyncException,
  lifecycleLabel,
  lifecycleTone,
  partyLabel,
  syncLabel,
  urgencyLabels,
} from "./presentation";

/** The identity a focus restoration targets after the Inspector closes. */
export function rowTriggerId(constraintId: string): string {
  return `constraint-row-trigger-${constraintId}`;
}

export interface RegisterTableProps {
  readonly entries: readonly ConstraintListEntry[];
  readonly state: ConstraintUrlState;
  readonly viewport: ConstraintViewport;
  readonly caption: string;
  readonly onSelect: (constraintId: string) => void;
  readonly onSort: (sort: ConstraintUrlState["sort"]) => void;
}

interface Column {
  readonly key: string;
  readonly label: string;
  readonly sort?: ConstraintUrlState["sort"];
  /** Present on tablet as well as desktop. `CM-FE-AC-131` fixes these five. */
  readonly tablet: boolean;
  readonly numeric?: boolean;
}

const COLUMNS: readonly Column[] = [
  { key: "code", label: "Code", sort: "code", tablet: true },
  { key: "description", label: "Description", tablet: true },
  { key: "status", label: "Status", tablet: true },
  { key: "daysOpen", label: "Days Open", sort: "daysOpen", tablet: false, numeric: true },
  { key: "bic", label: "Ball in Court", tablet: true },
  { key: "due", label: "Due", sort: "due", tablet: true },
  { key: "responsible", label: "Responsible party", tablet: false },
  { key: "reference", label: "Reference", tablet: false },
  { key: "category", label: "Category", tablet: false },
];

/**
 * The columns this state shows.
 *
 * Category is dropped when the Register is already grouped by Category, because
 * repeating the group's own identity in every one of its rows spends the widest
 * column on the one fact the reader already has (`CM-FE-AC-027`).
 */
export function visibleColumns(
  state: ConstraintUrlState,
  viewport: ConstraintViewport,
): readonly Column[] {
  return COLUMNS.filter((column) => {
    if (column.key === "category" && state.group === "category") return false;
    if (viewport === "tablet") return column.tablet;
    return true;
  });
}

function ariaSortFor(column: Column, state: ConstraintUrlState): "ascending" | "descending" | "none" {
  if (column.sort === undefined) return "none";
  if (state.sort !== column.sort) return "none";
  return state.dir === "asc" ? "ascending" : "descending";
}

/** Overdue / Due soon / Needs attention / sync, always as words. */
function StateChips({ entry }: { entry: ConstraintListEntry }) {
  const urgency = urgencyLabels(entry);
  return (
    <>
      {urgency.map((label) => (
        <Badge key={label} tone={label === "Overdue" ? "coral" : "gold"}>
          {label}
        </Badge>
      ))}
      {entry.needsAttention ? <Badge tone="gold">Needs attention</Badge> : null}
      {isSyncException(entry.syncState) ? (
        <Badge tone="coral">{syncLabel(entry.syncState)}</Badge>
      ) : null}
      {entry.recordQuality === "LEGACY_INCOMPLETE" ? <Badge tone="gold">Legacy</Badge> : null}
    </>
  );
}

function cellContent(entry: ConstraintListEntry, key: string) {
  switch (key) {
    case "description":
      return entry.description ?? "Not recorded";
    case "status":
      return (
        <Badge tone={lifecycleTone(entry.status)}>{lifecycleLabel(entry.status)}</Badge>
      );
    case "daysOpen":
      return entry.daysElapsed === null ? "Not recorded" : String(entry.daysElapsed);
    case "bic":
      return partyLabel(entry.bic);
    case "due":
      return (
        <span className="flex flex-wrap items-center gap-1">
          <span>{dateLabel(entry.dueDate)}</span>
          <StateChips entry={entry} />
        </span>
      );
    case "responsible":
      return partyLabel(entry.responsible);
    case "reference":
      // Reference is ordinary project-control text. It is rendered as text and
      // is never auto-linked, whatever it happens to look like
      // (`CM-FE-AC-095`).
      return entry.reference ?? "Not recorded";
    case "category":
      return entry.category === null ? "Not recorded" : entry.category.title;
    default:
      return null;
  }
}

export function RegisterTable({
  entries,
  state,
  viewport,
  caption,
  onSelect,
  onSort,
}: RegisterTableProps) {
  const columns = visibleColumns(state, viewport);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" data-testid="register-table">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-surface">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                aria-sort={ariaSortFor(column, state)}
                className="border-b border-border px-2 py-2 font-medium text-moss-slate"
              >
                {column.sort === undefined ? (
                  column.label
                ) : (
                  <button
                    type="button"
                    onClick={() => onSort(column.sort as ConstraintUrlState["sort"])}
                    className="inline-flex min-h-11 items-center gap-1 rounded font-medium"
                    data-testid={`register-sort-${column.key}`}
                  >
                    {column.label}
                    <span aria-hidden="true">
                      {state.sort === column.sort ? (state.dir === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  </button>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.constraintId}
              data-testid={`register-row-${entry.constraintId}`}
              data-selected={state.selectedConstraintId === entry.constraintId || undefined}
              className="border-b border-border-subtle data-[selected]:bg-surface-subtle"
            >
              {columns.map((column) =>
                column.key === "code" ? (
                  <th key={column.key} scope="row" className="px-2 py-2 font-normal align-top">
                    <button
                      type="button"
                      id={rowTriggerId(entry.constraintId)}
                      onClick={() => onSelect(entry.constraintId)}
                      className="inline-flex min-h-11 items-center rounded text-left font-medium text-moss-green underline"
                    >
                      {codeLabel(entry.constraintCode)}
                    </button>
                    {viewport === "tablet" ? (
                      <span className="mt-1 block text-xs text-muted">
                        {entry.daysElapsed === null
                          ? "Days open not recorded"
                          : `${entry.daysElapsed} days open`}
                        {entry.reference === null ? "" : ` · ${entry.reference}`}
                      </span>
                    ) : null}
                  </th>
                ) : (
                  <td key={column.key} className="px-2 py-2 align-top">
                    {cellContent(entry, column.key)}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Mobile: a list of cards, with the fields `04` §20 names and no others.
 *
 * A definition list per card, so each label/value pair is associated for a
 * screen reader without a table's column semantics that a 390px screen cannot
 * honestly deliver.
 */
export function RegisterCardList({
  entries,
  state,
  onSelect,
}: {
  readonly entries: readonly ConstraintListEntry[];
  readonly state: ConstraintUrlState;
  readonly onSelect: (constraintId: string) => void;
}) {
  return (
    <ul className="grid gap-2" data-testid="register-card-list">
      {entries.map((entry) => (
        <li
          key={entry.constraintId}
          data-testid={`register-card-${entry.constraintId}`}
          data-selected={state.selectedConstraintId === entry.constraintId || undefined}
          className="rounded-lg border border-border bg-surface p-3 data-[selected]:border-moss-green"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              id={rowTriggerId(entry.constraintId)}
              onClick={() => onSelect(entry.constraintId)}
              className="min-h-11 rounded text-left font-medium text-moss-green underline"
            >
              {codeLabel(entry.constraintCode)}
            </button>
            <Badge tone={lifecycleTone(entry.status)}>{lifecycleLabel(entry.status)}</Badge>
          </div>
          <p className="mt-1 text-sm text-moss-slate">{entry.description ?? "Not recorded"}</p>
          <dl className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted">
            <dt>Ball in Court</dt>
            <dd>{partyLabel(entry.bic)}</dd>
            <dt>Due</dt>
            <dd>{dateLabel(entry.dueDate)}</dd>
          </dl>
          <div className="mt-2 flex flex-wrap gap-1">
            <StateChips entry={entry} />
          </div>
        </li>
      ))}
    </ul>
  );
}
