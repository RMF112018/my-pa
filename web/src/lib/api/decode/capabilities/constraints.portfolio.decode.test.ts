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
 *   figure is absent rather than computed from counts that are not summable;
 * - every portfolio answer states how many owned Projects it could not include,
 *   as a count and never as an identity.
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
  it("is the same decoder function for the portfolio list and the portfolio search", () => {
    // Identity rather than equivalence: a second copy could be edited into a
    // second opinion about the same rows, and this is what forbids one.
    expect(decodeConstraintsPortfolioSearch).toBe(decodeConstraintsPortfolioList);
  });

  it("decodes the rows exactly as the exact-Project Register decodes them", () => {
    // The portfolio decoder is deliberately *not* the Register's own function
    // any more — a portfolio answer carries `omitted_projects` and an
    // exact-Project one cannot — so identity is replaced by the property
    // identity was standing in for: the same bytes yield the same rows. A
    // portfolio guard that drifted into a second projection fails here.
    const body = payload("constraints.portfolio_list");
    const portfolio = decodeConstraintsPortfolioList(body);
    const register = decodeConstraintsList({ constraints: body.constraints });
    expect(portfolio.ok).toBe(true);
    expect(register.ok).toBe(true);
    if (!portfolio.ok || !register.ok) return;
    expect(portfolio.value.constraints).toEqual(register.value.constraints);
  });

  it("carries the omitted-Project count, and nothing that names a Project", () => {
    const decoded = decodeConstraintsPortfolioList(payload("constraints.portfolio_list"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.omittedProjects).toBe(
      payload("constraints.portfolio_list").omitted_projects,
    );
    expect(decoded.value.omittedProjects).toBeGreaterThan(0);
    // A count and nothing else: the decoded result has exactly two members.
    expect(Object.keys(decoded.value).sort()).toEqual(["constraints", "omittedProjects"]);
  });

  it("decodes a page whose rows come from more than one Project", () => {
    const decoded = decodeConstraintsPortfolioList(payload("constraints.portfolio_list"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const projects = decoded.value.constraints.map((entry) => entry.projectId);
    expect(new Set(projects).size).toBeGreaterThan(1);
  });

  it("accepts an empty page, which is what a Principal with no rows has", () => {
    const empty = { constraints: [], omitted_projects: 0 };
    expect(decodeConstraintsPortfolioList(empty).ok).toBe(true);
    expect(decodeConstraintsPortfolioSearch(empty).ok).toBe(true);
  });

  it.each<readonly [string, unknown]>([
    ["an empty object", {}],
    ["rows sent as an object", { constraints: {} }],
    ["a row with no fields", { constraints: [{}] }],
    ["a boolean sent as a string", { constraints: [{ ...rows("constraints.portfolio_list")[0], in_my_court: "true" }] }],
    ["an unknown status", { constraints: [{ ...rows("constraints.portfolio_list")[0], status: "reopen" }] }],
    ["an unknown sync state", { constraints: [{ ...rows("constraints.portfolio_list")[0], sync_state: "partial" }] }],
    ["a dropped project_id", { constraints: [{ ...rows("constraints.portfolio_list")[0], project_id: undefined }] }],
    ["a page with no omitted-Project count", { constraints: [] }],
    ["an omitted-Project count sent as a string", { constraints: [], omitted_projects: "1" }],
    ["a fractional omitted-Project count", { constraints: [], omitted_projects: 1.5 }],
    ["a negative omitted-Project count", { constraints: [], omitted_projects: -1 }],
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
    expect(Object.keys(decoded.value.overview).sort()).toEqual([
      "asOf",
      "omittedProjects",
      "projects",
    ]);
  });

  it("accepts an empty Project collection, which is a Principal with no Projects", () => {
    const decoded = decodeConstraintsPortfolioOverview({
      overview: { projects: [], as_of: "2026-08-09T12:00:00Z", omitted_projects: 0 },
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.overview.projects).toEqual([]);
    expect(decoded.value.overview.omittedProjects).toBe(0);
  });

  it("states how many owned Projects it could not count, and never which", () => {
    const decoded = decodeConstraintsPortfolioOverview(
      payload("constraints.portfolio_overview"),
    );
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.overview.omittedProjects).toBeGreaterThan(0);
    // The omitted Projects are absent from `projects` entirely: the count is
    // larger than nothing, and no entry stands in for one.
    expect(decoded.value.overview.projects.length).toBeGreaterThan(0);
  });

  it.each<readonly [string, unknown]>([
    ["an empty object", {}],
    ["a missing overview", { overview: undefined }],
    ["the overview sent as an array", { overview: [] }],
    ["a missing projects array", { overview: { as_of: "2026-08-09T12:00:00Z" } }],
    ["projects sent as an object", { overview: { projects: {}, as_of: "2026-08-09T12:00:00Z" } }],
    ["a missing as_of", { overview: { projects: [], omitted_projects: 0 } }],
    ["an as_of sent as a number", { overview: { projects: [], as_of: 1, omitted_projects: 0 } }],
    ["a missing omitted-Project count", { overview: { projects: [], as_of: "2026-08-09T12:00:00Z" } }],
    [
      "a negative omitted-Project count",
      { overview: { projects: [], as_of: "2026-08-09T12:00:00Z", omitted_projects: -1 } },
    ],
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
