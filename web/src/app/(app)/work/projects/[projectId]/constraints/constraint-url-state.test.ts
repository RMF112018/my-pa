/**
 * What a Constraint link carries, and what it must never carry.
 *
 * The second half is the one worth having. A serializer that emitted an
 * `expectedVersion` would produce a URL that, opened tomorrow, applies a
 * concurrency token to a record it no longer describes — and no rendering test
 * would notice. So the test below asserts the *closed set* of keys rather than
 * spot-checking a few, which is the only form of the assertion that a later
 * addition cannot slip past.
 */
import { describe, expect, it } from "vitest";
import {
  categoryRegisterState,
  clearedFilters,
  constraintsHref,
  constraintsRoute,
  DEFAULT_CONSTRAINT_URL_STATE,
  hasActiveFilters,
  kpiRegisterState,
  parseConstraintUrlState,
  projectSwitchState,
  serializeConstraintUrlState,
} from "./constraint-url-state";

describe("the canonical route", () => {
  it("is /work/projects/[projectId]/constraints", () => {
    expect(constraintsRoute("prj_syn_0001")).toBe("/work/projects/prj_syn_0001/constraints");
  });

  it("encodes the Project identifier rather than interpolating it raw", () => {
    expect(constraintsRoute("prj a/b")).toBe("/work/projects/prj%20a%2Fb/constraints");
  });
});

describe("the default Register state", () => {
  it("is scope=open, group=category, sort=code, dir=asc", () => {
    expect(DEFAULT_CONSTRAINT_URL_STATE.scope).toBe("open");
    expect(DEFAULT_CONSTRAINT_URL_STATE.group).toBe("category");
    expect(DEFAULT_CONSTRAINT_URL_STATE.sort).toBe("code");
    expect(DEFAULT_CONSTRAINT_URL_STATE.dir).toBe("asc");
  });

  it("is what an empty query parses to, and serializes back to nothing", () => {
    expect(parseConstraintUrlState({})).toEqual(DEFAULT_CONSTRAINT_URL_STATE);
    expect(serializeConstraintUrlState(DEFAULT_CONSTRAINT_URL_STATE)).toBe("");
    expect(constraintsHref("prj_syn_0001", DEFAULT_CONSTRAINT_URL_STATE)).toBe(
      "/work/projects/prj_syn_0001/constraints",
    );
  });

  it("defaults the tab to Overview", () => {
    expect(DEFAULT_CONSTRAINT_URL_STATE.view).toBe("overview");
  });
});

describe("round-tripping", () => {
  it("preserves every meaningful filter, group, sort and selection", () => {
    const state = parseConstraintUrlState({
      view: "register",
      scope: "closed",
      status: "ON_HOLD",
      category: "cat_syn_0002",
      bic: "principal",
      responsible: "ent_aaaaaaaa11111111",
      overdue: "1",
      dueSoon: "1",
      inMyCourt: "1",
      needsAttention: "1",
      sync: "CONFLICT",
      q: "beam",
      group: "status",
      sort: "due",
      dir: "desc",
      constraint: "cst_syn_0013",
    });
    const round = parseConstraintUrlState(
      Object.fromEntries(new URLSearchParams(serializeConstraintUrlState(state)).entries()),
    );
    expect(round).toEqual(state);
    expect(state.selectedConstraintId).toBe("cst_syn_0013");
  });

  it("serializes exactly the closed set of durable keys and nothing else", () => {
    const state = parseConstraintUrlState({
      view: "register",
      scope: "all",
      status: "CLOSED",
      category: "cat_syn_0001",
      bic: "principal",
      responsible: "unresolved",
      overdue: "1",
      dueSoon: "1",
      inMyCourt: "1",
      needsAttention: "1",
      sync: "IN_SYNC",
      q: "kerb",
      group: "none",
      sort: "updated",
      dir: "desc",
      constraint: "cst_syn_0001",
    });
    const keys = [...new URLSearchParams(serializeConstraintUrlState(state)).keys()].sort();
    expect(keys).toEqual([
      "bic",
      "category",
      "constraint",
      "dir",
      "dueSoon",
      "group",
      "inMyCourt",
      "needsAttention",
      "overdue",
      "q",
      "responsible",
      "scope",
      "sort",
      "status",
      "sync",
      "view",
    ]);
  });

  it("never emits an edit or concurrency internal, whatever was in the query", () => {
    const state = parseConstraintUrlState({
      view: "register",
      expectedVersion: "4",
      idempotencyKey: "idem_0001",
      receiptId: "rcp_0001",
      draftDescription: "half-typed text",
      conflictCopy: "{}",
      collapsedGroups: "cat_syn_0001",
    });
    const serialized = serializeConstraintUrlState(state);
    for (const forbidden of [
      "expectedVersion",
      "idempotencyKey",
      "receiptId",
      "draftDescription",
      "conflictCopy",
      "collapsedGroups",
    ]) {
      expect(serialized).not.toContain(forbidden);
    }
  });
});

describe("malformed values", () => {
  it("falls back to the default rather than forwarding an unknown value", () => {
    const state = parseConstraintUrlState({
      view: "timeline",
      scope: "archived",
      group: "colour",
      sort: "randomly",
      dir: "sideways",
      status: "ARCHIVED",
      sync: "MADE_UP",
    });
    expect(state.view).toBe("overview");
    expect(state.scope).toBe("open");
    expect(state.group).toBe("category");
    expect(state.sort).toBe("code");
    expect(state.dir).toBe("asc");
    expect(state.status).toBeNull();
    expect(state.sync).toBeNull();
  });

  it("treats only the literal 1 as a flag", () => {
    expect(parseConstraintUrlState({ overdue: "true" }).overdue).toBe(false);
    expect(parseConstraintUrlState({ overdue: "0" }).overdue).toBe(false);
    expect(parseConstraintUrlState({ overdue: "1" }).overdue).toBe(true);
  });

  it("rejects an identifier that is not identifier-shaped", () => {
    expect(parseConstraintUrlState({ category: "<script>" }).categoryId).toBeNull();
    expect(parseConstraintUrlState({ constraint: "a b" }).selectedConstraintId).toBeNull();
  });
});

describe("KPI navigation", () => {
  const from = { ...DEFAULT_CONSTRAINT_URL_STATE, view: "overview" as const };

  it("maps each metric to the Register state the accepted package names", () => {
    expect(kpiRegisterState(from, "totalOpen")).toMatchObject({ view: "register", scope: "open" });
    expect(kpiRegisterState(from, "overdue")).toMatchObject({ scope: "open", overdue: true });
    expect(kpiRegisterState(from, "dueSoon")).toMatchObject({ scope: "open", dueSoon: true });
    expect(kpiRegisterState(from, "inMyCourt")).toMatchObject({ scope: "open", inMyCourt: true });
    expect(kpiRegisterState(from, "onHold")).toMatchObject({ scope: "open", status: "ON_HOLD" });
    expect(kpiRegisterState(from, "needsAttention")).toMatchObject({ needsAttention: true });
    expect(kpiRegisterState(from, "draft")).toMatchObject({ scope: "draft" });
  });

  it("carries Project-neutral view preferences across a KPI jump", () => {
    const preferred = { ...from, group: "status" as const, sort: "due" as const, dir: "desc" as const };
    expect(kpiRegisterState(preferred, "overdue")).toMatchObject({
      group: "status",
      sort: "due",
      dir: "desc",
    });
  });

  it("navigates a Category bar by canonical categoryId", () => {
    expect(categoryRegisterState(from, "cat_syn_0003")).toMatchObject({
      view: "register",
      categoryId: "cat_syn_0003",
    });
  });
});

describe("filters", () => {
  it("recognises a narrowed population and clears it back to the defaults", () => {
    expect(hasActiveFilters(DEFAULT_CONSTRAINT_URL_STATE)).toBe(false);
    const narrowed = { ...DEFAULT_CONSTRAINT_URL_STATE, overdue: true };
    expect(hasActiveFilters(narrowed)).toBe(true);
    expect(hasActiveFilters(clearedFilters(narrowed))).toBe(false);
  });

  it("keeps the selected Constraint when filters are cleared", () => {
    const state = {
      ...DEFAULT_CONSTRAINT_URL_STATE,
      overdue: true,
      selectedConstraintId: "cst_syn_0001",
    };
    expect(clearedFilters(state).selectedConstraintId).toBe("cst_syn_0001");
  });
});

describe("switching Project", () => {
  it("drops Project-specific filter identities and the selection", () => {
    const state = parseConstraintUrlState({
      view: "register",
      scope: "closed",
      group: "status",
      sort: "due",
      dir: "desc",
      category: "cat_syn_0001",
      bic: "ent_aaaaaaaa11111111",
      responsible: "principal",
      constraint: "cst_syn_0001",
    });
    const next = projectSwitchState(state);
    expect(next.categoryId).toBeNull();
    expect(next.bic).toBeNull();
    expect(next.responsible).toBeNull();
    expect(next.selectedConstraintId).toBeNull();
    // Project-neutral preferences survive.
    expect(next).toMatchObject({ view: "register", scope: "closed", group: "status", sort: "due", dir: "desc" });
  });
});
