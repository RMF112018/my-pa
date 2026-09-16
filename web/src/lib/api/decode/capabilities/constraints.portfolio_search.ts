/**
 * `constraints.portfolio_search`: the same portfolio page, narrowed by one term.
 *
 * Decoded by the guard the portfolio Register and the exact-Project Register
 * already share, for the reason `constraints.search` states: a search result
 * that decoded differently would be a second answer about the same records.
 */
import type { Decoder } from "../types";
import { decodeConstraintPage, type ConstraintListEntry } from "./_constraint-helpers";

export interface ConstraintsPortfolioSearchResult {
  readonly constraints: readonly ConstraintListEntry[];
}

export const decodeConstraintsPortfolioSearch: Decoder<ConstraintsPortfolioSearchResult> =
  decodeConstraintPage;
