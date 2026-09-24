import { describe, expect, it } from "vitest";
import {
  buildConstraintQueryKey,
  buildConstraintSessionKey,
  serializeConstraintQueryKey,
  constraintQueryKeysEqual,
  type ConstraintQueryKeyInput,
} from "@/lib/constraint/query-key";

const ALL_PROJECTS = { kind: "ALL_PROJECTS" as const };
const PROJECT_A = { kind: "PROJECT" as const, projectId: "prj_aaaaaaaa11111111" };

const BASE: ConstraintQueryKeyInput = {
  mode: "list",
  scope: PROJECT_A,
  status: "active",
  sessionKey: "prn_a::session-1",
  scopeEpoch: 0,
};

describe("buildConstraintQueryKey equality", () => {
  it("produces equal keys for equal semantic inputs including empty-vs-undefined normalization", () => {
    const a = buildConstraintQueryKey({ ...BASE, q: "", cursor: "  ", page: null, categoryId: undefined });
    const b = buildConstraintQueryKey({ ...BASE, q: undefined, cursor: null, page: undefined, categoryId: null });
    expect(constraintQueryKeysEqual(a, b)).toBe(true);
    expect(serializeConstraintQueryKey(a)).toBe(serializeConstraintQueryKey(b));
    expect(a.resource).toBe("constraints");
    expect(a.q).toBeNull();
    expect(a.cursor).toBeNull();
  });

  it("normalizes numeric page across number/string forms", () => {
    const a = buildConstraintQueryKey({ ...BASE, page: 2 });
    const b = buildConstraintQueryKey({ ...BASE, page: "2" });
    expect(constraintQueryKeysEqual(a, b)).toBe(true);
  });

  it("never includes a Principal field in the serialized key", () => {
    const key = buildConstraintQueryKey(BASE);
    const serialized = serializeConstraintQueryKey(key);
    expect(serialized.toLowerCase()).not.toContain("principal");
    expect(Object.keys(key)).not.toContain("principal");
    expect(Object.keys(key)).not.toContain("principalId");
  });
});

describe("buildConstraintQueryKey isolation", () => {
  it.each([
    ["mode", { mode: "search" as const }],
    ["scope (ALL_PROJECTS vs PROJECT)", { scope: ALL_PROJECTS }],
    ["q", { q: "drawings" }],
    ["status", { status: "closed" }],
    ["cursor", { cursor: "cst_aaaaaaaa11111111" }],
    ["page", { page: 2 }],
    ["categoryId", { categoryId: "cat_aaaaaaaa11111111" }],
    ["sessionKey", { sessionKey: "prn_b::session-1" }],
    ["scopeEpoch", { scopeEpoch: 1 }],
  ])("differs when %s changes", (_label, patch) => {
    const left = buildConstraintQueryKey(BASE);
    const right = buildConstraintQueryKey({ ...BASE, ...patch });
    expect(constraintQueryKeysEqual(left, right)).toBe(false);
    expect(serializeConstraintQueryKey(left)).not.toBe(serializeConstraintQueryKey(right));
  });

  it("distinguishes a PROJECT scope from ALL_PROJECTS even with the same other fields", () => {
    const all = buildConstraintQueryKey({ ...BASE, scope: ALL_PROJECTS });
    const project = buildConstraintQueryKey({ ...BASE, scope: PROJECT_A });
    expect(constraintQueryKeysEqual(all, project)).toBe(false);
    expect(all.projectId).toBeNull();
    expect(project.projectId).toBe(PROJECT_A.projectId);
  });

  it("distinguishes two different exact Projects", () => {
    const a = buildConstraintQueryKey({ ...BASE, scope: PROJECT_A });
    const b = buildConstraintQueryKey({
      ...BASE,
      scope: { kind: "PROJECT", projectId: "prj_bbbbbbbb22222222" },
    });
    expect(constraintQueryKeysEqual(a, b)).toBe(false);
  });

  it("keeps list and search modes distinct even with the same q", () => {
    const list = buildConstraintQueryKey({ ...BASE, mode: "list", q: "plan" });
    const search = buildConstraintQueryKey({ ...BASE, mode: "search", q: "plan" });
    expect(constraintQueryKeysEqual(list, search)).toBe(false);
  });

  it("keeps detail and category distinct for the same constraintId-shaped scope", () => {
    const detail = buildConstraintQueryKey({
      mode: "detail",
      scope: PROJECT_A,
      constraintId: "cst_aaaaaaaa11111111",
      sessionKey: "prn_a::session-1",
      scopeEpoch: 0,
    });
    const category = buildConstraintQueryKey({
      mode: "category",
      scope: PROJECT_A,
      categoryId: "cat_aaaaaaaa11111111",
      sessionKey: "prn_a::session-1",
      scopeEpoch: 0,
    });
    expect(constraintQueryKeysEqual(detail, category)).toBe(false);
  });

  it("distinguishes a category-collection read (no categoryId) from one category's own read", () => {
    const collection = buildConstraintQueryKey({ ...BASE, mode: "category", categoryId: null });
    const record = buildConstraintQueryKey({
      ...BASE,
      mode: "category",
      categoryId: "cat_aaaaaaaa11111111",
    });
    expect(constraintQueryKeysEqual(collection, record)).toBe(false);
  });
});

describe("buildConstraintQueryKey validation", () => {
  it("rejects an unsupported mode", () => {
    expect(() =>
      buildConstraintQueryKey({ ...BASE, mode: "bogus" as ConstraintQueryKeyInput["mode"] }),
    ).toThrow(/unsupported Constraint query mode/);
  });

  it("requires constraintId for detail mode", () => {
    expect(() => buildConstraintQueryKey({ ...BASE, mode: "detail", constraintId: null })).toThrow(
      /constraintId is required/,
    );
  });

  it("requires projectId when scope.kind is PROJECT", () => {
    expect(() =>
      buildConstraintQueryKey({ ...BASE, scope: { kind: "PROJECT", projectId: "  " } }),
    ).toThrow(/projectId is required/);
  });

  it("rejects an empty sessionKey", () => {
    expect(() => buildConstraintQueryKey({ ...BASE, sessionKey: "  " })).toThrow(/sessionKey/);
  });

  it("rejects a non-finite scopeEpoch", () => {
    expect(() => buildConstraintQueryKey({ ...BASE, scopeEpoch: Number.NaN })).toThrow(/scopeEpoch/);
  });
});

describe("buildConstraintSessionKey", () => {
  it("joins principalId and sessionEpoch deterministically", () => {
    expect(buildConstraintSessionKey("prn_a", "session-1")).toBe("prn_a::session-1");
  });

  it("rejects empty principalId or sessionEpoch", () => {
    expect(() => buildConstraintSessionKey("", "session-1")).toThrow();
    expect(() => buildConstraintSessionKey("prn_a", "")).toThrow();
  });
});
