/**
 * `constraints.portfolio_overview`: each owned Project's position, on its own calendar.
 *
 * One entry per Project, in `project_id` order, each the exact `ConstraintOverview`
 * the single-Project overview returns and decoded by that same guard — so
 * `averageOpenAgeBusinessDays` and `syncHealth` remain the canonical names here
 * too, and a payload carrying `averageOpenAge` or `synchronizationHealth` is
 * malformed rather than mapped. `projectName` is optional on that shared shape
 * (the single-Project overview never sends it), and `requirePortfolioProjectName`
 * is where this capability requires it to be a non-null string on every entry.
 *
 * There is deliberately **no** portfolio-wide roll-up member, and none is
 * computed here. Each Project's counts are taken against its own calendar, so a
 * total would be an addition across different days; a sum invented at this tier
 * would also be a figure no backend answer could be checked against.
 *
 * `asOf` is the read's own instant, not a per-Project date: the per-Project
 * dates are inside each entry, where the calendar that produced them is.
 *
 * `omittedProjects` is how many owned Projects could not be counted at all —
 * no Constraint settings row, or a stored zone the backend cannot load — and
 * so are absent from `projects` rather than counted on a substituted calendar.
 * It sits inside the overview because the overview is this read's scope object,
 * alongside the `asOf` those Projects were read at, and it is a count and never
 * an identity.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeConstraintOverview,
  decodeOmittedProjects,
  requirePortfolioProjectName,
  type ConstraintOverview,
} from "./_constraint-helpers";
import { decodeItems, fail, pick, requiredString } from "./_read-helpers";

export interface ConstraintPortfolioOverview {
  readonly projects: readonly ConstraintOverview[];
  readonly asOf: string;
  readonly omittedProjects: number;
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
  const known = pick(outer.value.overview, ["projects", "as_of", "omitted_projects"]);
  if (!known.ok) return known;
  if (known.value.projects === undefined) return fail("a required array was omitted");
  const projects = decodeItems(known.value.projects, (item) => {
    const entry = decodeConstraintOverview(item);
    if (!entry.ok) return entry;
    return requirePortfolioProjectName(entry.value);
  });
  if (!projects.ok) return projects;
  const asOf = requiredString(known.value.as_of);
  if (!asOf.ok) return asOf;
  const omittedProjects = decodeOmittedProjects(known.value.omitted_projects);
  if (!omittedProjects.ok) return omittedProjects;
  return ok({
    overview: {
      projects: projects.value,
      asOf: asOf.value,
      omittedProjects: omittedProjects.value,
    },
  });
};
