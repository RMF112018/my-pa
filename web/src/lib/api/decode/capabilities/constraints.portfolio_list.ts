/**
 * `constraints.portfolio_list`: one bounded page across every owned Project.
 *
 * The rows are the exact `constraints.list` shape — a portfolio row is a
 * Register row, not a second projection of it — so the Register's own guard
 * decodes them and nothing here is a third copy of it. Truncation and the next
 * cursor are the gateway disclosure's; a portfolio page can be short because it
 * filled, or because the Principal owns more Projects than one read spans, and
 * neither fact is reconstructed here from the rows.
 */
import type { Decoder } from "../types";
import { decodeConstraintPage, type ConstraintListEntry } from "./_constraint-helpers";

export interface ConstraintsPortfolioListResult {
  readonly constraints: readonly ConstraintListEntry[];
}

export const decodeConstraintsPortfolioList: Decoder<ConstraintsPortfolioListResult> =
  decodeConstraintPage;
