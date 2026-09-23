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

/** `IdKind.CONSTRAINT_CATEGORY` shape. */
const CATEGORY_ID = /^ccat_[A-Za-z0-9]{8,64}$/;

export function isProjectId(value: string): boolean {
  return PROJECT_ID.test(value);
}

export function isConstraintId(value: string): boolean {
  return CONSTRAINT_ID.test(value);
}

export function isCategoryId(value: string): boolean {
  return CATEGORY_ID.test(value);
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

/**
 * The portfolio Register allowlist, from `ListPortfolioConstraints`.
 *
 * `REGISTER_FIELDS` minus every Project field, and that subtraction is the
 * security property rather than a tidy-up. A portfolio read derives its Project
 * set server-side from the Principal; admitting a caller-supplied Project
 * identifier here would let a caller ask "does this Project answer for me?" and
 * read ownership off the difference between the answers, which is the existence
 * oracle the nondisclosure rule forbids. There is no `project` browser name and
 * no `project_id` gateway name in this map, so either spelling is refused as an
 * unknown field before a capability is spent.
 */
export const PORTFOLIO_REGISTER_FIELDS: Readonly<Record<string, WorkField>> = {
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
 * The narrower portfolio search allowlist, from `SearchPortfolioConstraints`.
 *
 * `SEARCH_FIELDS` minus the Project, for both reasons the two maps above give:
 * a filter, sort or grouping supplied with a term is refused rather than
 * dropped, and no Project identifier is admitted from the browser at all.
 */
export const PORTFOLIO_SEARCH_FIELDS: Readonly<Record<string, WorkField>> = {
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

/**
 * `ReadConstraintOverview`, `ReadConstraint`, `ReadProjectControlsStatus` and
 * `ReadPortfolioConstraintOverview` take no query at all.
 */
export const NO_FIELDS: Readonly<Record<string, WorkField>> = {} as const;

/**
 * `ConfigureProjectControls`: the only write vocabulary in this family.
 *
 * Three names, and deliberately not six. `ConfigureProjectControls` also
 * accepts `client_context` and `correlation_id`, and both are omitted here
 * because the accepted BFF plan admits only
 * `{timezoneName, idempotencyKey, expectedVersion?}` from the browser. A field
 * absent from this map is refused as an unknown field by the shared work-route
 * body mapper, so the omission is enforcement rather than an oversight: a
 * browser cannot label its own request for the server's telemetry, and a
 * correlation identifier the
 * caller chose is not one this transport is willing to attribute to a Principal.
 *
 * `project_id` is not here either, and cannot be. It is fixed from the route
 * segment, so a body naming a *different* Project is an unknown field and a
 * `400` — the URL and the body cannot disagree, because only one of them is
 * ever consulted.
 *
 * `idempotencyKey` is required by the backend command rather than optional as
 * it is on every other Constraint-plane write; the gateway refuses a request
 * without one, and nothing here supplies a default. A key this layer invented
 * would make replay protection depend on the transport rather than the caller.
 *
 * `expectedVersion` is an integer and genuinely optional: a Project nobody has
 * configured has no version to expect, and omitting the field is how a caller
 * says "I believe there is nothing here yet".
 *
 * No timezone vocabulary is transcribed. The IANA zone set is `zoneinfo`'s
 * answer, it is not closed, and a copy of it here would be a second opinion
 * that drifts — `timezoneName` is admitted as a string and validated by the
 * domain before anything is written.
 */
export const SETTINGS_FIELDS: Readonly<Record<string, WorkField>> = {
  timezoneName: { gateway: "timezone_name", type: "string" },
  idempotencyKey: { gateway: "idempotency_key", type: "string" },
  expectedVersion: { gateway: "expected_version", type: "integer" },
} as const;

function notFound(message: string): NextResponse {
  const response = NextResponse.json(
    { error: { errorClass: "not_found", code: "not_found", message } },
    { status: 404 },
  );
  response.headers.set("cache-control", "private, no-store");
  return response;
}

/**
 * The one nondisclosing answer for a Constraint that is not in the URL's Project.
 *
 * Defined once and imported by every route that binds a Constraint to its path
 * Project — the detail and history reads and the exact-Project mutation
 * preflight — so "belongs to another of your Projects" has exactly one shape,
 * byte for byte, wherever it is asked. `private, no-store` is set here because
 * this response is built outside the shared work-route helpers.
 */
export function constraintNotFound(): NextResponse {
  return notFound("Constraint was not found");
}

/** The same answer for a Category that is not in the URL's Project. */
export function categoryNotFound(): NextResponse {
  return notFound("Category was not found");
}

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

// --- R01-WP09: Constraint and Category authoring vocabularies ----------------
//
// The browser half of the thirteen `constraint_authoring` capabilities. Each map
// below is artifact 17 §5's "browser body fields" column for one route and
// nothing more, translated field by field to the gateway spelling artifact 17 §7
// fixes. Four things are deliberately absent from every one of them:
//
// - the Project. It is fixed from the route segment (create, create-published,
//   category create, reorder) or bound by the exact-Project preflight (every
//   existing-record route), so a body naming one is an unknown field and a 400;
// - the record identity (`constraint_id`, `category_id` of the record being
//   changed), which is always the path segment's;
// - `client_context` and `correlation_id`, which a browser may not choose for
//   the server's telemetry, exactly as `SETTINGS_FIELDS` explains;
// - any Principal field, which `readCleanBody` refuses before a map is read.
//
// `constraints.update` in particular does **not** carry `project_id` (plan D6):
// `UpdateConstraint.project_id` is "move to this Project", `None` is "no
// move", and forwarding the URL Project would make every update a same-Project
// move with a different request digest.

/**
 * The active lifecycle states: the only targets Publish, create-published,
 * Transition, Reopen and a follow-up successor can legally name.
 *
 * `ACTIVE_CONSTRAINT_LIFECYCLE_STATES`, verbatim. The commands themselves type
 * the field as any `ConstraintLifecycleState`; `check_lifecycle_move` then
 * refuses every non-active target for those four operations (Transition's only
 * other acceptance is a same-state no-op on a Draft or terminal record, which
 * no authoring surface asks for). Closing the vocabulary here refuses a
 * `draft`/`closed`/`void` target without a round trip; *which* active state a
 * given record may move to is still the backend's graph and is not restated.
 */
export const CONSTRAINT_ACTIVE_TARGET_STATES = [
  "identified",
  "pending",
  "in_progress",
  "on_hold",
] as const;

/** `ConstraintUpdateField`, verbatim: every name the backend lets an update touch. */
export const CONSTRAINT_UPDATABLE_FIELDS = [
  "description",
  "date_identified",
  "due_date",
  "reference",
  "current_update",
  "bic",
  "responsible",
  "project_id",
  "category_id",
] as const;

/**
 * The `clearFields` a browser may name: `ConstraintUpdateField` minus
 * `project_id`.
 *
 * Clearing `project_id` on a Draft detaches it from its Project, which is a
 * Project move by another name, and no Project move is browser-reachable
 * (artifact 17 §5; plan D6). Every other member is transcribed unchanged, and
 * which of them a *published* record may clear is still the service's
 * `DRAFT_ONLY_FIELDS`/`PUBLISH_REQUIRED_FIELDS` decision.
 */
export const CONSTRAINT_CLEARABLE_FIELDS = CONSTRAINT_UPDATABLE_FIELDS.filter(
  (name) => name !== "project_id",
);

/** `CreateConstraintCategory.state` is a `ConstraintCategoryState`. */
export const CATEGORY_CREATE_STATES = CATEGORY_STATES;

/** At most this many parties in one BIC or Responsible array (artifact 17 §8). */
const MAX_PARTIES = 32;

/** At most this many Categories in one reorder (artifact 17 §8). */
const MAX_REORDER = 64;

/**
 * The transport ceiling on a caller's idempotency key. The backend owns the
 * exact `^[A-Za-z0-9_-]{8,128}$` shape; nothing here supplies a default.
 */
const IDEMPOTENCY_KEY: WorkField = {
  gateway: "idempotency_key",
  type: "string",
  maxLength: 128,
};

const EXPECTED_VERSION: WorkField = { gateway: "expected_version", type: "integer", minimum: 0 };
const DISPLAY_ORDER: WorkField = { gateway: "display_order", type: "integer", minimum: 0 };

function parties(gateway: string): WorkField {
  return { gateway, type: "party-ref-array", maxItems: MAX_PARTIES };
}

function activeTarget(gateway: string): WorkField {
  return { gateway, type: "string", values: CONSTRAINT_ACTIVE_TARGET_STATES };
}

/** The authoring fields a Draft and a created-published Constraint share. */
const AUTHORED_FIELDS: Readonly<Record<string, WorkField>> = {
  categoryId: { gateway: "category_id", type: "string" },
  description: { gateway: "description", type: "string" },
  dateIdentified: { gateway: "date_identified", type: "string" },
  dueDate: { gateway: "due_date", type: "string" },
  reference: { gateway: "reference", type: "string" },
  currentUpdate: { gateway: "current_update", type: "string" },
  bic: parties("bic"),
  responsible: parties("responsible"),
};

/** `CreateConstraintDraft`, minus the path Project and the telemetry pair. */
export const CONSTRAINT_CREATE_DRAFT_FIELDS: Readonly<Record<string, WorkField>> = {
  ...AUTHORED_FIELDS,
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `CreatePublishedConstraint`: the Draft fields plus an optional active target. */
export const CONSTRAINT_CREATE_PUBLISHED_FIELDS: Readonly<Record<string, WorkField>> = {
  ...AUTHORED_FIELDS,
  toState: activeTarget("to_state"),
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `UpdateConstraint`, minus the path identity, `project_id` (D6) and telemetry. */
export const CONSTRAINT_UPDATE_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  ...AUTHORED_FIELDS,
  clearFields: {
    gateway: "clear_fields",
    type: "string-array",
    values: CONSTRAINT_CLEARABLE_FIELDS,
    maxItems: CONSTRAINT_CLEARABLE_FIELDS.length,
  },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `PublishConstraint`. */
export const CONSTRAINT_PUBLISH_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  toState: activeTarget("to_state"),
  categoryId: { gateway: "category_id", type: "string" },
  dateIdentified: { gateway: "date_identified", type: "string" },
  dueDate: { gateway: "due_date", type: "string" },
  bic: parties("bic"),
  responsible: parties("responsible"),
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `TransitionConstraint`. */
export const CONSTRAINT_TRANSITION_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  toState: activeTarget("to_state"),
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `CloseConstraint`. */
export const CONSTRAINT_CLOSE_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  completionDate: { gateway: "completion_date", type: "string" },
  closureCommentary: { gateway: "closure_commentary", type: "string" },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `CloseConstraintWithFollowUp`. The successor's Project is inherited backend-side. */
export const CONSTRAINT_CLOSE_FOLLOW_UP_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  successorDescription: { gateway: "successor_description", type: "string" },
  completionDate: { gateway: "completion_date", type: "string" },
  closureCommentary: { gateway: "closure_commentary", type: "string" },
  successorCategoryId: { gateway: "successor_category_id", type: "string" },
  successorDueDate: { gateway: "successor_due_date", type: "string" },
  successorState: activeTarget("successor_state"),
  successorBic: parties("successor_bic"),
  successorResponsible: parties("successor_responsible"),
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `VoidConstraint`. */
export const CONSTRAINT_VOID_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  voidReason: { gateway: "void_reason", type: "string" },
  voidedDate: { gateway: "voided_date", type: "string" },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `ReopenConstraint`. */
export const CONSTRAINT_REOPEN_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  toState: activeTarget("to_state"),
  reason: { gateway: "reason", type: "string" },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/**
 * `CreateConstraintCategory`. The browser says `prefix`, the gateway
 * `code_segment` — the command's own rename, for the reason `commands.py`
 * gives above `ConstraintUpdateField`.
 */
export const CATEGORY_CREATE_FIELDS: Readonly<Record<string, WorkField>> = {
  prefix: { gateway: "code_segment", type: "string" },
  title: { gateway: "title", type: "string" },
  description: { gateway: "description", type: "string" },
  displayOrder: DISPLAY_ORDER,
  state: { gateway: "state", type: "string", values: CATEGORY_CREATE_STATES },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `UpdateConstraintCategory`. State is not settable here; deactivation is its own route. */
export const CATEGORY_UPDATE_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  prefix: { gateway: "code_segment", type: "string" },
  title: { gateway: "title", type: "string" },
  description: { gateway: "description", type: "string" },
  displayOrder: DISPLAY_ORDER,
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `DeactivateConstraintCategory`. */
export const CATEGORY_DEACTIVATE_FIELDS: Readonly<Record<string, WorkField>> = {
  expectedVersion: EXPECTED_VERSION,
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/** `ReorderConstraintCategories`: two parallel arrays, checked together below. */
export const CATEGORY_REORDER_FIELDS: Readonly<Record<string, WorkField>> = {
  orderedCategoryIds: { gateway: "ordered_category_ids", type: "string-array", maxItems: MAX_REORDER },
  expectedVersions: { gateway: "expected_versions", type: "integer-array", maxItems: MAX_REORDER },
  idempotencyKey: IDEMPOTENCY_KEY,
} as const;

/**
 * The reorder rules no single field can state, run over the mapped payload.
 *
 * Both arrays are required and non-empty, every id is a Category id, no id
 * repeats, and the version list is exactly as long as the id list — the
 * `ReorderConstraintCategories.__post_init__` shape checks, refused here so the
 * message names the browser field. Whether the ids are the Project's *complete*
 * active set, and whether each version is current, is the backend's and only
 * the backend's to decide.
 */
export function validateCategoryReorder(payload: Readonly<Record<string, unknown>>): string | null {
  const ids = payload.ordered_category_ids;
  const versions = payload.expected_versions;
  if (!Array.isArray(ids) || ids.length < 1) {
    return "orderedCategoryIds must name at least one category";
  }
  if (!ids.every((id) => typeof id === "string" && isCategoryId(id))) {
    return "orderedCategoryIds must contain only category identifiers";
  }
  if (new Set(ids).size !== ids.length) {
    return "orderedCategoryIds must not repeat a category";
  }
  if (!Array.isArray(versions) || versions.length !== ids.length) {
    return "expectedVersions must have one version per orderedCategoryIds entry";
  }
  return null;
}
