/**
 * `constraints.portfolio_list`: one bounded page across every owned Project.
 *
 * The rows are the exact `constraints.list` shape — a portfolio row is a
 * Register row, not a second projection of it — so the Register's own guard
 * decodes them and nothing here is a third copy of it. Truncation and the next
 * cursor are the gateway disclosure's; a portfolio page can be short because it
 * filled, because the Principal owns more Projects than one read spans, or
 * because some owned Projects could not contribute at all, and none of those
 * facts is reconstructed here from the rows.
 *
 * `omittedProjects` is the one thing the *result* carries about being partial:
 * how many owned Projects had no usable Constraint calendar and were therefore
 * left out. It is a count and never an identity.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintPortfolioPage,
  type ConstraintListEntry,
} from "./_constraint-helpers";

export interface ConstraintsPortfolioListResult {
  readonly constraints: readonly ConstraintListEntry[];
  readonly omittedProjects: number;
}

export const decodeConstraintsPortfolioList: Decoder<ConstraintsPortfolioListResult> =
  decodeConstraintPortfolioPage;
