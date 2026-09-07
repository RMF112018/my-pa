/**
 * `constraints.overview`: one Project's Constraint position, counted once.
 *
 * `averageOpenAgeBusinessDays` and `syncHealth` are the canonical names.
 * `averageOpenAge` and `synchronizationHealth` are not accepted aliases, are not
 * optional members, and are not mapped: a payload carrying either is malformed.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeConstraintOverview,
  type ConstraintOverview,
} from "./_constraint-helpers";
import { fail, pick } from "./_read-helpers";

export type { ConstraintOverview };

export interface ConstraintsOverviewResult {
  readonly overview: ConstraintOverview;
}

export const decodeConstraintsOverview: Decoder<ConstraintsOverviewResult> = (input) => {
  const known = pick(input, ["overview"]);
  if (!known.ok) return known;
  if (known.value.overview === undefined) return fail("a required object was missing");
  const overview = decodeConstraintOverview(known.value.overview);
  if (!overview.ok) return overview;
  return ok({ overview: overview.value });
};
