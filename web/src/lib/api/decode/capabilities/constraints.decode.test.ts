// @vitest-environment node
/**
 * T08-03 / T08-05: the six Constraint decoders, positive and negative.
 *
 * Every case starts from the *committed Python bytes* rather than a literal
 * written here, so a negative proves that one named mutation of a real payload
 * is refused — not that a hand-built object nobody ships is refused. The
 * positives are covered again by `parity.test.ts`; what this file adds is the
 * closed half: which malformations fail, and that each one fails as
 * `upstream_contract_invalid`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DECODERS } from "../index";
import type { GatewayCapability } from "../types";
import { FORBIDDEN_OVERVIEW_ALIASES } from "./_constraint-helpers";

const FIXTURE = join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json");
const PYTHON = JSON.parse(readFileSync(FIXTURE, "utf8")) as Record<string, unknown>;

const CONSTRAINT_CAPABILITIES = [
  "constraints.read",
  "constraints.list",
  "constraints.search",
  "constraints.history",
  "constraints.overview",
  "constraint_categories.list",
] as const satisfies readonly GatewayCapability[];

type Json = Record<string, unknown>;

function payload(capability: GatewayCapability): Json {
  return structuredClone(PYTHON[capability]) as Json;
}

/** The one record inside a single-record success, so a case can name a field. */
function detail(): Json {
  return payload("constraints.read").constraint as Json;
}

function firstRow(capability: GatewayCapability, key: string): Json {
  return (payload(capability)[key] as Json[])[0];
}

function withDetail(mutate: (record: Json) => void): unknown {
  const record = detail();
  mutate(record);
  return { constraint: record };
}

function withRow(capability: GatewayCapability, key: string, mutate: (row: Json) => void) {
  const row = firstRow(capability, key);
  mutate(row);
  return { [key]: [row] };
}

function withOverview(mutate: (overview: Json) => void): unknown {
  const overview = payload("constraints.overview").overview as Json;
  mutate(overview);
  return { overview };
}

function expectClosed(capability: GatewayCapability, input: unknown, why: string) {
  const decoded = DECODERS[capability](input);
  expect(decoded.ok, why).toBe(false);
  if (!decoded.ok) expect(decoded.code).toBe("upstream_contract_invalid");
}

describe("Constraint decoders accept the Python success bytes", () => {
  it.each(CONSTRAINT_CAPABILITIES)("%s decodes its committed payload", (capability) => {
    expect(PYTHON[capability], `${capability} has no Python fixture`).toBeTypeOf("object");
    expect(DECODERS[capability](payload(capability)).ok).toBe(true);
  });

  it("keeps constraintCode as text so 2.01 and 2.1 stay distinct", () => {
    const decoded = DECODERS["constraints.read"](withDetail((r) => { r.constraint_code = "2.10"; }));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.constraint.constraintCode).toBe("2.10");
    expect(typeof decoded.value.constraint.constraintCode).toBe("string");
  });

  it("renames the Overview to its canonical camelCase members", () => {
    const decoded = DECODERS["constraints.overview"](payload("constraints.overview"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.overview).toHaveProperty("averageOpenAgeBusinessDays");
    expect(decoded.value.overview).toHaveProperty("syncHealth");
    expect(decoded.value.overview.syncHealth.openConflictCount).toBe(0);
  });

  it("carries the backend-derived booleans through unchanged", () => {
    const decoded = DECODERS["constraints.list"](payload("constraints.list"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const [row] = decoded.value.constraints;
    expect(row.isOverdue).toBe(false);
    expect(row.isDueSoon).toBe(true);
    expect(row.inMyCourt).toBe(true);
    expect(row.syncState).toBe("never_synced");
  });

  it("admits a null average rather than turning it into a zero", () => {
    const decoded = DECODERS["constraints.overview"](
      withOverview((o) => { o.average_open_age_business_days = null; }),
    );
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.overview.averageOpenAgeBusinessDays).toBeNull();
  });
});

describe("malformed Constraint success fails closed", () => {
  it.each(["is_overdue", "is_due_soon", "in_my_court", "needs_attention", "version"])(
    "refuses a detail missing the authoritative field %s",
    (field) => {
      expectClosed(
        "constraints.read",
        withDetail((r) => { delete r[field]; }),
        `${field} was defaulted instead of required`,
      );
    },
  );

  it.each(["is_overdue", "is_due_soon", "in_my_court"])(
    "refuses %s sent as the string \"false\"",
    (field) => {
      expectClosed("constraints.read", withDetail((r) => { r[field] = "false"; }), field);
    },
  );

  it("refuses a Register row missing a derived boolean", () => {
    expectClosed(
      "constraints.list",
      withRow("constraints.list", "constraints", (row) => { delete row.in_my_court; }),
      "a list row defaulted inMyCourt",
    );
  });

  it("refuses an unknown lifecycle status", () => {
    expectClosed("constraints.read", withDetail((r) => { r.status = "reopen"; }), "status");
    expectClosed(
      "constraints.list",
      withRow("constraints.list", "constraints", (row) => { row.status = "archived"; }),
      "list status",
    );
  });

  it.each([
    ["a party that is not an object", "not-a-party"],
    ["a party of an unknown kind", { kind: "vendor", party_ref_id: null, display_label: "x" }],
    ["a party without a display label", { kind: "principal", party_ref_id: "principal" }],
  ])("refuses %s", (_name, party) => {
    expectClosed("constraints.read", withDetail((r) => { r.bic = [party]; }), "bic");
    expectClosed("constraints.read", withDetail((r) => { r.responsible = party as never; }), "responsible");
  });

  it.each(["partial", "workbook_unavailable", "verification_pending", "external_import_pending"])(
    "refuses the sync state %s, which no read at this head can establish",
    (state) => {
      expectClosed("constraints.read", withDetail((r) => { (r.sync as Json).state = state; }), state);
      expectClosed(
        "constraints.list",
        withRow("constraints.list", "constraints", (row) => { row.sync_state = state; }),
        state,
      );
      expectClosed(
        "constraints.overview",
        withOverview((o) => { (o.sync_health as Json).state = state; }),
        state,
      );
    },
  );

  it.each([undefined, 0, -1, "3", 3.5])("refuses the version %s", (version) => {
    expectClosed(
      "constraints.read",
      withDetail((r) => {
        if (version === undefined) delete r.version;
        else r.version = version;
      }),
      "version",
    );
  });

  it("refuses a history receipt with a missing or unreadable version", () => {
    expectClosed(
      "constraints.history",
      withRow("constraints.history", "history", (row) => { delete row.after_version; }),
      "after_version",
    );
    expectClosed(
      "constraints.history",
      withRow("constraints.history", "history", (row) => { row.before_version = "2"; }),
      "before_version",
    );
  });

  it("refuses an unknown history operation, actor or outcome", () => {
    for (const [field, value] of [
      ["operation", "merge"],
      ["actor", "vendor"],
      ["outcome", "maybe"],
    ] as const) {
      expectClosed(
        "constraints.history",
        withRow("constraints.history", "history", (row) => { row[field] = value; }),
        field,
      );
    }
  });

  it.each(FORBIDDEN_OVERVIEW_ALIASES)("refuses the Overview alias %s", (alias) => {
    expectClosed(
      "constraints.overview",
      withOverview((o) => { o[alias] = 4; }),
      alias,
    );
  });

  it("refuses an Overview that carries only the alias and not the canonical field", () => {
    expectClosed(
      "constraints.overview",
      withOverview((o) => {
        delete o.average_open_age_business_days;
        o.averageOpenAge = 4;
      }),
      "averageOpenAge substituted for averageOpenAgeBusinessDays",
    );
    expectClosed(
      "constraints.overview",
      withOverview((o) => {
        delete o.sync_health;
        o.synchronizationHealth = { state: "in_sync", open_conflict_count: 0, last_verified_at: null };
      }),
      "synchronizationHealth substituted for syncHealth",
    );
  });

  it("refuses an Overview missing any single count", () => {
    for (const field of [
      "total_open",
      "overdue",
      "due_soon",
      "in_my_court",
      "on_hold",
      "recently_changed",
      "recently_closed",
      "draft",
      "needs_attention",
    ]) {
      expectClosed("constraints.overview", withOverview((o) => { delete o[field]; }), field);
    }
  });

  it("refuses a Category whose backend-published prefix lock is absent", () => {
    expectClosed(
      "constraint_categories.list",
      withRow("constraint_categories.list", "categories", (row) => { delete row.prefix_locked; }),
      "prefix_locked",
    );
    expectClosed(
      "constraint_categories.list",
      withRow("constraint_categories.list", "categories", (row) => { row.state = "deleted"; }),
      "state",
    );
  });

  it("refuses a relationship or evidence link that lost its identity", () => {
    expectClosed(
      "constraints.read",
      withDetail((r) => { (r.relationships as Json[])[0].related_constraint_id = 7; }),
      "relationship identity",
    );
    expectClosed(
      "constraints.read",
      withDetail((r) => { delete (r.evidence_links as Json[])[0].evidence_ref; }),
      "evidence ref",
    );
  });

  it.each([
    ["needs_attention_reasons", "overdue"],
    ["missing_fields", "reference"],
  ])("refuses an unknown member of %s", (field, member) => {
    expectClosed("constraints.read", withDetail((r) => { r[field] = [member]; }), field);
  });

  it("refuses a page whose rows array was dropped or replaced", () => {
    expectClosed("constraints.list", {}, "empty list result");
    expectClosed("constraints.search", { constraints: {} }, "search rows were not an array");
    expectClosed("constraints.history", {}, "empty history result");
    expectClosed("constraint_categories.list", { categories: null }, "null categories");
    expectClosed("constraints.overview", {}, "empty overview result");
    expectClosed("constraints.read", { constraint: null }, "null constraint");
  });
});
