"use client";

/**
 * The Register: the working surface, its toolbar, and the four answers it may
 * give when it is not showing rows.
 *
 * The default state is fixed by `CM-FE-AC-020` — open, grouped by Category, by
 * Code ascending — and is defined once, as a value, in `constraint-url-state`.
 *
 * **The quick filters are backend intents, not client predicates.** Overdue,
 * Due Soon, My Court and Needs Attention set a URL flag; the read plane selects
 * on the boolean the backend already put on the row. This component never sees
 * a date. Its filters and the Overview's counts therefore cannot drift apart,
 * which is the failure the separation exists to prevent.
 *
 * **Paging is bounded continuation, and the cursor is the last row's identity.**
 * Fifty rows, then "Load 50 more" — no infinite scroll, no page numbers, no
 * virtualization (`04` §14). Continuation appends; it never re-fetches what is
 * on screen, so a loaded row cannot appear twice.
 */
import { useMemo, useState } from "react";
import type {
  ConstraintCategory,
  ConstraintListEntry,
  ConstraintPartyRef,
} from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SurfaceState } from "@/components/ui/surface-state";
import { LiveAnnouncement } from "@/components/ui/live-region";
import {
  UNRESOLVED_PARTY_FILTER_BUCKET,
  type ConstraintGrouping,
  type ConstraintLifecycle,
  type ConstraintListScope,
  type ConstraintSort,
} from "@/contracts/constraints";
import type { ConstraintUrlState } from "./constraint-url-state";
import { clearedFilters, hasActiveFilters } from "./constraint-url-state";
import { groupRegisterEntries, queryRegisterPage, REGISTER_PAGE_SIZE } from "./register-query";
import { RegisterCardList, RegisterTable } from "./register-table";
import type { ConstraintViewport } from "./use-viewport";
import { lifecycleLabel, syncLabel } from "./presentation";

const SCOPES: readonly { readonly value: ConstraintListScope; readonly label: string }[] = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
];

const QUICK_FILTERS = [
  { key: "overdue", label: "Overdue" },
  { key: "dueSoon", label: "Due Soon" },
  { key: "inMyCourt", label: "My Court" },
  { key: "needsAttention", label: "Needs Attention" },
] as const;

const GROUPINGS: readonly { readonly value: ConstraintGrouping; readonly label: string }[] = [
  { value: "category", label: "Category" },
  { value: "bic", label: "Ball in Court" },
  { value: "responsible", label: "Responsible party" },
  { value: "status", label: "Status" },
  { value: "none", label: "None" },
];

const SORTS: readonly { readonly value: ConstraintSort; readonly label: string }[] = [
  { value: "code", label: "Code" },
  { value: "dateIdentified", label: "Date Identified" },
  { value: "daysOpen", label: "Days Open" },
  { value: "due", label: "Due Date" },
  { value: "updated", label: "Recently Updated" },
];

const LIFECYCLES: readonly ConstraintLifecycle[] = [
  "DRAFT",
  "IDENTIFIED",
  "PENDING",
  "IN_PROGRESS",
  "ON_HOLD",
  "CLOSED",
  "VOID",
];

export interface ConstraintsRegisterProps {
  readonly projectId: string;
  readonly entries: readonly ConstraintListEntry[];
  readonly categories: readonly ConstraintCategory[];
  readonly partyOptions: readonly ConstraintPartyRef[];
  readonly state: ConstraintUrlState;
  readonly viewport: ConstraintViewport;
  readonly onStateChange: (next: ConstraintUrlState, options?: { readonly replace?: boolean }) => void;
  readonly onSelect: (constraintId: string) => void;
  readonly onNewConstraint: () => void;
}

export function ConstraintsRegister({
  projectId,
  entries,
  categories,
  partyOptions,
  state,
  viewport,
  onStateChange,
  onSelect,
  onNewConstraint,
}: ConstraintsRegisterProps) {
  /**
   * How far the reader has continued, as a cursor and not a page number.
   *
   * Reset implicitly whenever the query changes, because the memo below is
   * keyed on the query: a continuation into a query that no longer exists is
   * not a thing this component can hold.
   */
  const [cursors, setCursors] = useState<readonly string[]>([]);
  const queryKey = JSON.stringify({ ...state, selectedConstraintId: null });

  const loaded = useMemo(() => {
    // Every page from the first, in order. Each is a bounded read from the
    // same total order, so appending them cannot duplicate or skip a row.
    const pages = [];
    let cursor: string | null = null;
    const wanted = cursors.length;
    for (let index = 0; index <= wanted; index += 1) {
      const page = queryRegisterPage(entries, state, projectId, cursor);
      pages.push(page);
      cursor = page.nextCursor;
      if (cursor === null) break;
    }
    const rows = pages.flatMap((page) => page.entries);
    const last = pages[pages.length - 1];
    return { rows, isTruncated: last.isTruncated, nextCursor: last.nextCursor, totalCount: last.totalCount };
    // `queryKey` is the query's identity; `cursors.length` is how far into it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, projectId, queryKey, cursors.length]);

  const categoryTitles = useMemo(() => {
    const map = new Map<string, string>();
    for (const category of categories) map.set(category.categoryId, category.title);
    return map;
  }, [categories]);

  const partyTitles = useMemo(() => {
    const map = new Map<string, string>();
    for (const party of partyOptions) map.set(party.partyRefId ?? "", party.displayLabel);
    return map;
  }, [partyOptions]);

  const groups = useMemo(
    () =>
      groupRegisterEntries(loaded.rows, state, (key) => {
        const [dimension, value] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
        if (dimension === "category") return categoryTitles.get(value) ?? "Category not recorded";
        if (dimension === "status") {
          return lifecycleLabel(value === "unavailable" ? null : (value as ConstraintLifecycle));
        }
        if (value === UNRESOLVED_PARTY_FILTER_BUCKET) return "Unresolved or not recorded";
        return partyTitles.get(value) ?? "Not recorded";
      }),
    [loaded.rows, state, categoryTitles, partyTitles],
  );

  function update(next: Partial<ConstraintUrlState>, options?: { readonly replace?: boolean }) {
    setCursors([]);
    onStateChange({ ...state, ...next }, options);
  }

  const filtered = hasActiveFilters(state);

  return (
    <section aria-label="Constraint Register" className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Register scope" className="flex flex-wrap gap-1">
          {SCOPES.map((scope) => (
            <Button
              key={scope.value}
              size="sm"
              variant={state.scope === scope.value ? "primary" : "secondary"}
              aria-pressed={state.scope === scope.value}
              data-testid={`register-scope-${scope.value}`}
              onClick={() => update({ scope: scope.value })}
            >
              {scope.label}
            </Button>
          ))}
        </div>
        <label className="flex-1 min-w-56">
          <span className="sr-only">Search Constraints in this Project</span>
          <Input
            type="search"
            value={state.search}
            placeholder="Search constraints…"
            data-testid="register-search"
            // Search replaces rather than pushes: a history entry per keystroke
            // would make Back useless (`02` §13).
            onChange={(event) => update({ search: event.target.value }, { replace: true })}
          />
        </label>
        <Button size="sm" onClick={onNewConstraint} data-testid="register-new-constraint">
          New Constraint
        </Button>
      </div>

      <div role="group" aria-label="Quick filters" className="flex flex-wrap gap-1">
        {QUICK_FILTERS.map((filter) => (
          <Button
            key={filter.key}
            size="sm"
            variant={state[filter.key] ? "primary" : "secondary"}
            aria-pressed={state[filter.key]}
            data-testid={`register-quick-${filter.key}`}
            onClick={() => update({ [filter.key]: !state[filter.key] } as Partial<ConstraintUrlState>)}
          >
            {filter.label}
          </Button>
        ))}
        <Popover>
          <PopoverTrigger asChild>
            <Button size="sm" variant="secondary" data-testid="register-filters">
              Filters
            </Button>
          </PopoverTrigger>
          <PopoverContent aria-label="Advanced filters" className="grid w-72 gap-3">
            <label className="grid gap-1 text-sm">
              Status
              <Select
                value={state.status ?? ""}
                data-testid="register-filter-status"
                onChange={(event) =>
                  update({ status: (event.target.value || null) as ConstraintLifecycle | null })
                }
              >
                <option value="">Any status</option>
                {LIFECYCLES.map((lifecycle) => (
                  <option key={lifecycle} value={lifecycle}>
                    {lifecycleLabel(lifecycle)}
                  </option>
                ))}
              </Select>
            </label>
            <label className="grid gap-1 text-sm">
              Category
              <Select
                value={state.categoryId ?? ""}
                data-testid="register-filter-category"
                onChange={(event) => update({ categoryId: event.target.value || null })}
              >
                <option value="">Any Category</option>
                {categories.map((category) => (
                  <option key={category.categoryId} value={category.categoryId}>
                    {category.title}
                    {category.state === "ACTIVE" ? "" : " (inactive)"}
                  </option>
                ))}
              </Select>
            </label>
            {/*
              Party filters offer only options with a stable server reference,
              plus the whole Unresolved bucket. An unresolved party has no
              identity of its own, so it is deliberately not individually
              selectable here (`CM-FE-AC-009`).
            */}
            <label className="grid gap-1 text-sm">
              Ball in Court
              <Select
                value={state.bic ?? ""}
                data-testid="register-filter-bic"
                onChange={(event) => update({ bic: event.target.value || null })}
              >
                <option value="">Any Ball in Court</option>
                {partyOptions.map((party) => (
                  <option key={party.partyRefId ?? ""} value={party.partyRefId ?? ""}>
                    {party.displayLabel}
                  </option>
                ))}
                <option value={UNRESOLVED_PARTY_FILTER_BUCKET}>Unresolved (all)</option>
              </Select>
            </label>
            <label className="grid gap-1 text-sm">
              Responsible party
              <Select
                value={state.responsible ?? ""}
                data-testid="register-filter-responsible"
                onChange={(event) => update({ responsible: event.target.value || null })}
              >
                <option value="">Any Responsible party</option>
                {partyOptions.map((party) => (
                  <option key={party.partyRefId ?? ""} value={party.partyRefId ?? ""}>
                    {party.displayLabel}
                  </option>
                ))}
                <option value={UNRESOLVED_PARTY_FILTER_BUCKET}>Unresolved (all)</option>
              </Select>
            </label>
            <label className="grid gap-1 text-sm">
              Synchronisation state
              <Select
                value={state.sync ?? ""}
                data-testid="register-filter-sync"
                onChange={(event) =>
                  update({ sync: (event.target.value || null) as ConstraintUrlState["sync"] })
                }
              >
                <option value="">Any sync state</option>
                {(["NEVER_SYNCED", "IN_SYNC", "DB_EXPORT_PENDING", "CONFLICT"] as const).map(
                  (syncState) => (
                    <option key={syncState} value={syncState}>
                      {syncLabel(syncState)}
                    </option>
                  ),
                )}
              </Select>
            </label>
          </PopoverContent>
        </Popover>
        <label className="flex items-center gap-1 text-sm">
          Group
          <Select
            value={state.group}
            data-testid="register-group"
            onChange={(event) => update({ group: event.target.value as ConstraintGrouping })}
          >
            {GROUPINGS.map((grouping) => (
              <option key={grouping.value} value={grouping.value}>
                {grouping.label}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-1 text-sm">
          Sort
          <Select
            value={state.sort}
            data-testid="register-sort"
            onChange={(event) => update({ sort: event.target.value as ConstraintSort })}
          >
            {SORTS.map((sort) => (
              <option key={sort.value} value={sort.value}>
                {sort.label}
              </option>
            ))}
          </Select>
        </label>
        <Button
          size="sm"
          variant="secondary"
          data-testid="register-direction"
          aria-label={state.dir === "asc" ? "Sorted ascending. Sort descending." : "Sorted descending. Sort ascending."}
          onClick={() => update({ dir: state.dir === "asc" ? "desc" : "asc" })}
        >
          {state.dir === "asc" ? "Ascending" : "Descending"}
        </Button>
      </div>

      {filtered ? (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="register-active-filters">
          <span className="text-muted">Active filters:</span>
          <Badge tone="neutral">{SCOPES.find((s) => s.value === state.scope)?.label}</Badge>
          {QUICK_FILTERS.filter((filter) => state[filter.key]).map((filter) => (
            <Badge key={filter.key} tone="gold">
              {filter.label}
            </Badge>
          ))}
          {state.status ? <Badge tone="neutral">{lifecycleLabel(state.status)}</Badge> : null}
          {state.categoryId ? (
            <Badge tone="neutral">
              {categoryTitles.get(state.categoryId) ?? "Category not in this Project"}
            </Badge>
          ) : null}
          {state.search.trim().length > 0 ? <Badge tone="neutral">“{state.search}”</Badge> : null}
          <Button size="sm" variant="ghost" data-testid="register-clear-filters" onClick={() => update(clearedFilters(state))}>
            Clear filters
          </Button>
        </div>
      ) : null}

      <LiveAnnouncement testId="register-live">
        {`Showing ${loaded.rows.length} of ${loaded.totalCount ?? loaded.rows.length} Constraints.`}
      </LiveAnnouncement>

      {loaded.rows.length === 0 ? (
        filtered ? (
          <SurfaceState
            kind="empty"
            title="No Constraints match these filters"
            detail="The read succeeded. These filters select nothing in this Project."
            testId="register-empty-filtered"
          >
            <Button size="sm" variant="secondary" onClick={() => update(clearedFilters(state))}>
              Clear filters
            </Button>
          </SurfaceState>
        ) : (
          <SurfaceState
            kind="empty"
            title="This Project holds no Constraints"
            detail="The read succeeded and this Project's Constraint Register is empty."
            testId="register-empty-project"
          >
            <Button size="sm" variant="secondary" onClick={onNewConstraint}>
              New Constraint
            </Button>
          </SurfaceState>
        )
      ) : (
        <div className="grid gap-4">
          {groups.map((group) => (
            <section key={group.key} aria-label={group.label} data-testid={`register-group-${group.key}`}>
              {state.group === "none" ? null : (
                <h3 className="mb-1 text-sm font-semibold text-moss-slate">
                  {group.label}{" "}
                  <span className="font-normal text-muted">
                    ({group.entries.length} loaded
                    {loaded.isTruncated ? " so far" : ""})
                  </span>
                </h3>
              )}
              {viewport === "mobile" ? (
                <RegisterCardList entries={group.entries} state={state} onSelect={onSelect} />
              ) : (
                <RegisterTable
                  entries={group.entries}
                  state={state}
                  viewport={viewport}
                  caption={`${group.label} — Constraint Register`}
                  onSelect={onSelect}
                  onSort={(sort) =>
                    update(
                      sort === state.sort
                        ? { dir: state.dir === "asc" ? "desc" : "asc" }
                        : { sort, dir: "asc" },
                    )
                  }
                />
              )}
            </section>
          ))}
          <div className="flex items-center gap-3 text-sm text-muted">
            <span data-testid="register-count">
              {loaded.rows.length} loaded
              {loaded.totalCount === null ? "" : ` of ${loaded.totalCount} matching`}
            </span>
            {loaded.isTruncated && loaded.nextCursor !== null ? (
              <Button
                size="sm"
                variant="secondary"
                data-testid="register-load-more"
                onClick={() => setCursors((current) => [...current, loaded.nextCursor as string])}
              >
                Load {REGISTER_PAGE_SIZE} more
              </Button>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
