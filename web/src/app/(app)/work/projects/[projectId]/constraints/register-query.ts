/**
 * Evaluating a Register query against the synthetic corpus.
 *
 * **This is a stand-in for the backend's query, not a second copy of the
 * backend's judgement, and the difference is the point.** Everything here
 * *reads* fields the backend already decided — `isOverdue`, `isDueSoon`,
 * `inMyCourt`, `needsAttention`, `recordQuality`, `syncState`, `status`,
 * `groupKeys` — and selects, orders and bounds rows by them. Nothing here
 * derives one. There is no `Date` in this file, no arithmetic on `dueDate`, and
 * no comparison of a party label to a person: a browser that computed urgency
 * would produce a second answer that could disagree with the Overview's counts,
 * and the reader would have no way to know which one they were looking at
 * (`CM-FE-AC-033`, `034`, `035`, `036`).
 *
 * When the BFF read plane lands, this module is what a request replaces. Its
 * signature is deliberately request-shaped — a query in, one bounded page out,
 * with a cursor — so that replacement is a substitution rather than a redesign.
 *
 * **Constraint Code is text, everywhere in here.** Ordering compares code units
 * directly. `"1.10"` sorts before `"1.2"` because `'1' < '2'`, which is what a
 * project-local textual Code means and is exactly what a numeric parse would
 * get wrong (`CM-FE-AC-025`). There is no `parseFloat` in this file and there
 * must never be one.
 */
import type { ConstraintListEntry, ConstraintListPage } from "@/contracts/constraints";
import { UNRESOLVED_PARTY_FILTER_BUCKET } from "@/contracts/constraints";
import type { ConstraintUrlState } from "./constraint-url-state";

/** The bounded first page, and the size of each continuation. */
export const REGISTER_PAGE_SIZE = 50;

/** The lifecycle states each scope admits, as a lookup and not a computation. */
const SCOPE_MEMBERSHIP: Readonly<Record<ConstraintUrlState["scope"], readonly string[] | null>> = {
  open: ["IDENTIFIED", "PENDING", "IN_PROGRESS", "ON_HOLD"],
  closed: ["CLOSED", "VOID"],
  draft: ["DRAFT"],
  // `all` applies no lifecycle predicate at all; Project and paging still bound it.
  all: null,
};

function matchesParty(
  parties: readonly ConstraintListEntry["bic"][number][],
  filter: string,
): boolean {
  if (filter === UNRESOLVED_PARTY_FILTER_BUCKET) {
    // The bucket is evaluated by kind, never by label: an unresolved party has
    // no stable reference, so matching its wording would be string identity.
    return parties.some((party) => party.kind === "UNRESOLVED");
  }
  return parties.some((party) => party.partyRefId === filter);
}

/**
 * Search, over the fields the backend contract says are searched.
 *
 * Code, Description and Reference. Not "everything that happens to be a string
 * on the row": promising a field the backend does not search would make the
 * Register's answer and a live answer differ silently.
 */
function matchesSearch(entry: ConstraintListEntry, needle: string): boolean {
  const term = needle.trim().toLowerCase();
  if (term.length === 0) return true;
  const haystacks = [entry.constraintCode, entry.description, entry.reference];
  return haystacks.some((value) => value !== null && value.toLowerCase().includes(term));
}

/** Every row the query admits, before ordering and before bounding. */
export function filterRegisterEntries(
  entries: readonly ConstraintListEntry[],
  state: ConstraintUrlState,
  projectId: string,
): readonly ConstraintListEntry[] {
  const scopeStates = SCOPE_MEMBERSHIP[state.scope];
  return entries.filter((entry) => {
    // Project is route identity and is the first predicate, not the last: no
    // page of one Project may ever carry a row of another (`CM-FE-AC-028`).
    if (entry.projectId !== projectId) return false;
    if (scopeStates !== null) {
      if (entry.status === null || !scopeStates.includes(entry.status)) return false;
    }
    if (state.status !== null && entry.status !== state.status) return false;
    if (state.categoryId !== null && entry.category?.categoryId !== state.categoryId) return false;
    if (state.bic !== null && !matchesParty(entry.bic, state.bic)) return false;
    if (state.responsible !== null && !matchesParty(entry.responsible, state.responsible)) {
      return false;
    }
    if (state.overdue && !entry.isOverdue) return false;
    if (state.dueSoon && !entry.isDueSoon) return false;
    if (state.inMyCourt && !entry.inMyCourt) return false;
    if (state.needsAttention && !entry.needsAttention) return false;
    if (state.sync !== null && entry.syncState !== state.sync) return false;
    return matchesSearch(entry, state.search);
  });
}

/** Nulls sort last in both directions: an absent value is not a small one. */
function compareNullable(
  left: string | number | null,
  right: string | number | null,
): number {
  if (left === right) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return left < right ? -1 : 1;
}

function sortValue(entry: ConstraintListEntry, sort: ConstraintUrlState["sort"]) {
  switch (sort) {
    case "code":
      // Code units, not numbers. See the module note.
      return entry.constraintCode;
    case "dateIdentified":
      return entry.dateIdentified;
    case "daysOpen":
      return entry.daysElapsed;
    case "due":
      return entry.dueDate;
    case "updated":
      return entry.updatedAt;
  }
}

/**
 * One total order over the admitted rows.
 *
 * The tiebreak on `constraintId` is what makes continuation safe: without a
 * total order, two rows with equal sort values could swap between pages and a
 * reader would see one of them twice and the other never.
 */
export function sortRegisterEntries(
  entries: readonly ConstraintListEntry[],
  state: ConstraintUrlState,
): readonly ConstraintListEntry[] {
  const direction = state.dir === "asc" ? 1 : -1;
  return [...entries].sort((left, right) => {
    const primary = compareNullable(sortValue(left, state.sort), sortValue(right, state.sort));
    if (primary !== 0) return primary * direction;
    return left.constraintId < right.constraintId ? -1 : 1;
  });
}

/**
 * One bounded page, continued from a cursor.
 *
 * The cursor is the identity of the last row already delivered. Resolving it
 * against the same total order and taking what follows means a continuation can
 * neither repeat a row nor skip one. A cursor that no longer resolves — the row
 * was filtered out by a changed query — starts again from the beginning rather
 * than silently returning nothing.
 */
export function queryRegisterPage(
  entries: readonly ConstraintListEntry[],
  state: ConstraintUrlState,
  projectId: string,
  cursor: string | null,
): ConstraintListPage {
  const ordered = sortRegisterEntries(filterRegisterEntries(entries, state, projectId), state);
  const from =
    cursor === null
      ? 0
      : (() => {
          const at = ordered.findIndex((entry) => entry.constraintId === cursor);
          return at === -1 ? 0 : at + 1;
        })();
  const slice = ordered.slice(from, from + REGISTER_PAGE_SIZE);
  const delivered = from + slice.length;
  return {
    entries: slice,
    isTruncated: delivered < ordered.length,
    nextCursor:
      delivered < ordered.length && slice.length > 0
        ? slice[slice.length - 1].constraintId
        : null,
    // The backend supplies the total for this query. It is not the number of
    // rows loaded so far, and the two are shown as different things.
    totalCount: ordered.length,
  };
}

export interface RegisterGroup {
  readonly key: string;
  readonly label: string;
  readonly entries: readonly ConstraintListEntry[];
}

const STATUS_GROUP_ORDER: readonly string[] = [
  "DRAFT",
  "IDENTIFIED",
  "PENDING",
  "IN_PROGRESS",
  "ON_HOLD",
  "CLOSED",
  "VOID",
];

/**
 * Split the loaded rows into the groups the page was asked for.
 *
 * The membership comes from `groupKeys`, which the backend returned per row; a
 * multi-party row therefore appears under each party it actually has and under
 * no party it does not. The group count shown is the count of *loaded* rows and
 * is labelled as such wherever paging may span the group, because a partial
 * client tally presented as a total is a number a reader cannot check
 * (`04_REGISTER_PRODUCT_SPECIFICATION` §12).
 */
export function groupRegisterEntries(
  entries: readonly ConstraintListEntry[],
  state: ConstraintUrlState,
  labelFor: (key: string) => string,
): readonly RegisterGroup[] {
  if (state.group === "none") {
    return [{ key: "all", label: "All Constraints", entries }];
  }
  const prefix = `${state.group}:`;
  const buckets = new Map<string, ConstraintListEntry[]>();
  for (const entry of entries) {
    const keys = entry.groupKeys.filter((key) => key.startsWith(prefix));
    if (keys.length === 0) {
      const fallback = `${prefix}${UNRESOLVED_PARTY_FILTER_BUCKET}`;
      buckets.set(fallback, [...(buckets.get(fallback) ?? []), entry]);
      continue;
    }
    for (const key of keys) buckets.set(key, [...(buckets.get(key) ?? []), entry]);
  }
  const groups = [...buckets.entries()].map(([key, groupEntries]) => ({
    key,
    label: labelFor(key),
    entries: groupEntries as readonly ConstraintListEntry[],
  }));
  if (state.group === "status") {
    return groups.sort(
      (left, right) =>
        STATUS_GROUP_ORDER.indexOf(left.key.slice(prefix.length)) -
        STATUS_GROUP_ORDER.indexOf(right.key.slice(prefix.length)),
    );
  }
  return groups.sort((left, right) => (left.label < right.label ? -1 : 1));
}
