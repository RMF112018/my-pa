import { readFileSync } from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskDueControl } from "@/components/tasks/task-due-control";
import {
  addCivilDays,
  civilDayInZone,
  civilDayStartIso,
  type TaskCivilClock,
} from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const clock: TaskCivilClock = { timezone: "America/New_York", workDate: "2026-09-12" };

const TODAY_ISO = civilDayStartIso(clock.workDate, clock.timezone);
const TOMORROW_ISO = civilDayStartIso(addCivilDays(clock.workDate, 1), clock.timezone);
const OVERDUE_ISO = civilDayStartIso(addCivilDays(clock.workDate, -3), clock.timezone);
const FAR_FUTURE_ISO = civilDayStartIso("2026-12-25", clock.timezone);

const CONFLICT_COPY = "This task changed elsewhere. Review the latest version before saving.";

function trigger(): HTMLElement {
  return screen.getByRole("button", { name: /^Due, / });
}

describe("TaskDueControl", () => {
  it("renders the human due phrase for each display state", () => {
    const cases: ReadonlyArray<readonly [string | null, string]> = [
      [null, "Due, No due date"],
      [TODAY_ISO, "Due, Today"],
      [TOMORROW_ISO, "Due, Tomorrow"],
      [OVERDUE_ISO, "Due, Overdue by 3 days"],
    ];

    for (const [value, expected] of cases) {
      render(<TaskDueControl value={value} clock={clock} onChange={() => {}} />);
      expect(screen.getByRole("button", { name: expected })).toBeInTheDocument();
      cleanup();
    }

    render(<TaskDueControl value={FAR_FUTURE_ISO} clock={clock} onChange={() => {}} />);
    const name = trigger().getAttribute("aria-label") ?? "";
    expect(name).toMatch(/^Due, /);
    expect(name).toContain("25");
    expect(name).not.toContain(FAR_FUTURE_ISO);
    expect(name).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(name).not.toMatch(/T\d{2}:\d{2}/);
  });

  it("names the trigger with the human phrase", () => {
    render(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={() => {}} />);
    expect(trigger()).toHaveAccessibleName("Due, Today");
    expect(screen.getByTestId("task-due-control")).toBeInTheDocument();
  });

  it("turns Today and Tomorrow into civil-day-correct instants", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TaskDueControl value={null} clock={clock} onChange={onChange} />);

    await user.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(civilDayInZone(String(onChange.mock.calls[0][0]), clock.timezone)).toBe("2026-09-12");

    onChange.mockClear();
    await user.click(trigger());
    await user.click(screen.getByRole("button", { name: "Tomorrow" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(civilDayInZone(String(onChange.mock.calls[0][0]), clock.timezone)).toBe("2026-09-13");
  });

  it("marks the currently-applicable quick choice as current", async () => {
    const user = userEvent.setup();
    render(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={() => {}} />);

    await user.click(trigger());
    expect(screen.getByRole("button", { name: "Today" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Tomorrow" })).not.toHaveAttribute("aria-current");
  });

  it("converts a picked date into that civil day's starting instant", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TaskDueControl value={null} clock={clock} onChange={onChange} />);

    await user.click(trigger());
    await user.click(screen.getByRole("button", { name: "Pick date" }));

    const picker = screen.getByLabelText("Pick a date");
    expect(picker).toHaveAttribute("type", "date");
    await user.type(picker, "2026-10-01");

    expect(onChange).toHaveBeenCalled();
    const last = String(onChange.mock.calls[onChange.mock.calls.length - 1][0]);
    expect(civilDayInZone(last, clock.timezone)).toBe("2026-10-01");
  });

  it("offers an explicit clear intent only when a due date exists", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <TaskDueControl value={null} clock={clock} onChange={onChange} />,
    );

    await user.click(trigger());
    expect(screen.queryByRole("button", { name: "Clear due date" })).toBeNull();

    rerender(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Clear due date" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toBeNull();
  });

  it("offers no Next week choice", async () => {
    const user = userEvent.setup();
    render(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={() => {}} />);

    await user.click(trigger());
    expect(screen.queryByRole("button", { name: /next week/i })).toBeNull();
    expect(screen.getByTestId("task-due-control").textContent ?? "").not.toMatch(/next week/i);
  });

  it("closes the quick choices on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={() => {}} />);

    await user.click(trigger());
    expect(screen.getByRole("group", { name: "Due choices" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("group", { name: "Due choices" })).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("blocks intents while disabled and marks itself busy while pending", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <TaskDueControl value={TODAY_ISO} clock={clock} disabled onChange={onChange} />,
    );

    expect(trigger()).toBeDisabled();
    await user.click(trigger());
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(onChange).not.toHaveBeenCalled();

    rerender(<TaskDueControl value={TODAY_ISO} clock={clock} pending onChange={onChange} />);
    expect(trigger()).toBeDisabled();
    expect(screen.getByTestId("task-due-control")).toHaveAttribute("aria-busy", "true");
  });

  it("describes the trigger with the conflict copy when the version drifted", () => {
    render(<TaskDueControl value={TODAY_ISO} clock={clock} conflict onChange={() => {}} />);

    const describedBy = trigger().getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const note = document.getElementById(describedBy ?? "");
    expect(note).toHaveTextContent(CONFLICT_COPY);
  });

  it("makes no network call of its own", async () => {
    const source = readFileSync("src/components/tasks/task-due-control.tsx", "utf8");
    expect(source).not.toContain("fetch(");

    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const user = userEvent.setup();
    render(<TaskDueControl value={TODAY_ISO} clock={clock} onChange={() => {}} />);
    await user.click(trigger());
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
