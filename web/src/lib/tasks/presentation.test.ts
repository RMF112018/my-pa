import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { TaskDetail, TaskLifecycle, TaskPriority } from "@/contracts/work";
import {
  addCivilDays,
  civilDayEndIso,
  civilDayInZone,
  civilDayOffset,
  civilDayStartIso,
  formatTaskDue,
  formatTaskPlanningDate,
  formatTaskPriority,
  formatTaskStatus,
  isActiveTaskStatus,
  isTerminalTaskStatus,
  NO_DUE_DATE_LABEL,
  NO_PRIORITY_LABEL,
  TASK_ACTIVE_STATUSES,
  TASK_STATUS_LABELS,
  terminalTaskSummary,
  toTaskPresentationModel,
  type TaskCivilClock,
} from "./presentation";

const CLOCK: TaskCivilClock = { timezone: "America/New_York", workDate: "2026-09-12" };

function isoOn(workDate: string, timezone = CLOCK.timezone): string {
  return civilDayStartIso(workDate, timezone);
}

const LIFECYCLES: readonly TaskLifecycle[] = [
  "open",
  "in_progress",
  "waiting",
  "blocked",
  "completed",
  "cancelled",
];

describe("task status language", () => {
  it("maps every lifecycle state to its accepted human label", () => {
    expect(formatTaskStatus("open")).toBe("Open");
    expect(formatTaskStatus("in_progress")).toBe("In progress");
    expect(formatTaskStatus("waiting")).toBe("Waiting");
    expect(formatTaskStatus("blocked")).toBe("Blocked");
    expect(formatTaskStatus("completed")).toBe("Closed");
    expect(formatTaskStatus("cancelled")).toBe("Cancelled");
  });

  it("covers the whole closed lifecycle set with no raw token leaking into a label", () => {
    for (const state of LIFECYCLES) {
      const label = TASK_STATUS_LABELS[state];
      expect(label).toBeTruthy();
      expect(label).not.toMatch(/_/);
    }
  });

  it("offers exactly the four non-terminal statuses as ordinary Status choices", () => {
    expect([...TASK_ACTIVE_STATUSES]).toEqual(["open", "in_progress", "waiting", "blocked"]);
    expect(TASK_ACTIVE_STATUSES).not.toContain("completed");
    expect(TASK_ACTIVE_STATUSES).not.toContain("cancelled");
  });

  it("classifies terminal and active states", () => {
    expect(isTerminalTaskStatus("completed")).toBe(true);
    expect(isTerminalTaskStatus("cancelled")).toBe(true);
    expect(isTerminalTaskStatus("open")).toBe(false);
    expect(isActiveTaskStatus("blocked")).toBe(true);
    expect(isActiveTaskStatus("completed")).toBe(false);
  });

  it("summarises terminal state in product language and stays silent while active", () => {
    expect(terminalTaskSummary("completed")).toBe("This task is closed.");
    expect(terminalTaskSummary("cancelled")).toBe("This task is cancelled.");
    expect(terminalTaskSummary("open")).toBeNull();
  });
});

describe("task priority language", () => {
  it("maps p1..p4 to Critical/High/Medium/Low", () => {
    const cases: ReadonlyArray<readonly [TaskPriority, string]> = [
      ["p1", "Critical"],
      ["p2", "High"],
      ["p3", "Medium"],
      ["p4", "Low"],
    ];
    for (const [token, label] of cases) {
      expect(formatTaskPriority(token)).toBe(label);
    }
  });

  it("never silently treats an absent priority as Low", () => {
    expect(formatTaskPriority(null)).toBe(NO_PRIORITY_LABEL);
    expect(formatTaskPriority(undefined)).toBe(NO_PRIORITY_LABEL);
    expect(formatTaskPriority(null)).not.toBe("Low");
  });
});

describe("civil-day arithmetic", () => {
  it("reads the civil day in the caller's zone, not in UTC", () => {
    // 03:30Z on 2026-09-13 is still 2026-09-12 in New York.
    expect(civilDayInZone("2026-09-13T03:30:00Z", "America/New_York")).toBe("2026-09-12");
    expect(civilDayInZone("2026-09-13T03:30:00Z", "UTC")).toBe("2026-09-13");
  });

  it("does not answer by truncating a UTC timestamp", () => {
    const iso = "2026-09-13T03:30:00Z";
    expect(civilDayInZone(iso, "America/New_York")).not.toBe(iso.slice(0, 10));
  });

  it("counts whole civil days in both directions", () => {
    expect(civilDayOffset("2026-09-12", "2026-09-12")).toBe(0);
    expect(civilDayOffset("2026-09-12", "2026-09-13")).toBe(1);
    expect(civilDayOffset("2026-09-12", "2026-09-09")).toBe(-3);
  });

  it("shifts civil dates across a month boundary", () => {
    expect(addCivilDays("2026-09-30", 1)).toBe("2026-10-01");
    expect(addCivilDays("2026-01-01", -1)).toBe("2025-12-31");
  });

  it("resolves the instant a civil day begins in a zone", () => {
    const start = civilDayStartIso("2026-09-12", "America/New_York");
    expect(civilDayInZone(start, "America/New_York")).toBe("2026-09-12");
    // Midnight in New York on that date is 04:00Z.
    expect(start).toBe("2026-09-12T04:00:00.000Z");
  });

  it("resolves civil day starts across a DST transition", () => {
    for (const day of ["2026-03-07", "2026-03-08", "2026-03-09", "2026-11-01", "2026-11-02"]) {
      const start = civilDayStartIso(day, "America/New_York");
      expect(civilDayInZone(start, "America/New_York")).toBe(day);
    }
  });

  it("rejects unreadable input rather than guessing", () => {
    expect(() => civilDayInZone("not-a-date", "UTC")).toThrow(TypeError);
    expect(() => addCivilDays("not-a-date", 1)).toThrow(TypeError);
  });
});

describe("due presentation", () => {
  it("states an absent due date", () => {
    const due = formatTaskDue(null, CLOCK);
    expect(due.phrase).toBe(NO_DUE_DATE_LABEL);
    expect(due.tone).toBe("none");
    expect(due.iso).toBeNull();
  });

  it("says Today for the current civil day", () => {
    const due = formatTaskDue(isoOn("2026-09-12"), CLOCK);
    expect(due.phrase).toBe("Today");
    expect(due.tone).toBe("today");
  });

  it("says Tomorrow for the next civil day", () => {
    const due = formatTaskDue(isoOn("2026-09-13"), CLOCK);
    expect(due.phrase).toBe("Tomorrow");
    expect(due.tone).toBe("tomorrow");
  });

  it("counts overdue civil days with correct singular and plural", () => {
    expect(formatTaskDue(isoOn("2026-09-11"), CLOCK).phrase).toBe("Overdue by 1 day");
    const older = formatTaskDue(isoOn("2026-09-09"), CLOCK);
    expect(older.phrase).toBe("Overdue by 3 days");
    expect(older.tone).toBe("overdue");
    expect(older.overdueDays).toBe(3);
  });

  it("renders a concise localized date further out, never a raw timestamp", () => {
    const due = formatTaskDue(isoOn("2026-11-20"), CLOCK);
    expect(due.tone).toBe("scheduled");
    expect(due.phrase).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(due.phrase).not.toMatch(/T\d{2}:\d{2}/);
    expect(due.phrase).not.toMatch(/Z$/);
  });

  it("classifies a late-evening UTC timestamp by the caller's civil day", () => {
    // 2026-09-13T02:00:00Z is 22:00 on 2026-09-12 in New York: still Today there.
    expect(formatTaskDue("2026-09-13T02:00:00Z", CLOCK).phrase).toBe("Today");
    expect(formatTaskDue("2026-09-13T02:00:00Z", { timezone: "UTC", workDate: "2026-09-12" }).phrase).toBe(
      "Tomorrow",
    );
  });

  it("omits an explicit time unless the caller opts in", () => {
    const iso = "2026-09-12T17:30:00Z";
    expect(formatTaskDue(iso, CLOCK).phrase).toBe("Today");
    expect(formatTaskDue(iso, CLOCK, { withExplicitTime: true }).phrase).toMatch(/^Today at /);
  });
});

describe("planning date presentation", () => {
  it("states the absence a caller supplies", () => {
    expect(formatTaskPlanningDate(null, CLOCK, "Not planned")).toBe("Not planned");
  });

  it("uses relative civil-day language near today", () => {
    expect(formatTaskPlanningDate(isoOn("2026-09-12"), CLOCK, "—")).toBe("Today");
    expect(formatTaskPlanningDate(isoOn("2026-09-13"), CLOCK, "—")).toBe("Tomorrow");
    expect(formatTaskPlanningDate(isoOn("2026-09-11"), CLOCK, "—")).toBe("Yesterday");
  });
});

function task(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    task_id: "tsk_01HZY",
    title: "Send the revised scope",
    lifecycle_state: "in_progress",
    priority: "p2",
    due_at: isoOn("2026-09-12"),
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-10T12:00:00Z",
    version: 4,
    description: "A description.",
    evidence_state: "accepted",
    origin_kind: "direct_principal",
    origin_evidence_ref: null,
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    commitment_id: null,
    role: null,
    project_id: null,
    situation_id: null,
    opened_at: "2026-09-01T12:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

describe("task presentation model", () => {
  it("carries human status, priority and due language", () => {
    const model = toTaskPresentationModel(task(), { clock: CLOCK, canMutate: true });
    expect(model.statusLabel).toBe("In progress");
    expect(model.priorityLabel).toBe("High");
    expect(model.hasPriority).toBe(true);
    expect(model.due.phrase).toBe("Today");
    expect(model.active).toBe(true);
    expect(model.terminal).toBe(false);
  });

  it("reports no priority rather than inventing Low", () => {
    const model = toTaskPresentationModel(task({ priority: null }), { clock: CLOCK });
    expect(model.priorityLabel).toBe(NO_PRIORITY_LABEL);
    expect(model.hasPriority).toBe(false);
  });

  it("marks terminal tasks and summarises them in product language", () => {
    const model = toTaskPresentationModel(task({ lifecycle_state: "completed" }), { clock: CLOCK });
    expect(model.statusLabel).toBe("Closed");
    expect(model.terminal).toBe(true);
    expect(model.terminalSummary).toBe("This task is closed.");
  });

  it("refuses mutation authority without a trustworthy version", () => {
    const projection = { ...task(), version: undefined } as unknown as TaskDetail;
    const seeded = toTaskPresentationModel(projection, { clock: CLOCK, canMutate: true });
    expect(seeded.version).toBeNull();
    expect(seeded.canMutate).toBe(false);
  });

  it("refuses mutation authority when the caller does not claim a canonical snapshot", () => {
    const model = toTaskPresentationModel(task(), { clock: CLOCK });
    expect(model.version).toBe(4);
    expect(model.canMutate).toBe(false);
  });

  it("grants mutation authority only with both a canonical claim and a version", () => {
    const model = toTaskPresentationModel(task(), { clock: CLOCK, canMutate: true });
    expect(model.canMutate).toBe(true);
  });
});

describe("presentation module boundaries", () => {
  it("performs no I/O and imports no network module", () => {
    const source = readFileSync(resolve(process.cwd(), "src/lib/tasks/presentation.ts"), "utf8");
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/from "@\/lib\/api\//);
    expect(source).not.toMatch(/from "@\/lib\/task\//);
    expect(source).not.toMatch(/from "@\/components\//);
    expect(source).not.toMatch(/XMLHttpRequest|WebSocket/);
  });
});

describe("civil day end (WP-TUX-04)", () => {
  const NY = "America/New_York";

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Wall-clock parts of an instant in a zone, read back independently of the helper. */
  function wallClock(iso: string, timezone: string) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).formatToParts(new Date(iso));
    const read = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? "-1");
    return {
      hour: read("hour") % 24,
      minute: read("minute"),
      second: read("second"),
    };
  }

  it("ends an ordinary day at the zone's own 23:59:59 and round-trips to the same civil date", () => {
    const result = civilDayEndIso("2026-09-15", NY);
    expect(result).toBe("2026-09-16T03:59:59.000Z");
    expect(civilDayInZone(result, NY)).toBe("2026-09-15");
  });

  it("stays 23:59:59 local across the spring-forward boundary", () => {
    const result = civilDayEndIso("2026-03-08", NY);
    expect(result).toBe("2026-03-09T03:59:59.000Z");
    expect(civilDayInZone(result, NY)).toBe("2026-03-08");
    expect(wallClock(result, NY)).toEqual({ hour: 23, minute: 59, second: 59 });
  });

  it("stays 23:59:59 local across the fall-back boundary", () => {
    const result = civilDayEndIso("2026-11-01", NY);
    expect(result).toBe("2026-11-02T04:59:59.000Z");
    expect(civilDayInZone(result, NY)).toBe("2026-11-01");
    expect(wallClock(result, NY)).toEqual({ hour: 23, minute: 59, second: 59 });
  });

  it("keeps a UTC-positive zone's end of day on its own UTC day, never later", () => {
    // Tokyo is UTC+9 year round: 23:59:59 local is 14:59:59 the same UTC day.
    const tokyo = civilDayEndIso("2026-06-15", "Asia/Tokyo");
    expect(tokyo).toBe("2026-06-15T14:59:59.000Z");
    expect(civilDayInZone(tokyo, "Asia/Tokyo")).toBe("2026-06-15");
    // The instant is never on a UTC day after the civil date it ends.
    expect(tokyo.slice(0, 10) <= "2026-06-15").toBe(true);

    // Sydney observes DST; both offsets keep the instant on the same UTC day,
    // and the start of the same civil day does land on the previous UTC day.
    const sydneyWinter = civilDayEndIso("2026-06-15", "Australia/Sydney");
    expect(sydneyWinter).toBe("2026-06-15T13:59:59.000Z");
    expect(civilDayStartIso("2026-06-15", "Australia/Sydney").slice(0, 10)).toBe("2026-06-14");
    const sydneySummer = civilDayEndIso("2026-12-15", "Australia/Sydney");
    expect(sydneySummer).toBe("2026-12-15T12:59:59.000Z");
    expect(civilDayInZone(sydneySummer, "Australia/Sydney")).toBe("2026-12-15");
  });

  it("pushes a UTC-negative zone's end of day onto the next UTC day", () => {
    const result = civilDayEndIso("2026-06-15", "America/Los_Angeles");
    expect(result).toBe("2026-06-16T06:59:59.000Z");
    expect(result.slice(0, 10)).toBe("2026-06-16");
    expect(civilDayInZone(result, "America/Los_Angeles")).toBe("2026-06-15");
  });

  it("handles a leap day", () => {
    const result = civilDayEndIso("2028-02-29", NY);
    expect(result).toBe("2028-03-01T04:59:59.000Z");
    expect(civilDayInZone(result, NY)).toBe("2028-02-29");
    expect(wallClock(result, NY)).toEqual({ hour: 23, minute: 59, second: 59 });
  });

  it("handles a year boundary on both sides", () => {
    const lastDay = civilDayEndIso("2026-12-31", NY);
    expect(lastDay).toBe("2027-01-01T04:59:59.000Z");
    expect(civilDayInZone(lastDay, NY)).toBe("2026-12-31");

    const firstDay = civilDayEndIso("2027-01-01", NY);
    expect(firstDay).toBe("2027-01-02T04:59:59.000Z");
    expect(civilDayInZone(firstDay, NY)).toBe("2027-01-01");
  });

  it("never reads the current clock", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2001-05-04T01:02:03.000Z"));
    const early = civilDayEndIso("2026-09-15", NY);
    vi.setSystemTime(new Date("2099-12-31T22:11:00.000Z"));
    const late = civilDayEndIso("2026-09-15", NY);
    expect(late).toBe(early);
    expect(late).toBe("2026-09-16T03:59:59.000Z");
  });

  it("is strictly later than the start of the same civil day, on the same civil day", () => {
    for (const workDate of ["2026-03-08", "2026-06-15", "2026-11-01", "2026-12-31"]) {
      const start = civilDayStartIso(workDate, NY);
      const end = civilDayEndIso(workDate, NY);
      expect(Date.parse(end)).toBeGreaterThan(Date.parse(start));
      expect(civilDayInZone(start, NY)).toBe(workDate);
      expect(civilDayInZone(end, NY)).toBe(workDate);
    }
  });

  it("refuses an unreadable civil date", () => {
    expect(() => civilDayEndIso("not-a-date", NY)).toThrow(TypeError);
    expect(() => civilDayEndIso("", NY)).toThrow(TypeError);
    expect(() => civilDayEndIso("2026-02-31", NY)).toThrow(TypeError);
    expect(() => civilDayEndIso("2026-13-01", NY)).toThrow(TypeError);
    expect(() => civilDayEndIso("2026-9-15", NY)).toThrow(TypeError);
  });

  it("really is 23:59:59 on the local wall clock in every zone tested", () => {
    const cases: readonly (readonly [string, string])[] = [
      ["2026-09-15", NY],
      ["2026-06-15", "America/Los_Angeles"],
      ["2026-06-15", "Asia/Tokyo"],
      ["2026-12-15", "Australia/Sydney"],
      ["2028-02-29", "UTC"],
      ["2026-12-31", "Europe/London"],
    ];
    for (const [workDate, timezone] of cases) {
      const result = civilDayEndIso(workDate, timezone);
      expect(wallClock(result, timezone)).toEqual({ hour: 23, minute: 59, second: 59 });
      expect(civilDayInZone(result, timezone)).toBe(workDate);
    }
  });
});
