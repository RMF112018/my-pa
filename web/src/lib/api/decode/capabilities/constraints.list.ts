/**
 * `constraints.list`: one bounded page of a Project's Register.
 *
 * The rows are the whole result; truncation and the next cursor are the
 * gateway disclosure's, and nothing here reconstructs either.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintPage,
  type ConstraintListEntry,
} from "./_constraint-helpers";

export type { ConstraintListEntry };

export interface ConstraintsListResult {
  readonly constraints: readonly ConstraintListEntry[];
}

export const decodeConstraintsList: Decoder<ConstraintsListResult> = decodeConstraintPage;
