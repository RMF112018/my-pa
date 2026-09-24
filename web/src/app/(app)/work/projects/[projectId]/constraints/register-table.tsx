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
 *
 * **Inline edit is bounded, and it is the eligible four fields only
 * (`PC-CM-FE-AC-050`/`051`/`052`).** Status, Due Date, Ball in Court and
 * Current Update — nothing else — can be changed from the Register, each
 * through its own small, independently-committing control; there is no
 * full-row edit mode, and Code, Project, Category are never inline-editable.
 * A terminal row (`CLOSED`/`VOID`) offers none of the four: a terminal record
 * changes only through `constraint-direct-actions.tsx`'s guarded Reopen.
 *
 * **Optimistic, with a real rollback (`PC-CM-FE-AC-054`).** The edited value
 * is shown the instant a commit is sent; if the write does not confirm, the
 * cell reverts to the value it held before the edit and shows why. A row only
 * *leaves* the `open` scope once a decoded success actually said so
 * (`PC-CM-FE-AC-067`) — this file never removes a row from view on an
 * optimistic guess.
 *
 * **A caller, never this file, performs the write.** `onInlineEdit` is the one
 * seam: it is handed the field and the new value and returns whether the
 * write confirmed and, on success, the freshly re-read row
 * (`constraint-live.ts`'s `detailToListEntry`) to replace the optimistic one
 * with — so what ends up on screen is always backend-derived, never a locally
 * recomputed guess (`PC-CM-FE-AC-059`).
 */
import { useState } from "react";
import type { ConstraintListEntry, ConstraintPartyRef } from "@/contracts/constraints";
import { TERMINAL_CONSTRAINT_LIFECYCLES, type ConstraintLifecycle } from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ConstraintUrlState } from "./constraint-url-state";
import type { ConstraintViewport } from "./use-viewport";
import { ConstraintPartySelector, type RequestPartyRef } from "./constraint-party-selector";
import { multilineCommitHandler } from "./constraint-lifecycle";
import { readDetail } from "./constraint-live";
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

/** The exact four fields the Register may edit inline. Nothing else. */
export type InlineEditableField = "status" | "due" | "bic" | "currentUpdate";

/** `status`/`due`/`currentUpdate` carry a `string`; `bic` carries the wire party array. */
export type InlineEditValue = string | readonly RequestPartyRef[];

export interface InlineEditRequest {
  readonly constraintId: string;
  readonly field: InlineEditableField;
  readonly value: InlineEditValue;
  readonly expectedVersion: number;
}

export interface InlineEditResult {
  readonly ok: boolean;
  /** On success: the freshly re-read row. Absent means the caller will refresh separately. */
  readonly entry?: ConstraintListEntry;
  /** On failure: a safe, already-governed message. */
  readonly message?: string;
}

export type OnInlineEdit = (request: InlineEditRequest) => Promise<InlineEditResult>;

const ACTIVE_STATES: readonly ConstraintLifecycle[] = ["IDENTIFIED", "PENDING", "IN_PROGRESS", "ON_HOLD"];

function toRequestParties(parties: readonly ConstraintPartyRef[]): readonly RequestPartyRef[] {
  return parties.map((party) => {
    if (party.kind === "PRINCIPAL") return { kind: "principal" as const };
    if (party.kind === "ENTITY") {
      return { kind: "entity" as const, entityId: party.entityId ?? party.partyRefId ?? undefined, label: party.displayLabel };
    }
    return { kind: "unresolved" as const, label: party.displayLabel };
  });
}

export interface RegisterTableProps {
  readonly entries: readonly ConstraintListEntry[];
  readonly state: ConstraintUrlState;
  readonly viewport: ConstraintViewport;
  readonly caption: string;
  readonly onSelect: (constraintId: string) => void;
  readonly onSort: (sort: ConstraintUrlState["sort"]) => void;
  readonly onTriggerMount?: (constraintId: string, node: HTMLButtonElement | null) => void;
  /** Present only for the live workspace; absent (the synthetic fixture path) renders read-only exactly as before. */
  readonly onInlineEdit?: OnInlineEdit;
  /**
   * The cross-Project portfolio Register's own column, added by the
   * corrective: each row visibly carries the owning Project's name (plan
   * §6.2, "each row/card visibly carries Project name"). Absent (the default)
   * for the exact-Project Register, which already carries Project identity
   * from its route and does not repeat it per row.
   */
  readonly showProjectColumn?: boolean;
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

/** Portfolio scope only (`showProjectColumn`) — plan §6.2's "visibly carries Project name". */
const PROJECT_COLUMN: Column = { key: "project", label: "Project", tablet: true };

/**
 * The columns this state shows.
 *
 * Category is dropped when the Register is already grouped by Category, because
 * repeating the group's own identity in every one of its rows spends the widest
 * column on the one fact the reader already has (`CM-FE-AC-027`). The Project
 * column is inserted right after Code — the identity a portfolio reader needs
 * first — only when the caller asks for it; the exact-Project Register never
 * sees it (`showProjectColumn` defaults to `false`).
 */
export function visibleColumns(
  state: ConstraintUrlState,
  viewport: ConstraintViewport,
  showProjectColumn = false,
): readonly Column[] {
  const source = showProjectColumn ? [COLUMNS[0]!, PROJECT_COLUMN, ...COLUMNS.slice(1)] : COLUMNS;
  return source.filter((column) => {
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

function readOnlyCellContent(entry: ConstraintListEntry, key: string) {
  switch (key) {
    case "project":
      return entry.projectName ?? entry.projectId ?? "Not recorded";
    case "description":
      return entry.description ?? "Not recorded";
    case "status":
      return <Badge tone={lifecycleTone(entry.status)}>{lifecycleLabel(entry.status)}</Badge>;
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

/**
 * One Register row, with its own bounded inline-edit state.
 *
 * `localEntry` mirrors the incoming `entry` prop and is what every cell
 * renders from. A commit sets it optimistically before the write confirms
 * (`PC-CM-FE-AC-054`'s optimistic half); a failure restores the value the row
 * held immediately before that edit (the rollback half); a confirmed edit that
 * returned a freshly re-read row adopts it outright, so a genuinely fresher
 * prop (the parent's own subsequent Register refresh) and this row's own
 * optimistic state can never both claim to be current at once.
 */
function RegisterRow({
  entry,
  state,
  viewport,
  onSelect,
  onTriggerMount,
  onInlineEdit,
  columns,
}: {
  readonly entry: ConstraintListEntry;
  readonly state: ConstraintUrlState;
  readonly viewport: ConstraintViewport;
  readonly onSelect: (constraintId: string) => void;
  readonly onTriggerMount?: (constraintId: string, node: HTMLButtonElement | null) => void;
  readonly onInlineEdit?: OnInlineEdit;
  readonly columns: readonly Column[];
}) {
  const [localEntry, setLocalEntry] = useState(entry);
  const [errors, setErrors] = useState<Partial<Record<InlineEditableField, string>>>({});
  const [pendingField, setPendingField] = useState<InlineEditableField | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  // The Register row carries no `currentUpdate` field (it is a detail-only
  // member of `ConstraintView`, not `ConstraintListEntry`), so opening this
  // editor reads the canonical current text first — a blank starting point
  // would let a save silently replace existing narrative content with
  // whatever was typed, which is exactly the silent-overwrite this build
  // never does. `updateReady` gates Save until that read has resolved.
  const [updateDraft, setUpdateDraft] = useState("");
  const [updateReady, setUpdateReady] = useState(false);
  const [updateReadFailed, setUpdateReadFailed] = useState(false);
  const [bicDraft, setBicDraft] = useState<readonly RequestPartyRef[]>(() => toRequestParties(entry.bic));

  // Adopt a fresher `entry` prop (a full Register refresh, or this row's own
  // confirmed edit flowing back down) whenever its identity changes; an
  // in-flight optimistic edit is never overwritten by a stale re-render of
  // the same `entry` object.
  const [trackedId, setTrackedId] = useState(entry);
  if (trackedId !== entry) {
    setTrackedId(entry);
    setLocalEntry(entry);
  }

  const terminal = localEntry.status !== null && TERMINAL_CONSTRAINT_LIFECYCLES.includes(localEntry.status);
  // Each row's own `projectId` (never a page-level prop) is what the Current
  // Update re-read below dispatches against — the one thing that lets this
  // same component serve the portfolio Register's multi-Project rows without
  // a second copy of itself.
  const editable = onInlineEdit !== undefined && !terminal && entry.projectId !== null;
  const statusEditable = editable && localEntry.status !== null && ACTIVE_STATES.includes(localEntry.status);

  async function commit(
    field: InlineEditableField,
    value: InlineEditValue,
    optimisticPatch: Partial<ConstraintListEntry>,
  ) {
    if (!onInlineEdit) return;
    const before = localEntry;
    setLocalEntry({ ...localEntry, ...optimisticPatch });
    setPendingField(field);
    setErrors((current) => ({ ...current, [field]: undefined }));
    const result = await onInlineEdit({
      constraintId: entry.constraintId,
      field,
      value,
      expectedVersion: before.version,
    });
    setPendingField(null);
    if (!result.ok) {
      setLocalEntry(before);
      setErrors((current) => ({ ...current, [field]: result.message ?? "The change was not saved." }));
      return;
    }
    if (result.entry) setLocalEntry(result.entry);
  }

  return (
    <>
      <tr
        data-testid={`register-row-${entry.constraintId}`}
        data-selected={state.selectedConstraintId === entry.constraintId || undefined}
        className="border-b border-border-subtle data-[selected]:bg-surface-subtle"
      >
        {columns.map((column) => {
          if (column.key === "code") {
            return (
              <th key={column.key} scope="row" className="px-2 py-2 font-normal align-top">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    id={rowTriggerId(entry.constraintId)}
                    ref={(node) => onTriggerMount?.(entry.constraintId, node)}
                    onClick={() => onSelect(entry.constraintId)}
                    className="inline-flex min-h-11 items-center rounded text-left font-medium text-moss-green underline"
                  >
                    {codeLabel(localEntry.constraintCode)}
                  </button>
                  {editable ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid={`register-inline-current-update-toggle-${entry.constraintId}`}
                      aria-expanded={updateOpen}
                      onClick={() => {
                        setUpdateOpen((open) => {
                          const next = !open;
                          if (next) {
                            setUpdateReady(false);
                            setUpdateReadFailed(false);
                            setUpdateDraft("");
                            const controller = new AbortController();
                            void readDetail(entry.projectId as string, entry.constraintId, controller.signal).then((result) => {
                              if (result.ok) {
                                setUpdateDraft(result.value.currentUpdate ?? "");
                                setUpdateReady(true);
                              } else {
                                setUpdateReadFailed(true);
                              }
                            });
                          }
                          return next;
                        });
                      }}
                    >
                      Update
                    </Button>
                  ) : null}
                </div>
                {viewport === "tablet" ? (
                  <span className="mt-1 block text-xs text-muted">
                    {localEntry.daysElapsed === null
                      ? "Days open not recorded"
                      : `${localEntry.daysElapsed} days open`}
                    {localEntry.reference === null ? "" : ` · ${localEntry.reference}`}
                  </span>
                ) : null}
              </th>
            );
          }
          if (column.key === "status" && statusEditable) {
            return (
              <td key={column.key} className="px-2 py-2 align-top">
                <Select
                  value={localEntry.status ?? ""}
                  aria-label={`Status for ${codeLabel(localEntry.constraintCode)}`}
                  data-testid={`register-inline-status-${entry.constraintId}`}
                  disabled={pendingField === "status"}
                  onChange={(event) => {
                    const next = event.target.value as ConstraintLifecycle;
                    void commit("status", next.toLowerCase(), { status: next });
                  }}
                >
                  {ACTIVE_STATES.map((option) => (
                    <option key={option} value={option}>
                      {lifecycleLabel(option)}
                    </option>
                  ))}
                </Select>
                {errors.status ? (
                  <p role="alert" className="mt-1 text-xs text-moss-coral-strong" data-testid={`register-inline-status-error-${entry.constraintId}`}>
                    {errors.status}
                  </p>
                ) : null}
              </td>
            );
          }
          if (column.key === "due" && editable) {
            return (
              <td key={column.key} className="px-2 py-2 align-top">
                <div className="flex flex-wrap items-center gap-1">
                  <Input
                    type="date"
                    value={localEntry.dueDate ?? ""}
                    aria-label={`Due date for ${codeLabel(localEntry.constraintCode)}`}
                    data-testid={`register-inline-due-${entry.constraintId}`}
                    disabled={pendingField === "due"}
                    onChange={(event) => {
                      const next = event.target.value;
                      if (next.length === 0) return;
                      void commit("due", next, { dueDate: next });
                    }}
                  />
                  <StateChips entry={localEntry} />
                </div>
                {errors.due ? (
                  <p role="alert" className="mt-1 text-xs text-moss-coral-strong" data-testid={`register-inline-due-error-${entry.constraintId}`}>
                    {errors.due}
                  </p>
                ) : null}
              </td>
            );
          }
          if (column.key === "bic" && editable) {
            return (
              <td key={column.key} className="px-2 py-2 align-top">
                <Popover
                  onOpenChange={(open) => {
                    if (open) setBicDraft(toRequestParties(localEntry.bic));
                  }}
                >
                  <PopoverTrigger asChild>
                    <Button size="sm" variant="ghost" data-testid={`register-inline-bic-toggle-${entry.constraintId}`}>
                      {partyLabel(localEntry.bic)}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent aria-label="Edit Ball in Court" className="grid w-72 gap-2">
                    <ConstraintPartySelector
                      label="Ball in Court"
                      value={bicDraft}
                      onChange={setBicDraft}
                      testIdPrefix={`register-inline-bic-${entry.constraintId}`}
                    />
                    <Button
                      size="sm"
                      disabled={pendingField === "bic"}
                      data-testid={`register-inline-bic-save-${entry.constraintId}`}
                      onClick={() => void commit("bic", bicDraft, {})}
                    >
                      Save
                    </Button>
                  </PopoverContent>
                </Popover>
                {errors.bic ? (
                  <p role="alert" className="mt-1 text-xs text-moss-coral-strong" data-testid={`register-inline-bic-error-${entry.constraintId}`}>
                    {errors.bic}
                  </p>
                ) : null}
              </td>
            );
          }
          return (
            <td key={column.key} className="px-2 py-2 align-top">
              {readOnlyCellContent(localEntry, column.key)}
            </td>
          );
        })}
      </tr>
      {updateOpen ? (
        <tr data-testid={`register-inline-current-update-row-${entry.constraintId}`}>
          <td colSpan={columns.length} className="px-2 pb-2">
            {!updateReady && !updateReadFailed ? (
              <p role="status" className="text-sm text-muted" data-testid={`register-inline-current-update-loading-${entry.constraintId}`}>
                Reading the current text…
              </p>
            ) : updateReadFailed ? (
              <p role="alert" className="text-sm text-moss-coral-strong" data-testid={`register-inline-current-update-read-failed-${entry.constraintId}`}>
                The current text could not be read, so it cannot be safely replaced here. Open the
                full record to edit it.
              </p>
            ) : (
              <>
                <label className="grid gap-1 text-sm">
                  Current Update
                  <Textarea
                    value={updateDraft}
                    data-testid={`register-inline-current-update-${entry.constraintId}`}
                    onChange={(event) => setUpdateDraft(event.target.value)}
                    onKeyDown={multilineCommitHandler(() => void commit("currentUpdate", updateDraft, {}))}
                  />
                </label>
                {errors.currentUpdate ? (
                  <p role="alert" className="mt-1 text-xs text-moss-coral-strong" data-testid={`register-inline-current-update-error-${entry.constraintId}`}>
                    {errors.currentUpdate}
                  </p>
                ) : null}
                <div className="mt-1 flex gap-2">
                  <Button
                    size="sm"
                    disabled={pendingField === "currentUpdate"}
                    data-testid={`register-inline-current-update-save-${entry.constraintId}`}
                    onClick={() => void commit("currentUpdate", updateDraft, {})}
                  >
                    {pendingField === "currentUpdate" ? "Saving…" : "Save"}
                  </Button>
                  <Button size="sm" variant="ghost" data-testid={`register-inline-current-update-cancel-${entry.constraintId}`} onClick={() => setUpdateOpen(false)}>
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function RegisterTable({
  entries,
  state,
  viewport,
  caption,
  onSelect,
  onSort,
  onTriggerMount,
  onInlineEdit,
  showProjectColumn = false,
}: RegisterTableProps) {
  const columns = visibleColumns(state, viewport, showProjectColumn);
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
            <RegisterRow
              key={entry.constraintId}
              entry={entry}
              state={state}
              viewport={viewport}
              onSelect={onSelect}
              onTriggerMount={onTriggerMount}
              onInlineEdit={onInlineEdit}
              columns={columns}
            />
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
  onTriggerMount,
  showProject = false,
}: {
  readonly entries: readonly ConstraintListEntry[];
  readonly state: ConstraintUrlState;
  readonly onSelect: (constraintId: string) => void;
  readonly onTriggerMount?: (constraintId: string, node: HTMLButtonElement | null) => void;
  /** The portfolio Register's own field — see `RegisterTableProps.showProjectColumn`. */
  readonly showProject?: boolean;
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
              ref={(node) => onTriggerMount?.(entry.constraintId, node)}
              onClick={() => onSelect(entry.constraintId)}
              className="min-h-11 rounded text-left font-medium text-moss-green underline"
            >
              {codeLabel(entry.constraintCode)}
            </button>
            <Badge tone={lifecycleTone(entry.status)}>{lifecycleLabel(entry.status)}</Badge>
          </div>
          {showProject ? (
            <p className="mt-1 text-xs font-medium text-moss-slate" data-testid={`register-card-project-${entry.constraintId}`}>
              {entry.projectName ?? entry.projectId ?? "Not recorded"}
            </p>
          ) : null}
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
