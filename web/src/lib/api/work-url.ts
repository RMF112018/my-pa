export const WORK_VIEWS = ["today", "upcoming", "waiting", "blocked", "all-open", "completed", "commitments"] as const;
export type WorkView = (typeof WORK_VIEWS)[number];
export type ArchiveMode = "exclude" | "only";
export type CommitmentFilter = "all-open" | "waiting-on" | "closed" | "all";

export interface WorkUrlState {
  readonly view: WorkView;
  readonly q: string;
  readonly cursor: string;
  readonly tz: string;
  readonly archived: ArchiveMode;
  readonly commitment: CommitmentFilter;
}

function first(value: string | readonly string[] | undefined) {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

function validTimezone(value: string) {
  if (!value || value.length > 64 || !/^[A-Za-z0-9_+\/-]+$/.test(value)) return "";
  try { new Intl.DateTimeFormat("en", { timeZone: value }).format(); return value; } catch { return ""; }
}

export function parseWorkUrlState(parameters: Record<string, string | readonly string[] | undefined>): WorkUrlState {
  const view = first(parameters.view);
  const archived = first(parameters.archived);
  const commitment = first(parameters.commitment);
  return {
    view: WORK_VIEWS.includes(view as WorkView) ? view as WorkView : "today",
    q: first(parameters.q),
    cursor: first(parameters.cursor),
    tz: validTimezone(first(parameters.tz)),
    archived: archived === "only" ? "only" : "exclude",
    commitment: ["all-open", "waiting-on", "closed", "all"].includes(commitment)
      ? commitment as CommitmentFilter
      : "all-open",
  };
}
