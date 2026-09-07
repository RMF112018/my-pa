/**
 * The Register's query, tested where it can be tested exactly.
 *
 * Three claims are worth more than the rest and are asserted first: that a
 * Code is text, that the derived booleans are read rather than recomputed, and
 * that a continuation cannot repeat or lose a row.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ConstraintListEntry } from "@/contracts/constraints";
import {
  DEFAULT_CONSTRAINT_URL_STATE,
  type ConstraintUrlState,
} from "./constraint-url-state";
import {
  filterRegisterEntries,
  groupRegisterEntries,
  queryRegisterPage,
  REGISTER_PAGE_SIZE,
  sortRegisterEntries,
} from "./register-query";

vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");

const PROJECT = "prj_syn_0001";

function row(overrides: Partial<ConstraintListEntry> & { constraintId: string }): ConstraintListEntry {
  return {
    projectId: PROJECT,
    constraintCode: null,
    description: "A synthetic Constraint.",
    category: { categoryId: "cat_syn_0001", prefix: "1", title: "Design information" },
    status: "IDENTIFIED",
    dateIdentified: "2026-01-01",
    dueDate: null,
    bic: [],
    responsible: [],
    reference: null,
    daysElapsed: 10,
    version: 1,
    updatedAt: "2026-08-01T00:00:00Z",
    isOverdue: false,
    isDueSoon: false,
    inMyCourt: false,
    recordQuality: "NORMAL",
    needsAttention: false,
    syncState: "IN_SYNC",
    groupKeys: ["category:cat_syn_0001", "status:IDENTIFIED"],
    ...overrides,
  };
}

const state: ConstraintUrlState = DEFAULT_CONSTRAINT_URL_STATE;

describe("Constraint Code is text", () => {
  it("orders 1.1, 1.10, 1.2 as text and not as decimals", () => {
    const rows = [
      row({ constraintId: "c3", constraintCode: "1.2" }),
      row({ constraintId: "c1", constraintCode: "1.1" }),
      row({ constraintId: "c2", constraintCode: "1.10" }),
    ];
    expect(sortRegisterEntries(rows, state).map((entry) => entry.constraintCode)).toEqual([
      "1.1",
      "1.10",
      "1.2",
    ]);
  });

  it("orders 2.09 before 2.10, which a numeric parse would also get right, and 2.9 after both", () => {
    const rows = [
      row({ constraintId: "c3", constraintCode: "2.9" }),
      row({ constraintId: "c2", constraintCode: "2.10" }),
      row({ constraintId: "c1", constraintCode: "2.01" }),
    ];
    expect(sortRegisterEntries(rows, state).map((entry) => entry.constraintCode)).toEqual([
      "2.01",
      "2.10",
      "2.9",
    ]);
  });

  it("sorts a Draft with no Code last rather than treating absence as zero", () => {
    const rows = [
      row({ constraintId: "c2", constraintCode: null, status: "DRAFT" }),
      row({ constraintId: "c1", constraintCode: "1.01" }),
    ];
    const scope = { ...state, scope: "all" as const };
    expect(sortRegisterEntries(rows, scope).map((entry) => entry.constraintId)).toEqual(["c1", "c2"]);
  });
});

describe("backend authority drives urgency and ownership", () => {
  it("honours isOverdue: false on a record whose due date is long past", () => {
    const rows = [
      row({ constraintId: "c1", dueDate: "2021-03-31", isOverdue: false }),
      row({ constraintId: "c2", dueDate: "2099-01-01", isOverdue: true }),
    ];
    const overdue = filterRegisterEntries(rows, { ...state, overdue: true }, PROJECT);
    // The one the backend calls overdue, and only it — whatever the dates say.
    expect(overdue.map((entry) => entry.constraintId)).toEqual(["c2"]);
  });

  it("selects Due Soon from isDueSoon and never from a locally computed window", () => {
    const rows = [
      row({ constraintId: "c1", dueDate: "2026-08-25", isDueSoon: false }),
      row({ constraintId: "c2", dueDate: "2027-06-01", isDueSoon: true }),
    ];
    expect(
      filterRegisterEntries(rows, { ...state, dueSoon: true }, PROJECT).map((e) => e.constraintId),
    ).toEqual(["c2"]);
  });

  it("selects My Court from inMyCourt and never from a BIC label", () => {
    const rows = [
      row({
        constraintId: "c1",
        inMyCourt: false,
        bic: [{ kind: "PRINCIPAL", partyRefId: "principal", displayLabel: "You" }],
      }),
      row({ constraintId: "c2", inMyCourt: true, bic: [] }),
    ];
    expect(
      filterRegisterEntries(rows, { ...state, inMyCourt: true }, PROJECT).map((e) => e.constraintId),
    ).toEqual(["c2"]);
  });
});

describe("scope", () => {
  const rows = [
    row({ constraintId: "open", status: "IN_PROGRESS" }),
    row({ constraintId: "hold", status: "ON_HOLD" }),
    row({ constraintId: "closed", status: "CLOSED" }),
    row({ constraintId: "void", status: "VOID" }),
    row({ constraintId: "draft", status: "DRAFT" }),
    row({ constraintId: "legacy", status: null }),
  ];

  it("open admits the four active states only", () => {
    expect(filterRegisterEntries(rows, state, PROJECT).map((e) => e.constraintId)).toEqual([
      "open",
      "hold",
    ]);
  });

  it("closed admits CLOSED and VOID, and the rows keep their distinct status", () => {
    const closed = filterRegisterEntries(rows, { ...state, scope: "closed" }, PROJECT);
    expect(closed.map((e) => e.status)).toEqual(["CLOSED", "VOID"]);
  });

  it("draft admits only persisted Drafts", () => {
    expect(
      filterRegisterEntries(rows, { ...state, scope: "draft" }, PROJECT).map((e) => e.constraintId),
    ).toEqual(["draft"]);
  });

  it("all admits every row including one with no stored lifecycle", () => {
    expect(filterRegisterEntries(rows, { ...state, scope: "all" }, PROJECT)).toHaveLength(6);
  });
});

describe("party filters", () => {
  const rows = [
    row({
      constraintId: "entity",
      bic: [{ kind: "ENTITY", partyRefId: "ent_aaaaaaaa11111111", displayLabel: "Design Lead", entityId: "ent_aaaaaaaa11111111" }],
    }),
    row({
      constraintId: "unresolved",
      bic: [{ kind: "UNRESOLVED", partyRefId: null, displayLabel: "structural eng. (per log)" }],
    }),
  ];

  it("selects an entity party by its stable reference", () => {
    expect(
      filterRegisterEntries(rows, { ...state, bic: "ent_aaaaaaaa11111111" }, PROJECT).map(
        (e) => e.constraintId,
      ),
    ).toEqual(["entity"]);
  });

  it("selects unresolved parties only as a whole bucket, by kind and never by label", () => {
    expect(
      filterRegisterEntries(rows, { ...state, bic: "unresolved" }, PROJECT).map((e) => e.constraintId),
    ).toEqual(["unresolved"]);
    // The preserved source wording is not an identity and selects nothing.
    expect(
      filterRegisterEntries(rows, { ...state, bic: "structural eng. (per log)" }, PROJECT),
    ).toHaveLength(0);
  });
});

describe("search", () => {
  const rows = [
    row({ constraintId: "c1", constraintCode: "1.01", description: "Rebar schedule", reference: "RFI-0112" }),
    row({ constraintId: "c2", description: "Something else", reference: null }),
  ];

  it("searches Code, Description and Reference", () => {
    for (const term of ["1.01", "rebar", "rfi-0112"]) {
      expect(
        filterRegisterEntries(rows, { ...state, search: term }, PROJECT).map((e) => e.constraintId),
      ).toEqual(["c1"]);
    }
  });
});

describe("Project scoping", () => {
  it("never returns a row belonging to another Project", () => {
    const rows = [
      row({ constraintId: "mine" }),
      row({ constraintId: "theirs", projectId: "prj_syn_0002" }),
    ];
    expect(filterRegisterEntries(rows, state, PROJECT).map((e) => e.constraintId)).toEqual(["mine"]);
    const page = queryRegisterPage(rows, state, PROJECT, null);
    expect(page.entries.every((entry) => entry.projectId === PROJECT)).toBe(true);
  });
});

describe("bounded continuation", () => {
  const many = Array.from({ length: 120 }, (_, index) =>
    row({
      constraintId: `cst_${String(index).padStart(4, "0")}`,
      constraintCode: `1.${String(index).padStart(3, "0")}`,
    }),
  );

  it("returns fifty rows and a cursor, and reports the backend total", () => {
    const first = queryRegisterPage(many, state, PROJECT, null);
    expect(first.entries).toHaveLength(REGISTER_PAGE_SIZE);
    expect(first.isTruncated).toBe(true);
    expect(first.nextCursor).toBe(first.entries[REGISTER_PAGE_SIZE - 1].constraintId);
    // The total is the query's, not the number of rows loaded so far.
    expect(first.totalCount).toBe(120);
  });

  it("continues without duplicating or skipping a row, to the end", () => {
    const seen: string[] = [];
    let cursor: string | null = null;
    for (let page = 0; page < 5; page += 1) {
      const result: ReturnType<typeof queryRegisterPage> = queryRegisterPage(
        many,
        state,
        PROJECT,
        cursor,
      );
      seen.push(...result.entries.map((entry) => entry.constraintId));
      cursor = result.nextCursor;
      if (cursor === null) break;
    }
    expect(seen).toHaveLength(120);
    expect(new Set(seen).size).toBe(120);
    expect(cursor).toBeNull();
  });

  it("starts again rather than returning nothing when a cursor no longer resolves", () => {
    const page = queryRegisterPage(many, state, PROJECT, "cst_does_not_exist");
    expect(page.entries).toHaveLength(REGISTER_PAGE_SIZE);
    expect(page.entries[0].constraintId).toBe("cst_0000");
  });

  it("orders equal sort values by identity so a page boundary is stable", () => {
    const tied = [
      row({ constraintId: "b", constraintCode: null, daysElapsed: 5 }),
      row({ constraintId: "a", constraintCode: null, daysElapsed: 5 }),
    ];
    expect(
      sortRegisterEntries(tied, { ...state, sort: "daysOpen" }).map((e) => e.constraintId),
    ).toEqual(["a", "b"]);
  });
});

describe("grouping", () => {
  const rows = [
    row({
      constraintId: "c1",
      groupKeys: ["category:cat_syn_0001", "status:IDENTIFIED", "bic:principal", "bic:ent_a"],
    }),
    row({
      constraintId: "c2",
      groupKeys: ["category:cat_syn_0002", "status:IDENTIFIED", "bic:unresolved"],
    }),
  ];

  it("groups by the backend's own membership keys", () => {
    const groups = groupRegisterEntries(rows, { ...state, group: "category" }, (key) => key);
    expect(groups.map((group) => group.key).sort()).toEqual([
      "category:cat_syn_0001",
      "category:cat_syn_0002",
    ]);
  });

  it("places a multi-party row under each party it has, and never twice in one group", () => {
    const groups = groupRegisterEntries(rows, { ...state, group: "bic" }, (key) => key);
    const principal = groups.find((group) => group.key === "bic:principal");
    expect(principal?.entries.map((entry) => entry.constraintId)).toEqual(["c1"]);
    for (const group of groups) {
      expect(new Set(group.entries.map((e) => e.constraintId)).size).toBe(group.entries.length);
    }
  });

  it("returns one group when grouping is none", () => {
    const groups = groupRegisterEntries(rows, { ...state, group: "none" }, (key) => key);
    expect(groups).toHaveLength(1);
    expect(groups[0].entries).toHaveLength(2);
  });
});
