/**
 * The Register's durable view state, and the line between it and everything
 * that must never reach the address bar.
 *
 * There is no query-state library in this repository and this work package does
 * not introduce one: `useSearchParams`/`useRouter` are used directly in exactly
 * one other place (`app/sign-in/sign-in-form.tsx`), and the accepted routing
 * document asks for "current Next.js conventions and shared URL helpers rather
 * than a feature-local routing system". So this is a pair of pure functions
 * over `URLSearchParams` — parse and serialize — feature-local by scope and
 * deliberately not a framework.
 *
 * **What is here is what a colleague can be sent.** Project (which is route
 * identity, not a parameter), tab, scope, the four quick filters, the advanced
 * filters, search text, grouping, sort, direction, and the selected Constraint.
 * Those are the things a link is *for*.
 *
 * **What is deliberately absent is the whole safety property.** No unsaved
 * Draft field, no `expectedVersion`, no idempotency key, no receipt, no
 * in-flight editor value, no conflict working copy, no collapsed-group state.
 * `02_INFORMATION_ARCHITECTURE_AND_ROUTING` §6 lists them; `CM-FE-AC-008` and
 * `CM-FE-AC-023` are the criteria. The reason is not tidiness: a URL is copied,
 * bookmarked, restored and shared, and a concurrency token that survived any of
 * those would be applied to a record it no longer describes. `serializeRegister`
 * below writes a closed set of keys and cannot emit one of those even if a
 * caller passed it, because it never reads a caller's object wholesale.
 *
 * Every unrecognised or malformed value falls back to its default rather than
 * being forwarded: a query the backend never defined is not something this tier
 * passes through (`02` §15).
 */
import type {
  ConstraintGrouping,
  ConstraintLifecycle,
  ConstraintListScope,
  ConstraintSort,
  ConstraintSortDirection,
  ConstraintSyncState,
} from "@/contracts/constraints";

/** The two v1 tabs. There is no third, and `overview` is the default. */
export type ConstraintWorkspaceTab = "overview" | "register";

/**
 * The Register state a URL can carry.
 *
 * `selectedConstraintId` lives here because selection is durable, linkable
 * identity (`CM-FE-AC-091`). Nothing about *editing* that Constraint does.
 */
export interface ConstraintUrlState {
  readonly view: ConstraintWorkspaceTab;
  readonly scope: ConstraintListScope;
  readonly status: ConstraintLifecycle | null;
  readonly categoryId: string | null;
  readonly bic: string | null;
  readonly responsible: string | null;
  readonly overdue: boolean;
  readonly dueSoon: boolean;
  readonly inMyCourt: boolean;
  readonly needsAttention: boolean;
  readonly sync: ConstraintSyncState | null;
  readonly search: string;
  readonly group: ConstraintGrouping;
  readonly sort: ConstraintSort;
  readonly dir: ConstraintSortDirection;
  readonly selectedConstraintId: string | null;
}

/**
 * The frozen default Register state: open, grouped by Category, by Code
 * ascending (`CM-FE-AC-020`). It is frozen here so a test can assert it as a
 * value rather than by driving the UI and hoping.
 */
export const DEFAULT_CONSTRAINT_URL_STATE: ConstraintUrlState = {
  view: "overview",
  scope: "open",
  status: null,
  categoryId: null,
  bic: null,
  responsible: null,
  overdue: false,
  dueSoon: false,
  inMyCourt: false,
  needsAttention: false,
  sync: null,
  search: "",
  group: "category",
  sort: "code",
  dir: "asc",
  selectedConstraintId: null,
};

const TABS: readonly ConstraintWorkspaceTab[] = ["overview", "register"];
const SCOPES: readonly ConstraintListScope[] = ["open", "closed", "all", "draft"];
const GROUPINGS: readonly ConstraintGrouping[] = [
  "none",
  "category",
  "status",
  "bic",
  "responsible",
];
const SORTS: readonly ConstraintSort[] = ["code", "dateIdentified", "daysOpen", "due", "updated"];
const DIRECTIONS: readonly ConstraintSortDirection[] = ["asc", "desc"];
const LIFECYCLES: readonly ConstraintLifecycle[] = [
  "DRAFT",
  "IDENTIFIED",
  "PENDING",
  "IN_PROGRESS",
  "ON_HOLD",
  "CLOSED",
  "VOID",
];
const SYNC_STATES: readonly ConstraintSyncState[] = [
  "NEVER_SYNCED",
  "IN_SYNC",
  "DB_EXPORT_PENDING",
  "EXTERNAL_IMPORT_PENDING",
  "CONFLICT",
  "WORKBOOK_UNAVAILABLE",
  "SCHEMA_UNSUPPORTED",
  "PARTIAL",
  "VERIFICATION_PENDING",
  "VERIFICATION_FAILED",
];

/** Query values arrive as `string | string[] | undefined` from a server page. */
export type RawSearchParams = Readonly<
  Record<string, string | readonly string[] | undefined>
>;

function first(value: string | readonly string[] | undefined | null): string | null {
  if (value === undefined || value === null) return null;
  const single = Array.isArray(value) ? value[0] : (value as string);
  if (typeof single !== "string") return null;
  const trimmed = single.trim();
  return trimmed.length === 0 ? null : trimmed;
}

function oneOf<T extends string>(
  value: string | null,
  admitted: readonly T[],
  fallback: T,
): T {
  return value !== null && (admitted as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function optionalOneOf<T extends string>(
  value: string | null,
  admitted: readonly T[],
): T | null {
  return value !== null && (admitted as readonly string[]).includes(value) ? (value as T) : null;
}

/** A flag is on only for the literal `1`. Nothing else is truthy here. */
function flag(value: string | null): boolean {
  return value === "1";
}

/** Identifiers are opaque, bounded and never interpreted. */
function identifier(value: string | null): string | null {
  if (value === null) return null;
  return /^[A-Za-z0-9_.:-]{1,128}$/.test(value) ? value : null;
}

/** Read durable view state out of a query. Unknown values become defaults. */
export function parseConstraintUrlState(params: RawSearchParams): ConstraintUrlState {
  return {
    view: oneOf(first(params.view), TABS, DEFAULT_CONSTRAINT_URL_STATE.view),
    scope: oneOf(first(params.scope), SCOPES, DEFAULT_CONSTRAINT_URL_STATE.scope),
    status: optionalOneOf(first(params.status), LIFECYCLES),
    categoryId: identifier(first(params.category)),
    bic: identifier(first(params.bic)),
    responsible: identifier(first(params.responsible)),
    overdue: flag(first(params.overdue)),
    dueSoon: flag(first(params.dueSoon)),
    inMyCourt: flag(first(params.inMyCourt)),
    needsAttention: flag(first(params.needsAttention)),
    sync: optionalOneOf(first(params.sync), SYNC_STATES),
    search: first(params.q)?.slice(0, 200) ?? "",
    group: oneOf(first(params.group), GROUPINGS, DEFAULT_CONSTRAINT_URL_STATE.group),
    sort: oneOf(first(params.sort), SORTS, DEFAULT_CONSTRAINT_URL_STATE.sort),
    dir: oneOf(first(params.dir), DIRECTIONS, DEFAULT_CONSTRAINT_URL_STATE.dir),
    selectedConstraintId: identifier(first(params.constraint)),
  };
}

/** Parse from a `URLSearchParams`, which is what a client component holds. */
export function parseConstraintUrlSearchParams(params: URLSearchParams): ConstraintUrlState {
  const raw: Record<string, string> = {};
  for (const [key, value] of params.entries()) raw[key] = value;
  return parseConstraintUrlState(raw);
}

/**
 * Write durable view state back out, omitting everything at its default.
 *
 * The omission matters beyond neatness: a link that carried every default would
 * pin state a later default change should have moved, and would make two
 * identical views look like two different addresses.
 */
export function serializeConstraintUrlState(state: ConstraintUrlState): string {
  const params = new URLSearchParams();
  const d = DEFAULT_CONSTRAINT_URL_STATE;
  if (state.view !== d.view) params.set("view", state.view);
  if (state.scope !== d.scope) params.set("scope", state.scope);
  if (state.status !== null) params.set("status", state.status);
  if (state.categoryId !== null) params.set("category", state.categoryId);
  if (state.bic !== null) params.set("bic", state.bic);
  if (state.responsible !== null) params.set("responsible", state.responsible);
  if (state.overdue) params.set("overdue", "1");
  if (state.dueSoon) params.set("dueSoon", "1");
  if (state.inMyCourt) params.set("inMyCourt", "1");
  if (state.needsAttention) params.set("needsAttention", "1");
  if (state.sync !== null) params.set("sync", state.sync);
  if (state.search.trim().length > 0) params.set("q", state.search.trim());
  if (state.group !== d.group) params.set("group", state.group);
  if (state.sort !== d.sort) params.set("sort", state.sort);
  if (state.dir !== d.dir) params.set("dir", state.dir);
  if (state.selectedConstraintId !== null) params.set("constraint", state.selectedConstraintId);
  return params.toString();
}

/** The canonical route for one Project's Constraints. Frozen by `CM-FE-AC-002`. */
export function constraintsRoute(projectId: string): string {
  return `/work/projects/${encodeURIComponent(projectId)}/constraints`;
}

/** The canonical route plus a serialized view state. */
export function constraintsHref(projectId: string, state: ConstraintUrlState): string {
  const query = serializeConstraintUrlState(state);
  const base = constraintsRoute(projectId);
  return query.length === 0 ? base : `${base}?${query}`;
}

/**
 * The Register state a KPI navigates to.
 *
 * One table, matching `03_OVERVIEW_PRODUCT_SPECIFICATION` §5 and `02` §7
 * exactly. `recentlyChanged` and `recentlyClosed` are absent on purpose: the
 * Register query contract at this head has no filter with the same semantic
 * window as those two metrics, and inventing a date range to make the card
 * clickable would be the frontend deciding what "recently" means.
 */
export type ConstraintKpiTarget =
  | "totalOpen"
  | "overdue"
  | "dueSoon"
  | "inMyCourt"
  | "needsAttention"
  | "onHold"
  | "draft";

export function kpiRegisterState(
  current: ConstraintUrlState,
  target: ConstraintKpiTarget,
): ConstraintUrlState {
  // A KPI answers one question, so it starts from the defaults rather than
  // layering onto whatever filters happened to be set; the grouping and sort a
  // reader chose are Project-neutral view preferences and are carried across.
  const base: ConstraintUrlState = {
    ...DEFAULT_CONSTRAINT_URL_STATE,
    view: "register",
    group: current.group,
    sort: current.sort,
    dir: current.dir,
  };
  switch (target) {
    case "totalOpen":
      return base;
    case "overdue":
      return { ...base, overdue: true };
    case "dueSoon":
      return { ...base, dueSoon: true };
    case "inMyCourt":
      return { ...base, inMyCourt: true };
    case "needsAttention":
      return { ...base, scope: "all", needsAttention: true };
    case "onHold":
      return { ...base, status: "ON_HOLD" };
    case "draft":
      return { ...base, scope: "draft" };
  }
}

/** The Register state an Open-by-Category bar navigates to (`CM-FE-AC-016`). */
export function categoryRegisterState(
  current: ConstraintUrlState,
  categoryId: string,
): ConstraintUrlState {
  return {
    ...DEFAULT_CONSTRAINT_URL_STATE,
    view: "register",
    group: current.group,
    sort: current.sort,
    dir: current.dir,
    categoryId,
  };
}

/**
 * Whether any filter narrowing the population is active.
 *
 * Used to tell "no rows match these filters" from "this Project holds no
 * Constraints", which are two different claims (`CM-FE-AC-029`).
 */
export function hasActiveFilters(state: ConstraintUrlState): boolean {
  return (
    state.status !== null ||
    state.categoryId !== null ||
    state.bic !== null ||
    state.responsible !== null ||
    state.overdue ||
    state.dueSoon ||
    state.inMyCourt ||
    state.needsAttention ||
    state.sync !== null ||
    state.search.trim().length > 0 ||
    state.scope !== DEFAULT_CONSTRAINT_URL_STATE.scope
  );
}

/** Clear every filter, keeping the tab, grouping, sort and selection. */
export function clearedFilters(state: ConstraintUrlState): ConstraintUrlState {
  return {
    ...DEFAULT_CONSTRAINT_URL_STATE,
    view: state.view,
    group: state.group,
    sort: state.sort,
    dir: state.dir,
    selectedConstraintId: state.selectedConstraintId,
  };
}

/**
 * The state a Project switch lands on.
 *
 * Project-neutral preferences — tab, grouping, sort, direction, scope — carry
 * across. Everything whose identity belongs to the old Project does not: the
 * Category, BIC and Responsible filters, and the selected Constraint. Carrying
 * a `cat_` identifier into another Project would either match nothing or, far
 * worse, match a similarly named option that is not the one the reader chose
 * (`02` §3 and `CM-FE-AC-004`/`009`).
 */
export function projectSwitchState(state: ConstraintUrlState): ConstraintUrlState {
  return {
    ...DEFAULT_CONSTRAINT_URL_STATE,
    view: state.view,
    scope: state.scope,
    group: state.group,
    sort: state.sort,
    dir: state.dir,
  };
}
