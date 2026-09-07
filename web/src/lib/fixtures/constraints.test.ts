/**
 * What the synthetic Constraint corpus is allowed to say.
 *
 * Two kinds of assertion live here and only two. The first is the gate: a build
 * that has not enabled the synthetic provider gets an exception, not rows. The
 * second is contract conformance — canonical field names, the closed sets, the
 * party identity rules, and the boundary record whose backend flag contradicts
 * its own due date. Both are things a later edit could quietly break while
 * every rendering test stayed green.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { SyntheticProviderDisabledError } from "@/lib/fixtures/gate";
import {
  SYNTHETIC_CONSTRAINT_PROJECT_ID,
  SYNTHETIC_SECOND_PROJECT_ID,
  syntheticConstraintProjects,
  syntheticConstraintWorkspace,
} from "@/lib/fixtures/constraints";
import { SYNC_STATES_READABLE_AT_THIS_HEAD } from "@/contracts/constraints";

function enabled() {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("the synthetic gate", () => {
  it("refuses to produce a single row unless the provider is enabled", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "");
    expect(() => syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID)).toThrow(
      SyntheticProviderDisabledError,
    );
    expect(() => syntheticConstraintProjects()).toThrow(SyntheticProviderDisabledError);
  });
});

describe("the corpus", () => {
  it("returns null for a Project it does not describe, rather than an empty one", () => {
    enabled();
    expect(syntheticConstraintWorkspace("prj_not_here")).toBeNull();
  });

  it("uses the canonical Overview names and never the forbidden aliases", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const overview = workspace?.overview as unknown as Record<string, unknown>;
    expect(overview).toHaveProperty("averageOpenAgeBusinessDays");
    expect(overview).toHaveProperty("syncHealth");
    expect(overview).not.toHaveProperty("averageOpenAge");
    expect(overview).not.toHaveProperty("synchronizationHealth");
    for (const field of [
      "projectId",
      "projectToday",
      "projectTimezone",
      "totalOpen",
      "overdue",
      "dueSoon",
      "dueSoonThrough",
      "inMyCourt",
      "onHold",
      "recentlyChanged",
      "recentlyClosed",
      "draft",
      "needsAttention",
      "asOf",
    ]) {
      expect(overview).toHaveProperty(field);
    }
  });

  it("does not make the Overview counts reconstructible from one Register page", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const rows = workspace?.entries ?? [];
    const tallied = rows.filter((entry) => entry.isOverdue).length;
    // Deliberately different: the Project's position is not the loaded rows'.
    expect(workspace?.overview.overdue).not.toBe(tallied);
  });

  it("carries the boundary record whose backend flag contradicts its due date", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const boundary = workspace?.entries.find((entry) => entry.constraintId === "cst_syn_0043");
    expect(boundary?.dueDate).toBe("2021-03-31");
    expect(boundary?.isOverdue).toBe(false);
  });

  it("carries Codes that only a textual reading can tell apart, and no duplicates", () => {
    enabled();
    const codes = (syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID)?.entries ?? [])
      .map((entry) => entry.constraintCode)
      .filter((code): code is string => code !== null);
    // A numeric reading would collapse "2.10" onto 2.1 and "1.10" onto 1.1.
    for (const code of ["1.10", "2.01", "2.10", "L.1", "L.10", "L.2"]) {
      expect(codes).toContain(code);
    }
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("gives Drafts no Code at all", () => {
    enabled();
    const drafts = (syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID)?.entries ?? [])
      .filter((entry) => entry.status === "DRAFT");
    expect(drafts.length).toBeGreaterThan(0);
    for (const draft of drafts) expect(draft.constraintCode).toBeNull();
  });

  it("emits only the sync states a persisted-row read can establish", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    for (const entry of workspace?.entries ?? []) {
      expect(SYNC_STATES_READABLE_AT_THIS_HEAD).toContain(entry.syncState);
    }
    expect(SYNC_STATES_READABLE_AT_THIS_HEAD).toContain(workspace?.overview.syncHealth.state);
  });

  it("gives a PRINCIPAL party the closed token and never a principal identifier", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const parties = (workspace?.entries ?? []).flatMap((entry) => [...entry.bic, ...entry.responsible]);
    expect(parties.length).toBeGreaterThan(0);
    for (const party of parties) {
      if (party.kind === "PRINCIPAL") {
        expect(party.partyRefId).toBe("principal");
      }
      if (party.kind === "ENTITY") {
        expect(party.partyRefId).toMatch(/^ent_/);
      }
      if (party.kind === "UNRESOLVED") {
        // No stable identity, so nothing can offer it as a filter option.
        expect(party.partyRefId).toBeNull();
      }
      expect(JSON.stringify(party)).not.toContain("prn_");
    }
  });

  it("offers no unresolved party as an individually filterable option", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    for (const option of workspace?.partyOptions ?? []) {
      expect(option.kind).not.toBe("UNRESOLVED");
      expect(option.partyRefId).not.toBeNull();
    }
  });

  it("names legacy gaps only from the backend's own missing-field list", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const legacy = Object.values(workspace?.details ?? {}).filter(
      (view) => view.recordQuality === "LEGACY_INCOMPLETE",
    );
    expect(legacy.length).toBeGreaterThan(0);
    for (const view of legacy) {
      expect(view.needsAttentionReasons).toContain("LEGACY_INCOMPLETE");
      expect(view.missingFields.length).toBeGreaterThan(0);
    }
    const normal = Object.values(workspace?.details ?? {}).filter(
      (view) => view.recordQuality === "NORMAL",
    );
    for (const view of normal) expect(view.missingFields).toHaveLength(0);
  });

  it("carries a record with no stored lifecycle at all", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    expect((workspace?.entries ?? []).some((entry) => entry.status === null)).toBe(true);
  });

  it("keeps the second Project's rows out of the first Project's read", () => {
    enabled();
    const first = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const second = syntheticConstraintWorkspace(SYNTHETIC_SECOND_PROJECT_ID);
    expect((first?.entries ?? []).every((entry) => entry.projectId === SYNTHETIC_CONSTRAINT_PROJECT_ID)).toBe(true);
    expect((second?.entries ?? []).every((entry) => entry.projectId === SYNTHETIC_SECOND_PROJECT_ID)).toBe(true);
  });

  it("relates the closed predecessor and its follow-up by relationship identity", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const predecessor = workspace?.details["cst_syn_0049"];
    const successor = workspace?.details["cst_syn_0064"];
    expect(predecessor?.relationships[0]?.relatedConstraintId).toBe("cst_syn_0064");
    expect(successor?.relationships[0]?.relatedConstraintId).toBe("cst_syn_0049");
    expect(predecessor?.relationships[0]?.relationshipId).toBe(
      successor?.relationships[0]?.relationshipId,
    );
  });

  it("records history as versions and outcomes, not as request digests", () => {
    enabled();
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID);
    const history = workspace?.history["cst_syn_0001"] ?? [];
    expect(history.length).toBeGreaterThan(0);
    for (const entry of history) {
      expect(entry).toHaveProperty("beforeVersion");
      expect(entry).toHaveProperty("afterVersion");
      expect(entry).not.toHaveProperty("requestDigest");
      expect(entry).not.toHaveProperty("idempotencyKey");
      expect(entry).not.toHaveProperty("correlationId");
    }
  });
});
