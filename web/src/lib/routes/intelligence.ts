/**
 * Canonical Intelligence routes. Frozen for WP12.
 *
 * There is no `/intelligence/brief/[date]`: business date comes from
 * `reports.resolve_set`, and `reports.latest` requires a `cycle_run_id`
 * discovered from `reports.list`. The browser clock is not a run identity.
 */
export function intelligenceHome(): string {
  return "/intelligence";
}

export function intelligenceReport(reportId: string): string {
  return `/intelligence/reports/${encodeURIComponent(reportId)}`;
}

export function intelligenceHistory(cycleRunId?: string): string {
  if (cycleRunId === undefined || cycleRunId.length === 0) {
    return "/intelligence/history";
  }
  return `/intelligence/history?cycleRunId=${encodeURIComponent(cycleRunId)}`;
}
