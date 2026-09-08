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
