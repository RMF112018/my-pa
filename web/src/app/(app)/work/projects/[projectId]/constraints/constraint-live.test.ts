import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_CONSTRAINT_URL_STATE, searchRegisterState } from "./constraint-url-state";
import { readDetail, readHistory, readRegister, registerQuery } from "./constraint-live";

const disclosure = {
  scope: "constraint-register",
  coverage: "partial",
  freshnessAt: "2026-09-08T12:00:00Z",
  authority: "accepted",
  limitations: ["bounded page"],
  truncated: true,
  nextCursor: "opaque-next",
} as const;

afterEach(() => vi.unstubAllGlobals());

describe("live Constraint query construction", () => {
  it("maps presentation values and sort names into the closed WP08 list vocabulary", () => {
    const query = new URLSearchParams(registerQuery({
      ...DEFAULT_CONSTRAINT_URL_STATE,
      status: "ON_HOLD",
      quality: "LEGACY_INCOMPLETE",
      sync: "CONFLICT",
      dueSoon: true,
      sort: "daysOpen",
      dir: "desc",
    }));
    expect(Object.fromEntries(query)).toMatchObject({
      status: "on_hold",
      quality: "legacy_incomplete",
      sync: "conflict",
      dueSoon: "true",
      sort: "days_elapsed",
      dir: "desc",
      pageSize: "50",
    });
  });

  it("canonicalizes search to the narrower route contract", () => {
    const state = searchRegisterState({
      ...DEFAULT_CONSTRAINT_URL_STATE,
      overdue: true,
      categoryId: "ccat_aaaaaaaa11111111",
      group: "status",
      sort: "updated",
    }, " steel ");
    const query = new URLSearchParams(registerQuery(state));
    expect([...query.keys()].sort()).toEqual(["pageSize", "q", "scope"]);
    expect(state.categoryId).toBeNull();
    expect(state.overdue).toBe(false);
    expect(state.group).toBe("none");
  });
});

describe("live Constraint adaptation", () => {
  it("maps backend values, disclosure and opaque continuation without deriving flags", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      shape: "backend",
      constraints: [{
        constraintId: "cst_aaaaaaaa11111111",
        projectId: "prj_aaaaaaaa11111111",
        constraintCode: "2.01",
        description: "Access",
        category: null,
        status: "on_hold",
        dateIdentified: null,
        dueDate: null,
        bic: [{ kind: "principal", partyRefId: "principal", displayLabel: "You", entityId: null }],
        responsible: [],
        reference: null,
        daysElapsed: 8,
        version: 3,
        updatedAt: "2026-09-08T12:00:00Z",
        isOverdue: true,
        isDueSoon: false,
        inMyCourt: true,
        recordQuality: "legacy_incomplete",
        needsAttention: true,
        syncState: "conflict",
        groupKeys: ["on_hold"],
      }],
      disclosure,
    }), { status: 200, headers: { "content-type": "application/json" } })));

    const result = await readRegister(
      "prj_aaaaaaaa11111111",
      { ...DEFAULT_CONSTRAINT_URL_STATE, group: "status" },
      null,
      new AbortController().signal,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.entries[0]).toMatchObject({
      status: "ON_HOLD",
      isOverdue: true,
      inMyCourt: true,
      recordQuality: "LEGACY_INCOMPLETE",
      syncState: "CONFLICT",
      groupKeys: ["status:ON_HOLD"],
    });
    expect(result.value.nextCursor).toBe("opaque-next");
  });

  it("rejects a detail returned for a different Project", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      shape: "backend",
      constraint: { projectId: "prj_bbbbbbbb22222222" },
      disclosure: { ...disclosure, truncated: false },
    }), { status: 200, headers: { "content-type": "application/json" } })));
    const result = await readDetail("prj_aaaaaaaa11111111", "cst_aaaaaaaa11111111", new AbortController().signal);
    expect(result).toMatchObject({ ok: false, error: { code: "constraint_not_in_project", status: 404 } });
  });

  it("does not fabricate backend URL-safety or provenance fields", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const result = url.includes("/history")
        ? {
            history: [{
              historyId: "hst_aaaaaaaa11111111",
              operation: "update",
              actor: "principal",
              outcome: "no_op",
              beforeVersion: 2,
              afterVersion: 2,
              occurredAt: "2026-09-08T12:00:00Z",
              revisionId: null,
              safeFailureReason: null,
            }],
          }
        : {
            constraint: {
              projectId: "prj_aaaaaaaa11111111",
              status: "identified",
              bic: [],
              responsible: [],
              recordQuality: "normal",
              needsAttentionReasons: [],
              sync: { state: "never_synced" },
              relationships: [],
              evidenceLinks: [{
                evidenceLinkId: "evl_aaaaaaaa11111111",
                evidenceKind: "reference",
                evidenceRef: "https://synthetic.example/evidence",
                role: "source",
              }],
            },
          };
      return new Response(JSON.stringify({ shape: "backend", ...result, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));

    const detail = await readDetail(
      "prj_aaaaaaaa11111111",
      "cst_aaaaaaaa11111111",
      new AbortController().signal,
    );
    expect(detail.ok).toBe(true);
    if (detail.ok) expect(detail.value.evidenceLinks[0]).not.toHaveProperty("isSafeUrl");

    const history = await readHistory(
      "prj_aaaaaaaa11111111",
      "cst_aaaaaaaa11111111",
      null,
      new AbortController().signal,
    );
    expect(history.ok).toBe(true);
    if (history.ok) expect(history.value.entries[0]).not.toHaveProperty("provenance");
  });
});
