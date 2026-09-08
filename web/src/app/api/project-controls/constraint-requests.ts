/**
 * The closed request vocabulary the Constraint read routes admit.
 *
 * Two rules make this file rather than inline literals the mechanism:
 *
 * 1. **Nothing arbitrary reaches the gateway.** Each map below is the whole set
 *    of query names a route accepts, and `workGet` refuses any other name with
 *    `400 invalid_request` before a request is built. No `URLSearchParams` is
 *    forwarded, and no value outside a backend command's own closed vocabulary
 *    is admitted — the vocabularies here are transcriptions of
 *    `my_pa.domain.project_controls.read_models` and `my_pa.application.commands`,
 *    not a second opinion about them.
 * 2. **The camelCase→snake_case translation is explicit and per field.** There
 *    is no recursive case converter in this repository and none is added: a
 *    converter admits whatever it is handed, which is the opposite of a closed
 *    allowlist. Note `sort_order` rather than `direction` — the command
 *    deliberately carries that name.
 *
 * Nothing here recomputes `overdue`, `dueSoon`, `inMyCourt`, a recent window, a
 * grouping or a business-day figure. Those are filter *inputs* travelling to the
 * read plane, and they come back as backend-derived facts.
 */
import { NextResponse } from "next/server";
import type { WorkField } from "@/lib/api/work-route";

/** `IdKind.PROJECT` shape, mirrored by the database CHECK on the Project table. */
const PROJECT_ID = /^prj_[A-Za-z0-9]{8,64}$/;

/** `IdKind.PROJECT_CONSTRAINT` shape. */
const CONSTRAINT_ID = /^cst_[A-Za-z0-9]{8,64}$/;

export function isProjectId(value: string): boolean {
  return PROJECT_ID.test(value);
}

export function isConstraintId(value: string): boolean {
  return CONSTRAINT_ID.test(value);
}

/** `ConstraintListScope`. */
export const LIST_SCOPES = ["open", "closed", "all", "draft"] as const;

/** `ConstraintLifecycleState`. `reopen` is an operation, not a state. */
export const LIFECYCLE_STATES = [
  "draft",
  "identified",
  "pending",
  "in_progress",
  "on_hold",
  "closed",
  "void",
] as const;

/** `ConstraintSyncStateView` — the four a read of persisted rows can establish. */
export const SYNC_STATES = ["never_synced", "in_sync", "db_export_pending", "conflict"] as const;

/** `ConstraintRecordQuality`. */
export const RECORD_QUALITIES = ["normal", "legacy_incomplete"] as const;

/** `ConstraintRecentFilter`. */
export const RECENT_FILTERS = ["recently_changed", "recently_closed"] as const;

/** `ConstraintSort`. */
export const SORTS = [
  "code",
  "date_identified",
  "days_elapsed",
  "due_date",
  "updated_at",
] as const;

/** `SortDirection`. */
export const SORT_DIRECTIONS = ["asc", "desc"] as const;

/** `ConstraintGrouping`. */
export const GROUPINGS = ["none", "category", "status", "bic", "responsible"] as const;

/** `ConstraintCategoryState`. */
export const CATEGORY_STATES = ["active", "inactive", "archived"] as const;

/** The full Register allowlist, from `ListConstraints`. */
export const REGISTER_FIELDS: Readonly<Record<string, WorkField>> = {
  scope: { gateway: "scope", type: "string", values: LIST_SCOPES },
  status: { gateway: "statuses", type: "string-array", values: LIFECYCLE_STATES, maxItems: 7 },
  category: { gateway: "category_ids", type: "string-array", maxItems: 32 },
  bic: { gateway: "bic_party_refs", type: "string-array", maxItems: 32 },
  responsible: { gateway: "responsible_party_refs", type: "string-array", maxItems: 32 },
  sync: { gateway: "sync_states", type: "string-array", values: SYNC_STATES, maxItems: 4 },
  quality: {
    gateway: "record_qualities",
    type: "string-array",
    values: RECORD_QUALITIES,
    maxItems: 2,
  },
  overdue: { gateway: "overdue", type: "boolean" },
  dueSoon: { gateway: "due_soon", type: "boolean" },
  inMyCourt: { gateway: "my_court", type: "boolean" },
  needsAttention: { gateway: "needs_attention", type: "boolean" },
  recent: { gateway: "recent", type: "string", values: RECENT_FILTERS },
  sort: { gateway: "sort", type: "string", values: SORTS },
  dir: { gateway: "sort_order", type: "string", values: SORT_DIRECTIONS },
  group: { gateway: "grouping", type: "string", values: GROUPINGS },
  pageSize: { gateway: "limit", type: "integer" },
  cursor: { gateway: "cursor", type: "string" },
} as const;

/**
 * The narrower search allowlist, from `SearchConstraints`.
 *
 * Deliberately *not* the Register map plus `q`. `SearchConstraints` accepts
 * `project_id, query, scope, limit, cursor` and nothing else, so a filter, a
 * sort or a grouping supplied alongside a term is refused as an unknown field
 * rather than silently dropped — a dropped filter would return a wider page
 * than the caller asked for and look like an answer.
 */
export const SEARCH_FIELDS: Readonly<Record<string, WorkField>> = {
  q: { gateway: "query", type: "string" },
  scope: { gateway: "scope", type: "string", values: LIST_SCOPES },
  pageSize: { gateway: "limit", type: "integer" },
  cursor: { gateway: "cursor", type: "string" },
} as const;

/** `ReadConstraintHistory`: a page size and an opaque cursor. */
export const HISTORY_FIELDS: Readonly<Record<string, WorkField>> = {
  pageSize: { gateway: "page_size", type: "integer" },
  cursor: { gateway: "cursor", type: "string" },
} as const;

/** `ListConstraintCategories`: one closed state filter and nothing else. */
export const CATEGORY_FIELDS: Readonly<Record<string, WorkField>> = {
  state: { gateway: "states", type: "string-array", values: CATEGORY_STATES, maxItems: 3 },
} as const;

/** `ReadConstraintOverview` and `ReadConstraint` take no query at all. */
export const NO_FIELDS: Readonly<Record<string, WorkField>> = {} as const;

/**
 * The refusal for a path segment that is not the identifier kind it must be.
 *
 * Answered before any gateway call: an id of the wrong kind is a malformed
 * request, and sending it onward would spend a capability invocation to learn
 * something the shape already says. Nothing about the rejected value is echoed,
 * and `private, no-store` is set here because this response never reaches
 * `workGet`, which is what sets it for every other answer these routes give.
 */
export function invalidPathIdentifier(field: string): NextResponse {
  const response = NextResponse.json(
    {
      error: {
        errorClass: "validation",
        code: "invalid_request",
        message: `${field} is not a well-formed identifier`,
      },
    },
    { status: 400 },
  );
  response.headers.set("cache-control", "private, no-store");
  return response;
}
