/**
 * `constraints.portfolio_overview`: each owned Project's position, on its own calendar.
 *
 * One entry per Project, in `project_id` order, each the exact `ConstraintOverview`
 * the single-Project overview returns and decoded by that same guard — so
 * `averageOpenAgeBusinessDays` and `syncHealth` remain the canonical names here
 * too, and a payload carrying `averageOpenAge` or `synchronizationHealth` is
 * malformed rather than mapped.
 *
 * There is deliberately **no** portfolio-wide roll-up member, and none is
 * computed here. Each Project's counts are taken against its own calendar, so a
 * total would be an addition across different days; a sum invented at this tier
 * would also be a figure no backend answer could be checked against.
 *
 * `asOf` is the read's own instant, not a per-Project date: the per-Project
 * dates are inside each entry, where the calendar that produced them is.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeConstraintOverview, type ConstraintOverview } from "./_constraint-helpers";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";

export interface ConstraintPortfolioOverview {
  readonly projects: readonly ConstraintOverview[];
  readonly asOf: string;
}

export interface ConstraintsPortfolioOverviewResult {
  readonly overview: ConstraintPortfolioOverview;
}

export const decodeConstraintsPortfolioOverview: Decoder<
  ConstraintsPortfolioOverviewResult
> = (input) => {
  const outer = pick(input, ["overview"]);
  if (!outer.ok) return outer;
  if (outer.value.overview === undefined) return fail("a required object was missing");
  const known = pick(outer.value.overview, ["projects", "as_of"]);
  if (!known.ok) return known;
  if (known.value.projects === undefined) return fail("a required array was omitted");
  const projects = decodeItems(known.value.projects, decodeConstraintOverview);
  if (!projects.ok) return projects;
  const asOf = requiredString(known.value.as_of);
  if (!asOf.ok) return asOf;
  return ok({ overview: { projects: projects.value, asOf: asOf.value } });
};
