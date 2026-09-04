/**
 * Current vs historical grouping from backend currency fields.
 *
 * Assignment and relationship rows already carry `is_current` and a status/state
 * the Python plane computed. This module reads those fields. It does not
 * re-derive currency from effective dates or the clock.
 */

export interface DirectedCurrency {
  readonly is_current: boolean | null;
  readonly status?: "active" | "ended" | "superseded";
  readonly state?: "active" | "ended" | "superseded";
}

export interface LifecycleCurrency {
  readonly state: "active" | "retired" | "superseded";
}

export interface ParticipationCurrency extends LifecycleCurrency {
  readonly relationship_status_code: "active" | "completed" | "terminated" | "on_hold" | "unresolved";
}

/** Trust `is_current` when the plane supplied it; otherwise the lifecycle flag. */
export function directedIsCurrent(row: DirectedCurrency): boolean {
  if (row.is_current === true) return true;
  if (row.is_current === false) return false;
  const lifecycle = row.status ?? row.state;
  return lifecycle === "active";
}

export function lifecycleIsCurrent(row: LifecycleCurrency): boolean {
  return row.state === "active";
}

export function participationIsCurrent(row: ParticipationCurrency): boolean {
  if (row.state !== "active") return false;
  return row.relationship_status_code !== "completed" && row.relationship_status_code !== "terminated";
}

export function partitionByCurrency<T>(
  rows: readonly T[],
  isCurrent: (row: T) => boolean,
): { readonly current: readonly T[]; readonly historical: readonly T[] } {
  const current: T[] = [];
  const historical: T[] = [];
  for (const row of rows) {
    if (isCurrent(row)) current.push(row);
    else historical.push(row);
  }
  return { current, historical };
}
