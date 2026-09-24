import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";
import type {
  ConstraintCategory,
  ConstraintHistoryEntry,
  ConstraintLifecycle,
  ConstraintListEntry,
  ConstraintListPage,
  ConstraintOverview,
  ConstraintPartyRef,
  ConstraintView,
} from "@/contracts/constraints";
import type { BackendProject } from "@/contracts/views";
import type {
  ConstraintCategory as WireCategory,
  ConstraintHistoryEntry as WireHistoryEntry,
  ConstraintListEntry as WireListEntry,
  ConstraintOverview as WireOverview,
  ConstraintPartyRef as WirePartyRef,
  ConstraintView as WireView,
} from "@/lib/api/decode/capabilities/_constraint-helpers";
import type { ConstraintUrlState } from "./constraint-url-state";

type BackendAnswer<T> = T & { readonly shape: "backend"; readonly disclosure: DisclosureEnvelope };
type ErrorAnswer = { readonly error?: Partial<ErrorEnvelope> };

export interface LiveFailure {
  readonly status: number;
  readonly code: string;
  readonly message: string;
}

export type LiveResult<T> =
  | { readonly ok: true; readonly value: T; readonly disclosure: DisclosureEnvelope }
  | { readonly ok: false; readonly error: LiveFailure };

/** The WP08 detail projection has references, but no backend URL-safety verdict. */
export type LiveConstraintView = Omit<ConstraintView, "evidenceLinks"> & {
  readonly evidenceLinks: WireView["evidenceLinks"];
};

/** The WP08 history projection omits human-readable provenance. */
export type LiveConstraintHistoryEntry = Omit<ConstraintHistoryEntry, "provenance">;

async function read<T>(path: string, signal: AbortSignal): Promise<LiveResult<T>> {
  try {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal });
    const body = (await response.json()) as BackendAnswer<T> | ErrorAnswer;
    if (!response.ok || !("shape" in body) || body.shape !== "backend") {
      const error = "error" in body ? body.error : undefined;
      return {
        ok: false,
        error: {
          status: response.status,
          code: error?.code ?? "read_failed",
          message: error?.message ?? `The read failed with status ${response.status}.`,
        },
      };
    }
    return { ok: true, value: body, disclosure: body.disclosure };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return { ok: false, error: { status: 0, code: "request_cancelled", message: "The read was superseded." } };
    }
    return {
      ok: false,
      error: { status: 0, code: "transport_unavailable", message: "The read plane could not be reached." },
    };
  }
}

const upper = <T extends string>(value: string): T => value.toUpperCase() as T;

function party(value: WirePartyRef): ConstraintPartyRef {
  return { ...value, kind: upper(value.kind) };
}

function listEntry(value: WireListEntry, grouping: ConstraintUrlState["group"]): ConstraintListEntry {
  return {
    ...value,
    status: upper<ConstraintLifecycle>(value.status),
    bic: value.bic.map(party),
    responsible: value.responsible.map(party),
    recordQuality: upper(value.recordQuality),
    syncState: upper(value.syncState),
    groupKeys: grouping === "none" ? [] : value.groupKeys.map((key) => `${grouping}:${upperGroupKey(grouping, key)}`),
  };
}

function upperGroupKey(grouping: ConstraintUrlState["group"], key: string): string {
  return grouping === "status" ? key.toUpperCase() : key;
}

function overview(value: WireOverview): ConstraintOverview {
  return {
    ...value,
    syncHealth: { ...value.syncHealth, state: upper(value.syncHealth.state) },
  };
}

function category(value: WireCategory): ConstraintCategory {
  return { ...value, state: upper(value.state) };
}

function detail(value: WireView): LiveConstraintView {
  return {
    ...value,
    status: upper<ConstraintLifecycle>(value.status),
    bic: value.bic.map(party),
    responsible: value.responsible.map(party),
    recordQuality: upper(value.recordQuality),
    needsAttentionReasons: value.needsAttentionReasons.map((item) => upper(item)),
    sync: { ...value.sync, state: upper(value.sync.state) },
    relationships: value.relationships.map((item) => ({
      ...item,
      direction: upper(item.direction),
      relatedStatus: item.relatedStatus === null ? null : upper<ConstraintLifecycle>(item.relatedStatus),
    })),
    evidenceLinks: value.evidenceLinks,
  };
}

function history(value: WireHistoryEntry): LiveConstraintHistoryEntry {
  return {
    ...value,
    operation: upper(value.operation),
    actor: upper(value.actor),
    outcome: upper(value.outcome),
  };
}

const SORTS = {
  code: "code",
  dateIdentified: "date_identified",
  daysOpen: "days_elapsed",
  due: "due_date",
  updated: "updated_at",
} as const;

export function registerQuery(state: ConstraintUrlState, cursor: string | null = null): string {
  const query = new URLSearchParams();
  query.set("scope", state.scope);
  query.set("pageSize", "50");
  if (cursor !== null) query.set("cursor", cursor);
  if (state.search.trim()) {
    query.set("q", state.search.trim());
    return query.toString();
  }
  if (state.status) query.append("status", state.status.toLowerCase());
  if (state.categoryId) query.append("category", state.categoryId);
  if (state.bic) query.append("bic", state.bic);
  if (state.responsible) query.append("responsible", state.responsible);
  if (state.sync) query.append("sync", state.sync.toLowerCase());
  if (state.quality) query.append("quality", state.quality.toLowerCase());
  if (state.overdue) query.set("overdue", "true");
  if (state.dueSoon) query.set("dueSoon", "true");
  if (state.inMyCourt) query.set("inMyCourt", "true");
  if (state.needsAttention) query.set("needsAttention", "true");
  query.set("sort", SORTS[state.sort]);
  query.set("dir", state.dir);
  query.set("group", state.group);
  return query.toString();
}

const root = (projectId: string) => `/api/project-controls/projects/${encodeURIComponent(projectId)}`;

export async function readProjects(signal: AbortSignal): Promise<LiveResult<readonly BackendProject[]>> {
  const response = await read<{ readonly projects: readonly BackendProject[] }>("/api/projects", signal);
  return response.ok ? { ...response, value: response.value.projects } : response;
}

export async function readOverview(projectId: string, signal: AbortSignal): Promise<LiveResult<ConstraintOverview>> {
  const response = await read<{ readonly overview: WireOverview }>(`${root(projectId)}/constraints/overview`, signal);
  return response.ok ? { ...response, value: overview(response.value.overview) } : response;
}

export async function readCategories(projectId: string, signal: AbortSignal): Promise<LiveResult<readonly ConstraintCategory[]>> {
  const response = await read<{ readonly categories: readonly WireCategory[] }>(`${root(projectId)}/constraint-categories?state=active&state=inactive&state=archived`, signal);
  return response.ok ? { ...response, value: response.value.categories.map(category) } : response;
}

export async function readRegister(projectId: string, state: ConstraintUrlState, cursor: string | null, signal: AbortSignal): Promise<LiveResult<ConstraintListPage>> {
  const response = await read<{ readonly constraints: readonly WireListEntry[] }>(`${root(projectId)}/constraints?${registerQuery(state, cursor)}`, signal);
  return response.ok
    ? {
        ...response,
        value: {
          entries: response.value.constraints.map((item) => listEntry(item, state.group)),
          isTruncated: response.disclosure.truncated,
          nextCursor: response.disclosure.nextCursor ?? null,
          totalCount: null,
        },
      }
    : response;
}

/**
 * Project a freshly-read canonical detail down into the Register's row shape.
 *
 * Used after an inline Register edit (`register-table.tsx`) confirms: rather
 * than hand-computing `isOverdue`/`isDueSoon`/`daysElapsed`/… from the edited
 * field, the row that replaces the optimistic one is built from a fresh
 * `readDetail` — the same backend-derived flags the rest of this feature
 * never recomputes (`PC-CM-FE-AC-059`). `groupKeys` is the one field a detail
 * read cannot supply (it is a Register-page concept); the caller passes the
 * row's prior membership through unchanged, so grouping can go stale for at
 * most this one row until the next full Register read replaces it — a
 * disclosed, narrow limitation, not a silent invention.
 */
export function detailToListEntry(
  detail: LiveConstraintView,
  priorGroupKeys: readonly string[],
): ConstraintListEntry {
  return {
    constraintId: detail.constraintId,
    projectId: detail.projectId,
    constraintCode: detail.constraintCode,
    description: detail.description,
    category: detail.category,
    status: detail.status,
    dateIdentified: detail.dateIdentified,
    dueDate: detail.dueDate,
    bic: detail.bic,
    responsible: detail.responsible,
    reference: detail.reference,
    daysElapsed: detail.daysElapsed,
    version: detail.version,
    updatedAt: detail.updatedAt,
    isOverdue: detail.isOverdue,
    isDueSoon: detail.isDueSoon,
    inMyCourt: detail.inMyCourt,
    recordQuality: detail.recordQuality,
    needsAttention: detail.needsAttention,
    syncState: detail.sync.state,
    groupKeys: priorGroupKeys,
  };
}

export async function readDetail(projectId: string, constraintId: string, signal: AbortSignal): Promise<LiveResult<LiveConstraintView>> {
  const response = await read<{ readonly constraint: WireView }>(`${root(projectId)}/constraints/${encodeURIComponent(constraintId)}`, signal);
  if (!response.ok) return response;
  if (response.value.constraint.projectId !== projectId) {
    return { ok: false, error: { status: 404, code: "constraint_not_in_project", message: "That Constraint was not returned for this Project." } };
  }
  const value = detail(response.value.constraint);
  return { ...response, value };
}

export async function readHistory(projectId: string, constraintId: string, cursor: string | null, signal: AbortSignal): Promise<LiveResult<{ entries: readonly LiveConstraintHistoryEntry[]; nextCursor: string | null }>> {
  const query = new URLSearchParams({ pageSize: "50" });
  if (cursor !== null) query.set("cursor", cursor);
  const response = await read<{ readonly history: readonly WireHistoryEntry[] }>(`${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/history?${query}`, signal);
  return response.ok
    ? { ...response, value: { entries: response.value.history.map(history), nextCursor: response.disclosure.nextCursor ?? null } }
    : response;
}

// --- R02-WP10 Phase 6: authoring / lifecycle / category mutation writes -----
//
// Everything below is a thin write layer over the R01-WP09 BFF routes
// (`app/api/project-controls/.../route.ts`), matched field-for-field against
// `constraint-requests.ts`'s browser vocabularies and the decoders in
// `lib/api/decode/capabilities/_constraint-authoring-helpers.ts`. A route's
// success body is already `{shape:"backend", ...<decoded camelCase result>,
// disclosure}` — the decoder on the server has already normalised snake_case
// to camelCase and validated every invariant, so nothing here re-decodes it; a
// response failing `response.ok` or missing `shape: "backend"` is thrown as a
// `LiveMutationFailure`, the shape `@/lib/constraint/mutation-coordinator`'s
// `classifyConstraintMutationError` already knows how to read (`status`,
// `code`, `message`), with `current` carried through only on the one path
// (`work-route.ts`'s own 409 handling) that ever supplies it.
//
// A caller (the four new Phase-6 authoring/lifecycle/category components)
// assembles the request body — the closed field set each BFF route admits,
// documented in `constraint-requests.ts` — and hands it to
// `ConstraintMutationCoordinator.mutate()`'s `dispatch` hook, which calls the
// matching function below with `idempotencyKey`/`expectedVersion`/
// `expectedVersions` already merged in. No function here mints an idempotency
// key itself; `mintIdempotencyKey` is the one place that does, so every retry
// path reuses the coordinator's own key rather than silently minting a new one.

export interface LiveMutationFailure {
  readonly status: number;
  readonly code: string;
  readonly message: string;
  /** Only ever set on a 409 whose body carried the canonical current state. */
  readonly current?: unknown;
}

/** A fresh idempotency key for one mutation attempt. Never reused across attempts. */
export function mintIdempotencyKey(): string {
  return crypto.randomUUID();
}

/** One BIC/Responsible party as the request body admits it (`work-route.ts`'s `PARTY_REF_KEYS`). */
export interface RequestPartyRef {
  readonly kind: "principal" | "entity" | "unresolved";
  readonly entityId?: string;
  readonly label?: string;
}

async function write<T>(
  method: "POST" | "PATCH",
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    const failure: LiveMutationFailure = {
      status: 0,
      code: "transport_unavailable",
      message: "The write plane could not be reached.",
    };
    throw failure;
  }
  let json: Record<string, unknown> | null = null;
  try {
    json = (await response.json()) as Record<string, unknown>;
  } catch {
    json = null;
  }
  if (!response.ok || json === null || json.shape !== "backend") {
    const errorBody =
      json !== null && typeof json.error === "object" && json.error !== null
        ? (json.error as { code?: string; message?: string })
        : {};
    const failure: LiveMutationFailure = {
      status: response.status,
      code: errorBody.code ?? "write_failed",
      message: errorBody.message ?? `The write failed with status ${response.status}.`,
      current: response.status === 409 && json !== null && "current" in json ? json.current : undefined,
    };
    throw failure;
  }
  return json as unknown as T;
}

/** One BIC/Responsible party, straight off the mutation wire (`asdict(PartyRef)`, camelCased). */
export interface WireMutationParty {
  readonly kind: "principal" | "entity" | "unresolved";
  readonly entityId: string | null;
  readonly label: string | null;
}

/** The 22 safe members of a mutated Constraint record — see `ConstraintMutationRecord`. */
export interface WireMutationRecord {
  readonly constraintId: string;
  readonly lifecycleState: string;
  readonly version: number;
  readonly projectId: string | null;
  readonly categoryId: string | null;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
  readonly reference: string | null;
  readonly currentUpdate: string | null;
  readonly bic: readonly WireMutationParty[];
  readonly responsible: readonly WireMutationParty[];
  readonly completionDate: string | null;
  readonly closureCommentary: string | null;
  readonly voidedDate: string | null;
  readonly voidReason: string | null;
  readonly recordQuality: string;
  readonly publishedAt: string | null;
}

export interface WireMutationReceipt {
  readonly historyId: string;
  readonly constraintId: string;
  readonly operation: string;
  readonly actor: string;
  readonly outcome: string;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly safeFailureReason: string | null;
}

/** `{disposition, constraint, receipt}` — the eight single-record Constraint capabilities. */
export interface ConstraintMutationAnswer {
  readonly disposition: "applied" | "no_op" | "replayed";
  readonly constraint: WireMutationRecord;
  readonly receipt: WireMutationReceipt;
}

/** Close + Follow-up: both records, both receipts, and the relationship between them. */
export interface ConstraintFollowUpAnswer {
  readonly disposition: "applied" | "replayed";
  readonly predecessor: WireMutationRecord;
  readonly successor: WireMutationRecord;
  readonly predecessorReceipt: WireMutationReceipt;
  readonly successorReceipt: WireMutationReceipt;
  readonly relationshipId: string;
}

export interface WireCategoryMutationRecord {
  readonly categoryId: string;
  readonly projectId: string;
  readonly prefix: string;
  readonly title: string;
  readonly state: string;
  readonly description: string | null;
  readonly displayOrder: number;
  readonly prefixLockedAt: string | null;
}

export interface WireCategoryMutationReceipt {
  readonly historyId: string;
  readonly projectId: string;
  readonly categoryId: string;
  readonly operation: string;
  readonly actor: string;
  readonly outcome: string;
  readonly beforeVersion: number;
  readonly afterVersion: number;
  readonly occurredAt: string;
  readonly safeFailureReason: string | null;
}

/** `{disposition, category, receipt}` — the three single-Category capabilities. */
export interface ConstraintCategoryMutationAnswer {
  readonly disposition: "applied" | "no_op" | "replayed";
  readonly category: WireCategoryMutationRecord & { readonly version: number };
  readonly receipt: WireCategoryMutationReceipt;
}

/** One atomic reorder: the whole Project's Category scheme in its new order. */
export interface ConstraintCategoryReorderAnswer {
  readonly disposition: "applied" | "replayed";
  readonly categories: readonly WireCategoryMutationRecord[];
  readonly receipts: readonly WireCategoryMutationReceipt[];
}

const categoriesRoot = (projectId: string) =>
  `/api/project-controls/projects/${encodeURIComponent(projectId)}/constraint-categories`;

/** `POST …/constraints/drafts` — `constraints.create`. */
export function createDraft(projectId: string, body: Record<string, unknown>, signal?: AbortSignal) {
  return write<ConstraintMutationAnswer>("POST", `${root(projectId)}/constraints/drafts`, body, signal);
}

/** `POST …/constraints` — `constraints.create_published`, the one atomic create-and-publish intent. */
export function createPublished(projectId: string, body: Record<string, unknown>, signal?: AbortSignal) {
  return write<ConstraintMutationAnswer>("POST", `${root(projectId)}/constraints`, body, signal);
}

/** `PATCH …/constraints/[id]` — `constraints.update`. */
export function updateConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "PATCH",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/publish` — `constraints.publish`. */
export function publishConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/publish`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/transition` — `constraints.transition`. */
export function transitionConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/transition`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/close` — `constraints.close`. Never optimistic. */
export function closeConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/close`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/close-follow-up` — `constraints.close_follow_up`. Never optimistic. */
export function closeFollowUpConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintFollowUpAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/close-follow-up`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/void` — `constraints.void`. Never optimistic. */
export function voidConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/void`,
    body,
    signal,
  );
}

/** `POST …/constraints/[id]/reopen` — `constraints.reopen`. */
export function reopenConstraint(
  projectId: string,
  constraintId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintMutationAnswer>(
    "POST",
    `${root(projectId)}/constraints/${encodeURIComponent(constraintId)}/reopen`,
    body,
    signal,
  );
}

/** `POST …/constraint-categories` — `constraint_categories.create`. */
export function createCategory(projectId: string, body: Record<string, unknown>, signal?: AbortSignal) {
  return write<ConstraintCategoryMutationAnswer>("POST", categoriesRoot(projectId), body, signal);
}

/** `PATCH …/constraint-categories/[id]` — `constraint_categories.update`. */
export function updateCategory(
  projectId: string,
  categoryId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintCategoryMutationAnswer>(
    "PATCH",
    `${categoriesRoot(projectId)}/${encodeURIComponent(categoryId)}`,
    body,
    signal,
  );
}

/** `POST …/constraint-categories/[id]/deactivate` — `constraint_categories.deactivate`. */
export function deactivateCategory(
  projectId: string,
  categoryId: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return write<ConstraintCategoryMutationAnswer>(
    "POST",
    `${categoriesRoot(projectId)}/${encodeURIComponent(categoryId)}/deactivate`,
    body,
    signal,
  );
}

/** `POST …/constraint-categories/reorder` — `constraint_categories.reorder`. One atomic write. */
export function reorderCategories(projectId: string, body: Record<string, unknown>, signal?: AbortSignal) {
  return write<ConstraintCategoryReorderAnswer>("POST", `${categoriesRoot(projectId)}/reorder`, body, signal);
}
