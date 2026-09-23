// @vitest-environment node
/**
 * R01-WP09: the 13 Constraint authoring decoders, against the committed Python bytes.
 *
 * Every positive case starts from `fixtures/python/success.json`, which
 * `tests/contract/test_bff_success_decoder_parity.py` holds equal to a live dump
 * of the real domain dataclasses through the handlers' own serialisers. The
 * NO_OP and REPLAYED cases are derived from those same bytes by changing
 * *values* only (disposition, outcome, versions) — the keys a Python NO_OP or
 * replay publishes are the APPLIED keys — so no case here is a hand-written
 * belief about the wire.
 *
 * Three families of assertion:
 *
 * 1. **Disposition invariants.** APPLIED means outcome applied, version + 1,
 *    record = receipt's after-version; NO_OP means an unmoved version; REPLAYED
 *    accepts a record *newer* than its original receipt and refuses one older.
 * 2. **Shape.** Enums, identifiers, PartyRefs, dates and nullability are
 *    refused when wrong, and unknown vocabulary members are refused, not mapped.
 * 3. **Nondisclosure.** The raw fixture carries `principal_id`,
 *    `idempotency_key`, `request_digest`, `client_context`, `correlation_id` and
 *    `recorded_at`; no decoded output may carry any of them, by key or value.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DECODERS } from "../index";
import type { GatewayCapability } from "../types";

const FIXTURE = join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json");
const committed: Record<string, unknown> = JSON.parse(readFileSync(FIXTURE, "utf8")) as Record<
  string,
  unknown
>;

type WireObject = Record<string, unknown>;

interface WireReceipt extends WireObject {
  outcome: string;
  before_version: number;
  after_version: number;
  project_id: string | null;
}

interface WireConstraintReceipt extends WireReceipt {
  constraint_id: string;
  revision_id: string | null;
  history_id: string;
  operation: string;
  actor: string;
}

interface WireConstraint extends WireObject {
  constraint_id: string;
  version: number;
  project_id: string | null;
  bic: WireObject[];
  responsible: WireObject[];
}

interface WireSingle {
  disposition: string;
  constraint: WireConstraint;
  receipt: WireConstraintReceipt;
}

interface WireFollowUp {
  disposition: string;
  predecessor: WireConstraint;
  successor: WireConstraint;
  predecessor_receipt: WireConstraintReceipt;
  successor_receipt: WireConstraintReceipt;
  relationship_id: string;
}

interface WireCategory extends WireObject {
  category_id: string;
  project_id: string;
  display_order: number;
  state: string;
}

interface WireCategoryReceipt extends WireReceipt {
  category_id: string;
  project_id: string;
  operation: string;
}

interface WireCategoryResult {
  disposition: string;
  category: WireCategory;
  receipt: WireCategoryReceipt;
}

interface WireReorder {
  disposition: string;
  categories: WireCategory[];
  receipts: WireCategoryReceipt[];
}

function wire<T>(capability: GatewayCapability): T {
  const payload = committed[capability];
  expect(payload, `${capability} has no committed Python fixture`).toBeDefined();
  return structuredClone(payload) as T;
}

function decode(capability: GatewayCapability, input: unknown) {
  return DECODERS[capability](input);
}

function accepts(capability: GatewayCapability, input: unknown): Record<string, unknown> {
  const decoded = decode(capability, input);
  expect(decoded.ok, `${capability} refused: ${decoded.ok ? "" : decoded.message}`).toBe(true);
  return (decoded.ok ? decoded.value : {}) as Record<string, unknown>;
}

function refuses(capability: GatewayCapability, input: unknown): void {
  const decoded = decode(capability, input);
  expect(decoded.ok, `${capability} accepted a payload it must refuse`).toBe(false);
  if (!decoded.ok) expect(decoded.code).toBe("upstream_contract_invalid");
}

const SINGLE_RECORD: readonly GatewayCapability[] = [
  "constraints.create",
  "constraints.create_published",
  "constraints.update",
  "constraints.publish",
  "constraints.transition",
  "constraints.close",
  "constraints.void",
  "constraints.reopen",
];

const SINGLE_CATEGORY: readonly GatewayCapability[] = [
  "constraint_categories.create",
  "constraint_categories.update",
  "constraint_categories.deactivate",
];

const ALL_AUTHORING: readonly GatewayCapability[] = [
  ...SINGLE_RECORD,
  "constraints.close_follow_up",
  ...SINGLE_CATEGORY,
  "constraint_categories.reorder",
];

/** The 22 safe Constraint members, and nothing else — `principal_id` above all. */
const RECORD_MEMBERS = [
  "bic",
  "categoryId",
  "closureCommentary",
  "completionDate",
  "constraintCode",
  "constraintId",
  "createdAt",
  "currentUpdate",
  "dateIdentified",
  "description",
  "dueDate",
  "lifecycleState",
  "origin",
  "projectId",
  "publishedAt",
  "recordQuality",
  "reference",
  "responsible",
  "updatedAt",
  "version",
  "voidReason",
  "voidedDate",
];

const RECEIPT_MEMBERS = [
  "actor",
  "afterVersion",
  "beforeVersion",
  "constraintId",
  "historyId",
  "occurredAt",
  "operation",
  "outcome",
  "projectId",
  "revisionId",
  "safeFailureReason",
];

const CATEGORY_MEMBERS = [
  "categoryId",
  "createdAt",
  "description",
  "displayOrder",
  "prefix",
  "prefixLockedAt",
  "projectId",
  "state",
  "title",
  "updatedAt",
];

const CATEGORY_RECEIPT_MEMBERS = [
  "actor",
  "afterVersion",
  "beforeVersion",
  "categoryId",
  "historyId",
  "occurredAt",
  "operation",
  "outcome",
  "projectId",
  "safeFailureReason",
];

const SENSITIVE_KEY = /principal_?id|idempotency|digest|client_?context|correlation|recorded/i;

function keysDeep(value: unknown, into: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) keysDeep(item, into);
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      into.push(key);
      keysDeep(item, into);
    }
  }
  return into;
}

/** A single-record fixture moved to NO_OP: same keys, an unmoved version. */
function asNoOp(payload: WireSingle): WireSingle {
  // `_mutate`'s NO_OP branch: the current record, a receipt at its version, no revision.
  payload.disposition = "no_op";
  payload.receipt.outcome = "no_op";
  payload.receipt.before_version = payload.constraint.version;
  payload.receipt.after_version = payload.constraint.version;
  payload.receipt.revision_id = null;
  return payload;
}

describe("nondisclosure: the raw wire's request identity never survives decoding", () => {
  it.each(ALL_AUTHORING)("%s strips every sensitive key and value", (capability) => {
    const raw = committed[capability];
    // The fixture is the unsafe one on purpose; otherwise this proves nothing.
    expect(
      keysDeep(raw).some((key) => SENSITIVE_KEY.test(key)),
      capability,
    ).toBe(true);
    const value = accepts(capability, structuredClone(raw));
    expect(keysDeep(value).filter((key) => SENSITIVE_KEY.test(key))).toEqual([]);
    const text = JSON.stringify(value);
    for (const needle of [
      "principal_id",
      "principalId",
      "idempotency",
      "digest",
      "client_context",
      "clientContext",
      "correlation",
      "recorded",
      "prn_aaaaaaaa",
      "parity-",
      "corr_",
      "a".repeat(64),
    ]) {
      expect(text, `${capability} output carried ${needle}`).not.toContain(needle);
    }
  });

  it("drops an unknown extra key rather than passing it through", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.constraint.tenant_hint = "leak";
    payload.receipt.request_body = "leak";
    const value = accepts("constraints.update", payload);
    expect(JSON.stringify(value)).not.toContain("leak");
  });
});

describe("single-record Constraint mutations", () => {
  it.each(SINGLE_RECORD)("%s decodes its committed APPLIED fixture exactly", (capability) => {
    const value = accepts(capability, wire(capability));
    expect(Object.keys(value).sort()).toEqual(["constraint", "disposition", "receipt"]);
    expect(value.disposition).toBe("applied");
    expect(Object.keys(value.constraint as object).sort()).toEqual(RECORD_MEMBERS);
    expect(Object.keys(value.receipt as object).sort()).toEqual(RECEIPT_MEMBERS);
  });

  it("publishes camelCase members and the domain PartyRef shape", () => {
    const value = accepts("constraints.update", wire("constraints.update"));
    expect(value.constraint).toMatchObject({
      constraintId: "cst_aaaaaaaa11111111",
      lifecycleState: "identified",
      origin: "product",
      version: 3,
      constraintCode: "2.01",
      dueDate: "2026-08-16",
      bic: [
        { kind: "principal", entityId: null, label: null },
        { kind: "entity", entityId: "ent_aaaaaaaa11111111", label: "Pat" },
      ],
      responsible: [{ kind: "unresolved", entityId: null, label: "Steel subcontractor" }],
    });
    expect(value.receipt).toMatchObject({
      operation: "update",
      outcome: "applied",
      beforeVersion: 2,
      afterVersion: 3,
    });
  });

  it.each(["constraints.update", "constraints.transition", "constraints.close"] as const)(
    "%s accepts NO_OP with an unmoved version",
    (capability) => {
      const value = accepts(capability, asNoOp(wire<WireSingle>(capability)));
      expect(value.disposition).toBe("no_op");
    },
  );

  it.each(SINGLE_RECORD)(
    "%s accepts REPLAYED with a record newer than its receipt",
    (capability) => {
      const payload = wire<WireSingle>(capability);
      payload.disposition = "replayed";
      payload.constraint.version = payload.receipt.after_version + 2;
      const value = accepts(capability, payload);
      expect(value.disposition).toBe("replayed");
      expect((value.constraint as { version: number }).version).toBe(
        payload.receipt.after_version + 2,
      );
    },
  );

  it("accepts REPLAYED even after the record moved to another Project", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.disposition = "replayed";
    payload.constraint.version = 7;
    payload.constraint.project_id = "prj_cccccccc33333333";
    accepts("constraints.update", payload);
  });

  it("accepts REPLAYED at exactly the receipt's version", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.disposition = "replayed";
    accepts("constraints.update", payload);
  });

  it("refuses REPLAYED with a record older than its receipt", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.disposition = "replayed";
    payload.constraint.version = payload.receipt.after_version - 1;
    refuses("constraints.update", payload);
  });

  it("refuses APPLIED whose record is not the receipt's after-version", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.constraint.version = payload.receipt.after_version + 1;
    refuses("constraints.update", payload);
  });

  it("refuses APPLIED whose receipt advanced by more than one", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.receipt.before_version = payload.receipt.after_version - 2;
    refuses("constraints.update", payload);
  });

  it("refuses APPLIED carrying a NO_OP receipt", () => {
    refuses("constraints.update", {
      ...asNoOp(wire<WireSingle>("constraints.update")),
      disposition: "applied",
    });
  });

  it("refuses NO_OP carrying an APPLIED receipt", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.disposition = "no_op";
    refuses("constraints.update", payload);
  });

  it("refuses NO_OP whose record is not the recorded version", () => {
    const payload = asNoOp(wire<WireSingle>("constraints.update"));
    payload.constraint.version += 1;
    refuses("constraints.update", payload);
  });

  it("refuses a receipt whose versions contradict its outcome", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.disposition = "replayed";
    payload.receipt.outcome = "no_op";
    refuses("constraints.update", payload);
  });

  it.each(["applied", "no_op", "replayed"])(
    "refuses a %s receipt that names a different Constraint",
    (disposition) => {
      const payload =
        disposition === "no_op"
          ? asNoOp(wire<WireSingle>("constraints.update"))
          : wire<WireSingle>("constraints.update");
      payload.disposition = disposition;
      payload.receipt.constraint_id = "cst_bbbbbbbb22222222";
      refuses("constraints.update", payload);
    },
  );

  it("refuses an APPLIED receipt that names a different Project", () => {
    const payload = wire<WireSingle>("constraints.update");
    payload.receipt.project_id = "prj_cccccccc33333333";
    refuses("constraints.update", payload);
  });

  it.each([
    ["disposition", (p: WireSingle) => void (p.disposition = "rejected")],
    ["disposition", (p: WireSingle) => void (p.disposition = "conflict")],
    ["outcome", (p: WireSingle) => void (p.receipt.outcome = "partial")],
    ["operation", (p: WireSingle) => void (p.receipt.operation = "delete")],
    ["actor", (p: WireSingle) => void (p.receipt.actor = "admin")],
    ["lifecycle", (p: WireSingle) => void (p.constraint.lifecycle_state = "reopened")],
    ["origin", (p: WireSingle) => void (p.constraint.origin = "import")],
    ["record quality", (p: WireSingle) => void (p.constraint.record_quality = "poor")],
  ])("refuses an unknown %s member", (_label, mutate) => {
    const payload = wire<WireSingle>("constraints.update");
    mutate(payload);
    refuses("constraints.update", payload);
  });

  it.each([
    ["a short Constraint id", (p: WireSingle) => void (p.constraint.constraint_id = "cst_short")],
    [
      "a wrong-prefix Project id",
      (p: WireSingle) => void (p.constraint.project_id = "prn_aaaaaaaa11111111"),
    ],
    [
      "a non-canonical Category id",
      (p: WireSingle) => void (p.constraint.category_id = "cat_aaaaaaaa11111111"),
    ],
    [
      "a wrong-prefix history id",
      (p: WireSingle) => void (p.receipt.history_id = "cchst_aaaaaaaa11111111"),
    ],
    ["a malformed revision id", (p: WireSingle) => void (p.receipt.revision_id = "crev_x")],
    ["a non-ISO date", (p: WireSingle) => void (p.constraint.due_date = "08/16/2026")],
    [
      "a date-time in a date field",
      (p: WireSingle) => void (p.constraint.date_identified = "2026-08-01T00:00:00+00:00"),
    ],
    ["a non-ISO instant", (p: WireSingle) => void (p.constraint.updated_at = "yesterday")],
    ["version zero", (p: WireSingle) => void (p.constraint.version = 0)],
    ["a fractional version", (p: WireSingle) => void (p.constraint.version = 2.5)],
    ["a numeric Code", (p: WireSingle) => void (p.constraint.constraint_code = 2.01)],
    ["a missing nullable key", (p: WireSingle) => void delete p.constraint.reference],
    ["a missing receipt", (p: WireSingle) => void delete (p as Partial<WireSingle>).receipt],
    ["a negative before-version", (p: WireSingle) => void (p.receipt.before_version = -1)],
  ])("refuses %s", (_label, mutate) => {
    const payload = wire<WireSingle>("constraints.update");
    mutate(payload);
    refuses("constraints.update", payload);
  });

  it.each([
    ["an entity without an identity", { kind: "entity", entity_id: null, label: "Pat" }],
    [
      "a principal with an identity",
      { kind: "principal", entity_id: "ent_aaaaaaaa11111111", label: null },
    ],
    ["a principal with a label", { kind: "principal", entity_id: null, label: "You" }],
    ["an unresolved party without wording", { kind: "unresolved", entity_id: null, label: null }],
    ["a blank label", { kind: "entity", entity_id: "ent_aaaaaaaa11111111", label: "   " }],
    ["an unknown kind", { kind: "team", entity_id: null, label: "Crew" }],
    ["a malformed entity id", { kind: "entity", entity_id: "ent_x", label: null }],
    [
      "the read plane's PartyRefView",
      { kind: "principal", party_ref_id: "principal", display_label: "You" },
    ],
  ])("refuses a PartyRef that is %s", (_label, party) => {
    const payload = wire<WireSingle>("constraints.update");
    payload.constraint.bic = [party];
    refuses("constraints.update", payload);
  });
});

describe("constraints.close_follow_up", () => {
  const CAPABILITY = "constraints.close_follow_up" as const;

  it("decodes the committed APPLIED fixture: both records, both receipts, the edge", () => {
    const value = accepts(CAPABILITY, wire(CAPABILITY));
    expect(Object.keys(value).sort()).toEqual([
      "disposition",
      "predecessor",
      "predecessorReceipt",
      "relationshipId",
      "successor",
      "successorReceipt",
    ]);
    expect(value.relationshipId).toBe("crel_aaaaaaaa11111111");
    expect(Object.keys(value.predecessor as object).sort()).toEqual(RECORD_MEMBERS);
    expect(Object.keys(value.successorReceipt as object).sort()).toEqual(RECEIPT_MEMBERS);
    expect(value.predecessor).toMatchObject({ lifecycleState: "closed", version: 4 });
    expect(value.successor).toMatchObject({ constraintId: "cst_bbbbbbbb22222222", version: 2 });
  });

  it("accepts REPLAYED with both current records newer than the original receipts", () => {
    const payload = wire<WireFollowUp>(CAPABILITY);
    payload.disposition = "replayed";
    payload.predecessor.version += 1;
    payload.successor.version += 3;
    expect(accepts(CAPABILITY, payload).disposition).toBe("replayed");
  });

  it("refuses NO_OP, which the composite never emits", () => {
    const payload = wire<WireFollowUp>(CAPABILITY);
    payload.disposition = "no_op";
    refuses(CAPABILITY, payload);
  });

  it.each([
    [
      "the predecessor receipt names another Constraint",
      (p: WireFollowUp) => void (p.predecessor_receipt.constraint_id = "cst_cccccccc33333333"),
    ],
    [
      "the successor receipt names another Constraint",
      (p: WireFollowUp) => void (p.successor_receipt.constraint_id = "cst_cccccccc33333333"),
    ],
    [
      "the receipts are swapped",
      (p: WireFollowUp) => {
        const receipt = p.predecessor_receipt;
        p.predecessor_receipt = p.successor_receipt;
        p.successor_receipt = receipt;
      },
    ],
    [
      "the successor is the predecessor",
      (p: WireFollowUp) => {
        p.successor = structuredClone(p.predecessor);
        p.successor_receipt = structuredClone(p.predecessor_receipt);
      },
    ],
    [
      "APPLIED with a predecessor record behind its receipt",
      (p: WireFollowUp) => void (p.predecessor.version -= 1),
    ],
    [
      "APPLIED with a successor record ahead of its receipt",
      (p: WireFollowUp) => void (p.successor.version += 1),
    ],
    [
      "APPLIED with a successor receipt that is not applied",
      (p: WireFollowUp) => {
        p.successor_receipt.outcome = "no_op";
        p.successor_receipt.before_version = p.successor_receipt.after_version;
        p.successor_receipt.revision_id = null;
      },
    ],
    [
      "APPLIED with a predecessor receipt advanced by two",
      (p: WireFollowUp) => void (p.predecessor_receipt.before_version -= 1),
    ],
    [
      "a non-canonical relationship id",
      (p: WireFollowUp) => void (p.relationship_id = "rel_aaaaaaaa11111111"),
    ],
    [
      "a missing relationship id",
      (p: WireFollowUp) => void delete (p as Partial<WireFollowUp>).relationship_id,
    ],
    [
      "REPLAYED with a successor older than its receipt",
      (p: WireFollowUp) => {
        p.disposition = "replayed";
        p.successor.version = 1;
      },
    ],
  ])("refuses a follow-up where %s", (_label, mutate) => {
    const payload = wire<WireFollowUp>(CAPABILITY);
    mutate(payload);
    refuses(CAPABILITY, payload);
  });
});

describe("single-Category mutations", () => {
  it.each(SINGLE_CATEGORY)(
    "%s decodes its APPLIED fixture and publishes version = receipt afterVersion",
    (capability) => {
      const payload = wire<WireCategoryResult>(capability);
      // The domain Category has no version; the fixture must not invent one.
      expect(payload.category).not.toHaveProperty("version");
      const value = accepts(capability, payload);
      expect(Object.keys(value).sort()).toEqual(["category", "disposition", "receipt"]);
      const category = value.category as Record<string, unknown>;
      expect(Object.keys(category).sort()).toEqual([...CATEGORY_MEMBERS, "version"].sort());
      expect(Object.keys(value.receipt as object).sort()).toEqual(CATEGORY_RECEIPT_MEMBERS);
      expect(category.version).toBe(payload.receipt.after_version);
    },
  );

  it("deactivate publishes the inactive state under the backend's update operation", () => {
    const value = accepts(
      "constraint_categories.deactivate",
      wire("constraint_categories.deactivate"),
    );
    expect(value.category).toMatchObject({ state: "inactive", version: 3 });
    expect(value.receipt).toMatchObject({ operation: "update" });
  });

  it("accepts NO_OP (deactivating an inactive Category) with version = the unmoved afterVersion", () => {
    const payload = wire<WireCategoryResult>("constraint_categories.deactivate");
    payload.disposition = "no_op";
    payload.receipt.outcome = "no_op";
    payload.receipt.before_version = 3;
    payload.receipt.after_version = 3;
    const value = accepts("constraint_categories.deactivate", payload);
    expect((value.category as { version: number }).version).toBe(3);
  });

  it("accepts REPLAYED and still publishes the original receipt's afterVersion", () => {
    const payload = wire<WireCategoryResult>("constraint_categories.update");
    payload.disposition = "replayed";
    payload.category.title = "Renamed since";
    const value = accepts("constraint_categories.update", payload);
    expect((value.category as { version: number }).version).toBe(payload.receipt.after_version);
  });

  it.each([
    [
      "the receipt names another Category",
      (p: WireCategoryResult) => void (p.receipt.category_id = "ccat_cccccccc33333333"),
    ],
    [
      "the receipt names another Project",
      (p: WireCategoryResult) => void (p.receipt.project_id = "prj_cccccccc33333333"),
    ],
    [
      "REPLAYED receipt names another Category",
      (p: WireCategoryResult) => {
        p.disposition = "replayed";
        p.receipt.category_id = "ccat_cccccccc33333333";
      },
    ],
    ["APPLIED advanced by two", (p: WireCategoryResult) => void (p.receipt.before_version -= 1)],
    [
      "APPLIED carries a no-op receipt",
      (p: WireCategoryResult) => {
        p.receipt.outcome = "no_op";
        p.receipt.before_version = p.receipt.after_version;
      },
    ],
    ["NO_OP carries an applied receipt", (p: WireCategoryResult) => void (p.disposition = "no_op")],
    [
      "the operation is not a Category operation",
      (p: WireCategoryResult) => void (p.receipt.operation = "deactivate"),
    ],
    ["the state is unknown", (p: WireCategoryResult) => void (p.category.state = "deleted")],
    [
      "the display order is negative",
      (p: WireCategoryResult) => void (p.category.display_order = -1),
    ],
    [
      "the history id is a Constraint one",
      (p: WireCategoryResult) => void (p.receipt.history_id = "chst_aaaaaaaa11111111"),
    ],
    ["the disposition is unknown", (p: WireCategoryResult) => void (p.disposition = "archived")],
  ])("refuses a Category mutation where %s", (_label, mutate) => {
    const payload = wire<WireCategoryResult>("constraint_categories.update");
    mutate(payload);
    refuses("constraint_categories.update", payload);
  });
});

describe("constraint_categories.reorder", () => {
  const CAPABILITY = "constraint_categories.reorder" as const;

  /** `_replayed_reorder`: the current scheme plus the single keyed receipt. */
  function asReplayed(payload: WireReorder): WireReorder {
    payload.disposition = "replayed";
    payload.receipts = payload.receipts.slice(0, 1);
    return payload;
  }

  it("decodes the committed APPLIED fixture: N categories, N aligned receipts", () => {
    const value = accepts(CAPABILITY, wire(CAPABILITY));
    const categories = value.categories as Array<Record<string, unknown>>;
    const receipts = value.receipts as Array<Record<string, unknown>>;
    expect(categories).toHaveLength(2);
    expect(receipts).toHaveLength(2);
    expect(categories.map((category) => category.displayOrder)).toEqual([0, 1]);
    expect(receipts.map((receipt) => receipt.categoryId)).toEqual(
      categories.map((category) => category.categoryId),
    );
    expect(Object.keys(categories[0] ?? {}).sort()).toEqual(CATEGORY_MEMBERS);
  });

  it("accepts REPLAYED with the full scheme and exactly one receipt", () => {
    const value = accepts(CAPABILITY, asReplayed(wire<WireReorder>(CAPABILITY)));
    expect(value.disposition).toBe("replayed");
    expect(value.categories as unknown[]).toHaveLength(2);
    expect(value.receipts as unknown[]).toHaveLength(1);
  });

  it("accepts REPLAYED whose display orders have moved since, since only APPLIED pins them", () => {
    const payload = asReplayed(wire<WireReorder>(CAPABILITY));
    payload.categories.forEach((category, index) => (category.display_order = 5 - index));
    accepts(CAPABILITY, payload);
  });

  it.each([
    ["APPLIED is missing a receipt", (p: WireReorder) => void p.receipts.pop()],
    ["APPLIED receipts are out of order", (p: WireReorder) => void p.receipts.reverse()],
    [
      "APPLIED advanced a receipt by two",
      (p: WireReorder) => {
        const receipt = p.receipts[1];
        if (receipt) receipt.before_version -= 1;
      },
    ],
    [
      "APPLIED carries a no-op receipt",
      (p: WireReorder) => {
        const receipt = p.receipts[0];
        if (receipt) {
          receipt.outcome = "no_op";
          receipt.before_version = receipt.after_version;
        }
      },
    ],
    [
      "APPLIED display order is one-based",
      (p: WireReorder) => {
        p.categories.forEach((category, index) => (category.display_order = index + 1));
      },
    ],
    [
      "APPLIED display orders are swapped",
      (p: WireReorder) => {
        const [first, second] = p.categories;
        if (first && second) [first.display_order, second.display_order] = [1, 0];
      },
    ],
    [
      "a receipt names another Project",
      (p: WireReorder) => {
        const receipt = p.receipts[1];
        if (receipt) receipt.project_id = "prj_cccccccc33333333";
      },
    ],
    [
      "the categories span two Projects",
      (p: WireReorder) => {
        const category = p.categories[1];
        if (category) category.project_id = "prj_cccccccc33333333";
      },
    ],
    [
      "a category repeats",
      (p: WireReorder) => {
        const [first] = p.categories;
        if (first) p.categories = [first, structuredClone({ ...first, display_order: 1 })];
        const [receipt] = p.receipts;
        if (receipt) p.receipts = [receipt, structuredClone(receipt)];
      },
    ],
    [
      "there are no categories",
      (p: WireReorder) => {
        p.categories = [];
        p.receipts = [];
      },
    ],
    ["the disposition is NO_OP", (p: WireReorder) => void (p.disposition = "no_op")],
    ["REPLAYED carries every receipt", (p: WireReorder) => void (p.disposition = "replayed")],
    [
      "REPLAYED carries no receipt",
      (p: WireReorder) => {
        asReplayed(p);
        p.receipts = [];
      },
    ],
    [
      "REPLAYED receipt is not the first category's",
      (p: WireReorder) => {
        p.disposition = "replayed";
        p.receipts = p.receipts.slice(1);
      },
    ],
    [
      "REPLAYED receipt is not a successful one",
      (p: WireReorder) => {
        asReplayed(p);
        const receipt = p.receipts[0];
        if (receipt) {
          receipt.outcome = "rejected";
          receipt.before_version = receipt.after_version;
        }
      },
    ],
  ])("refuses a reorder where %s", (_label, mutate) => {
    const payload = wire<WireReorder>(CAPABILITY);
    mutate(payload);
    refuses(CAPABILITY, payload);
  });
});
