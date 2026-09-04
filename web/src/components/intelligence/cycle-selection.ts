/**
 * Current-cycle and history grouping from backend fields only.
 *
 * `reports.list` entries do not carry `committed_at` or `report_date`.
 * Recency on the listing itself is therefore backend list order: the first
 * listed artifact's `cycle_run_id` is current. Latest ISO `business_date`
 * wins only when every listed cycle has a resolve_set date. A partial date
 * set must not badge an older dated run as current. `Date.now()` is never
 * consulted.
 */
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";

export const MORNING_BRIEF_SET_ID = "morning_brief_inputs";

export const REPORT_IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

export interface CycleDate {
  readonly cycle_run_id: string;
  readonly business_date: string;
}

export interface CycleGroup {
  readonly cycle_run_id: string;
  readonly business_date: string | null;
  readonly items: readonly ReportListEntry[];
  readonly current: boolean;
}

export function resolveSetPayload(cycleRunId: string): {
  readonly cycle_run_id: string;
  readonly set_id: string;
} {
  return { cycle_run_id: cycleRunId, set_id: MORNING_BRIEF_SET_ID };
}

export function currentCycleRunId(
  items: readonly Pick<ReportListEntry, "cycle_run_id">[],
  dates: readonly CycleDate[] = [],
): string | null {
  if (items.length === 0) return null;
  const uniqueCycles: string[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (seen.has(item.cycle_run_id)) continue;
    seen.add(item.cycle_run_id);
    uniqueCycles.push(item.cycle_run_id);
  }
  const dateByCycle = new Map(dates.map((row) => [row.cycle_run_id, row.business_date]));
  const allDated = uniqueCycles.every((cycle) => dateByCycle.has(cycle));
  if (!allDated) {
    return uniqueCycles[0] ?? null;
  }
  let latest: { cycle: string; date: string } | null = null;
  for (const cycle of uniqueCycles) {
    const date = dateByCycle.get(cycle);
    if (date === undefined) continue;
    if (latest === null || date > latest.date) {
      latest = { cycle, date };
    }
  }
  return latest?.cycle ?? uniqueCycles[0] ?? null;
}

export function groupArtifactsByCycle(
  items: readonly ReportListEntry[],
  dates: readonly CycleDate[] = [],
): readonly CycleGroup[] {
  const current = currentCycleRunId(items, dates);
  const dateByCycle = new Map(dates.map((row) => [row.cycle_run_id, row.business_date]));
  const grouped = new Map<string, ReportListEntry[]>();
  for (const item of items) {
    const bucket = grouped.get(item.cycle_run_id);
    if (bucket) bucket.push(item);
    else grouped.set(item.cycle_run_id, [item]);
  }
  const groups: CycleGroup[] = [...grouped.entries()].map(([cycle_run_id, cycleItems]) => ({
    cycle_run_id,
    business_date: dateByCycle.get(cycle_run_id) ?? null,
    items: cycleItems,
    current: cycle_run_id === current,
  }));
  groups.sort((left, right) => {
    if (left.business_date && right.business_date && left.business_date !== right.business_date) {
      return left.business_date < right.business_date ? 1 : -1;
    }
    if (left.business_date && !right.business_date) return -1;
    if (!left.business_date && right.business_date) return 1;
    return 0;
  });
  return groups;
}

export function nonReadyRequiredCount(
  members: readonly { readonly required: boolean; readonly readiness: string }[],
): number {
  return members.filter((member) => member.required && member.readiness !== "READY").length;
}
