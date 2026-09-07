/**
 * `constraints.search`: the same Register page, narrowed by one term.
 *
 * The same rows and the same derived flags the Register returns, decoded by the
 * same guard: a search result that decoded differently would be a second answer
 * about the same records.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintPage,
  type ConstraintListEntry,
} from "./_constraint-helpers";

export interface ConstraintsSearchResult {
  readonly constraints: readonly ConstraintListEntry[];
}

export const decodeConstraintsSearch: Decoder<ConstraintsSearchResult> = decodeConstraintPage;
