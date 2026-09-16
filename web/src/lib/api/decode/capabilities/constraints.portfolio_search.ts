/**
 * `constraints.portfolio_search`: the same portfolio page, narrowed by one term.
 *
 * Decoded by the guard the portfolio Register already uses, for the reason
 * `constraints.search` states: a search result that decoded differently would
 * be a second answer about the same records. A narrowed portfolio is no less
 * partial than an unnarrowed one, so `omittedProjects` is required here too.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintPortfolioPage,
  type ConstraintListEntry,
} from "./_constraint-helpers";

export interface ConstraintsPortfolioSearchResult {
  readonly constraints: readonly ConstraintListEntry[];
  readonly omittedProjects: number;
}

export const decodeConstraintsPortfolioSearch: Decoder<ConstraintsPortfolioSearchResult> =
  decodeConstraintPortfolioPage;
