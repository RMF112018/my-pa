// @vitest-environment node
/**
 * The portfolio Constraint decoders, positive and closed.
 *
 * Every case starts from the committed Python bytes rather than a literal
 * written here, so a negative proves that one named mutation of a real payload
 * is refused. `parity.test.ts` already covers the plain positive; what this file
 * adds is the closed half, plus the two structural claims the portfolio shape
 * makes that no exact-Project decoder can make:
 *
 * - a portfolio row is decoded by the *same* guard as a Register row, so the two
 *   capabilities cannot drift into two answers about the same records;
 * - the overview carries one entry per Project and no roll-up, so a combined
 *   figure is absent rather than computed from counts that are not summable.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DECODERS } from "../index";
import type { GatewayCapability } from "../types";
import { decodeConstraintsList } from "./constraints.list";
import { decodeConstraintsPortfolioList } from "./constraints.portfolio_list";
import { decodeConstraintsPortfolioSearch } from "./constraints.portfolio_search";
import { decodeConstraintsPortfolioOverview } from "./constraints.portfolio_overview";
import { FORBIDDEN_OVERVIEW_ALIASES } from "./_constraint-helpers";

const FIXTURE = join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json");
const PYTHON = JSON.parse(readFileSync(FIXTURE, "utf8")) as Record<string, unknown>;

type Json = Record<string, unknown>;

function payload(capability: GatewayCapability): Json {
  return structuredClone(PYTHON[capability]) as Json;
}

function rows(capability: GatewayCapability): Json[] {
  return payload(capability).constraints as Json[];
}

function overviewBody(): { projects: Json[]; as_of: string } {
  return payload("constraints.portfolio_overview").overview as {
    projects: Json[];
    as_of: string;
  };
}

describe("the portfolio page reuses the Register's own guard", () => {
  it("is the same decoder function for the list, the search and the Register", () => {
    // Identity rather than equivalence: a third copy could be edited into a
    // second opinion about the same rows, and this is what forbids one.
    expect(decodeConstraintsPortfolioList).toBe(decodeConstraintsList);
    expect(decodeConstraintsPortfolioSearch).toBe(decodeConstraintsList);
  });

  it("decodes a page whose rows come from more than one Project", () => {
    const decoded = decodeConstraintsPortfolioList(payload("constraints.portfolio_list"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const projects = decoded.value.constraints.map((entry) => entry.projectId);
    expect(new Set(projects).size).toBeGreaterThan(1);
  });

  it("accepts an empty page, which is what a Principal with no rows has", () => {
    expect(decodeConstraintsPortfolioList({ constraints: [] }).ok).toBe(true);
    expect(decodeConstraintsPortfolioSearch({ constraints: [] }).ok).toBe(true);
  });

  it.each<readonly [string, unknown]>([
    ["an empty object", {}],
    ["rows sent as an object", { constraints: {} }],
    ["a row with no fields", { constraints: [{}] }],
    ["a boolean sent as a string", { constraints: [{ ...rows("constraints.portfolio_list")[0], in_my_court: "true" }] }],
    ["an unknown status", { constraints: [{ ...rows("constraints.portfolio_list")[0], status: "reopen" }] }],
    ["an unknown sync state", { constraints: [{ ...rows("constraints.portfolio_list")[0], sync_state: "partial" }] }],
    ["a dropped project_id", { constraints: [{ ...rows("constraints.portfolio_list")[0], project_id: undefined }] }],
  ])("refuses %s", (_name, malformed) => {
    expect(decodeConstraintsPortfolioList(malformed).ok).toBe(false);
    expect(decodeConstraintsPortfolioSearch(malformed).ok).toBe(false);
  });
});

describe("the portfolio overview is one entry per Project and nothing more", () => {
  it("decodes the committed payload into per-Project entries and an as_of", () => {
    const decoded = decodeConstraintsPortfolioOverview(
      payload("constraints.portfolio_overview"),
    );
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const { projects, asOf } = decoded.value.overview;
    expect(projects.length).toBeGreaterThan(1);
    expect(typeof asOf).toBe("string");
    // Each entry keeps its own calendar; nothing here reconciles them.
    expect(new Set(projects.map((entry) => entry.projectTimezone)).size).toBeGreaterThan(1);
    for (const entry of projects) {
      expect(entry).toHaveProperty("averageOpenAgeBusinessDays");
      expect(entry).toHaveProperty("syncHealth");
    }
  });

  it("publishes no portfolio-wide roll-up member", () => {
    const decoded = decodeConstraintsPortfolioOverview(
      payload("constraints.portfolio_overview"),
    );
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(Object.keys(decoded.value.overview).sort()).toEqual(["asOf", "projects"]);
  });

  it("accepts an empty Project collection, which is a Principal with no Projects", () => {
    const decoded = decodeConstraintsPortfolioOverview({
      overview: { projects: [], as_of: "2026-08-09T12:00:00Z" },
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.overview.projects).toEqual([]);
  });

  it.each<readonly [string, unknown]>([
    ["an empty object", {}],
    ["a missing overview", { overview: undefined }],
    ["the overview sent as an array", { overview: [] }],
    ["a missing projects array", { overview: { as_of: "2026-08-09T12:00:00Z" } }],
    ["projects sent as an object", { overview: { projects: {}, as_of: "2026-08-09T12:00:00Z" } }],
    ["a missing as_of", { overview: { projects: [] } }],
    ["an as_of sent as a number", { overview: { projects: [], as_of: 1 } }],
    ["an entry that is not an object", { overview: { projects: [1], as_of: "2026-08-09T12:00:00Z" } }],
    [
      "an entry missing a required count",
      {
        overview: {
          projects: [{ ...overviewBody().projects[0], total_open: undefined }],
          as_of: "2026-08-09T12:00:00Z",
        },
      },
    ],
    [
      "an entry missing its Project",
      {
        overview: {
          projects: [{ ...overviewBody().projects[0], project_id: undefined }],
          as_of: "2026-08-09T12:00:00Z",
        },
      },
    ],
  ])("refuses %s", (_name, malformed) => {
    expect(decodeConstraintsPortfolioOverview(malformed).ok).toBe(false);
  });

  it.each(FORBIDDEN_OVERVIEW_ALIASES)(
    "refuses the forbidden alias %s on a portfolio entry",
    (alias) => {
      const decoded = decodeConstraintsPortfolioOverview({
        overview: {
          projects: [{ ...overviewBody().projects[0], [alias]: 1 }],
          as_of: "2026-08-09T12:00:00Z",
        },
      });
      expect(decoded.ok).toBe(false);
    },
  );
});

describe("the registry reaches the portfolio decoders by name", () => {
  it.each([
    "constraints.portfolio_list",
    "constraints.portfolio_search",
    "constraints.portfolio_overview",
  ] as const satisfies readonly GatewayCapability[])(
    "%s decodes its committed Python fixture and refuses an empty object",
    (capability) => {
      expect(DECODERS[capability](PYTHON[capability]).ok).toBe(true);
      expect(DECODERS[capability]({}).ok).toBe(false);
    },
  );
});
