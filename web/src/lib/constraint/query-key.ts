/**
 * Canonical Constraint query identity — R02-WP10 Phase 4.
 *
 * This is a fresh design for the Constraint runtime, not a port of
 * `@/lib/task/query-key.ts`. It exists for the same reason that module does
 * (stable, comparable query identity two components can share) but encodes a
 * different shape: every Constraint query is additionally bound to the
 * current Project scope (`ALL_PROJECTS` or one exact Project) and to the
 * Project-scope epoch (`useProjectScope().epoch`), because a scope or epoch
 * change must always produce a genuinely different key — never a stale one
 * silently reused. See `read-coordinator.ts` for how the epoch travels
 * further, into per-request staleness suppression.
 *
 * Browser-selected Principal is never part of a key — Principal is
 * server-derived. `sessionKey` is an internal client isolation token only
 * (mirrors `TaskRuntimeProvider`'s `principalId::sessionEpoch` session key),
 * never an API credential or parameter.
 */

export const CONSTRAINT_QUERY_RESOURCE = "constraints" as const;

/**
 * `portfolio` — cross-Project overview reads.
 * `list` / `search` — Register-shaped paged/filtered reads.
 * `overview` — a summary/aggregate read for the active scope.
 * `detail` — one canonical Constraint.
 * `category` — either the Category collection for a Project (no `categoryId`)
 * or one canonical Category record (`categoryId` set).
 */
export const CONSTRAINT_QUERY_MODES = [
  "portfolio",
  "list",
  "search",
  "overview",
  "detail",
  "category",
] as const;
export type ConstraintQueryMode = (typeof CONSTRAINT_QUERY_MODES)[number];

export type ConstraintQueryScopeInput =
  | { readonly kind: "ALL_PROJECTS" }
  | { readonly kind: "PROJECT"; readonly projectId: string };

export type ConstraintQueryScope =
  | { readonly kind: "ALL_PROJECTS" }
  | { readonly kind: "PROJECT"; readonly projectId: string };

/**
 * Input fields for a Constraint query. Undefined / null / empty optional
 * strings normalize identically so callers need not agree on which sentinel
 * they use.
 */
export interface ConstraintQueryKeyInput {
  readonly mode: ConstraintQueryMode;
  readonly scope: ConstraintQueryScopeInput;
  readonly q?: string | null;
  readonly status?: string | null;
  readonly cursor?: string | null;
  readonly page?: string | number | null;
  readonly constraintId?: string | null;
  readonly categoryId?: string | null;
  /** Opaque session identity, e.g. `${principalId}::${sessionEpoch}`. */
  readonly sessionKey: string;
  /** `useProjectScope().epoch` captured at key-construction time. */
  readonly scopeEpoch: number;
}

/**
 * Stable, comparable Constraint query identity. Field order is fixed; values
 * are normalized. Do not reconstruct this by hand — use
 * {@link buildConstraintQueryKey}.
 */
export interface ConstraintQueryKey {
  readonly resource: typeof CONSTRAINT_QUERY_RESOURCE;
  readonly mode: ConstraintQueryMode;
  readonly scopeKind: ConstraintQueryScope["kind"];
  readonly projectId: string | null;
  readonly q: string | null;
  readonly status: string | null;
  readonly cursor: string | null;
  readonly page: string | null;
  readonly constraintId: string | null;
  readonly categoryId: string | null;
  readonly sessionKey: string;
  readonly scopeEpoch: number;
}

function normalizeOptionalString(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function normalizePage(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return String(Math.trunc(value));
  }
  return normalizeOptionalString(value);
}

function normalizeSessionKey(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new TypeError("sessionKey must be a non-empty string");
  }
  return trimmed;
}

function normalizeScopeEpoch(value: number): number {
  if (!Number.isFinite(value)) {
    throw new TypeError("scopeEpoch must be a finite number");
  }
  return Math.trunc(value);
}

/** Build the canonical Constraint query key from semantic inputs. */
export function buildConstraintQueryKey(input: ConstraintQueryKeyInput): ConstraintQueryKey {
  if (!CONSTRAINT_QUERY_MODES.includes(input.mode)) {
    throw new TypeError(`unsupported Constraint query mode: ${String(input.mode)}`);
  }
  const constraintId = normalizeOptionalString(input.constraintId);
  if (input.mode === "detail" && constraintId === null) {
    throw new TypeError("constraintId is required for Constraint query mode \"detail\"");
  }
  const projectId =
    input.scope.kind === "PROJECT" ? normalizeOptionalString(input.scope.projectId) : null;
  if (input.scope.kind === "PROJECT" && projectId === null) {
    throw new TypeError("projectId is required when scope.kind is \"PROJECT\"");
  }
  return {
    resource: CONSTRAINT_QUERY_RESOURCE,
    mode: input.mode,
    scopeKind: input.scope.kind,
    projectId,
    q: normalizeOptionalString(input.q),
    status: normalizeOptionalString(input.status),
    cursor: normalizeOptionalString(input.cursor),
    page: normalizePage(input.page),
    constraintId,
    categoryId: normalizeOptionalString(input.categoryId),
    sessionKey: normalizeSessionKey(input.sessionKey),
    scopeEpoch: normalizeScopeEpoch(input.scopeEpoch),
  };
}

const KEY_FIELD_ORDER = [
  "resource",
  "mode",
  "scopeKind",
  "projectId",
  "q",
  "status",
  "cursor",
  "page",
  "constraintId",
  "categoryId",
  "sessionKey",
  "scopeEpoch",
] as const satisfies ReadonlyArray<keyof ConstraintQueryKey>;

/** Deterministic map / wire identity for a canonical key. */
export function serializeConstraintQueryKey(key: ConstraintQueryKey): string {
  return JSON.stringify(KEY_FIELD_ORDER.map((field) => key[field]));
}

/** Structural equality of two canonical keys. */
export function constraintQueryKeysEqual(a: ConstraintQueryKey, b: ConstraintQueryKey): boolean {
  return serializeConstraintQueryKey(a) === serializeConstraintQueryKey(b);
}

/** Build the opaque session identity `buildConstraintQueryKey` expects. */
export function buildConstraintSessionKey(principalId: string, sessionEpoch: string): string {
  const principal = normalizeOptionalString(principalId);
  const session = normalizeOptionalString(sessionEpoch);
  if (!principal || !session) {
    throw new TypeError("principalId and sessionEpoch must be non-empty strings");
  }
  return `${principal}::${session}`;
}
