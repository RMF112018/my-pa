/**
 * `constraints.read`: one Constraint in full, exactly as WP03 derived it.
 *
 * Every derived flag, the version, the sync summary, the relationships and the
 * evidence links are required. A payload missing one is `upstream_contract_invalid`
 * rather than a record with a silently absent field.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeConstraintView, type ConstraintView } from "./_constraint-helpers";
import { fail, pick } from "./_read-helpers";

export type { ConstraintView };

export interface ConstraintsReadResult {
  readonly constraint: ConstraintView;
}

export const decodeConstraintsRead: Decoder<ConstraintsReadResult> = (input) => {
  const known = pick(input, ["constraint"]);
  if (!known.ok) return known;
  if (known.value.constraint === undefined) return fail("a required object was missing");
  const constraint = decodeConstraintView(known.value.constraint);
  if (!constraint.ok) return constraint;
  return ok({ constraint: constraint.value });
};
