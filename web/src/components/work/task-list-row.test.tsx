import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskListRow, type TaskListRowProps } from "@/components/work/task-list-row";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import type { TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";
const TITLE = "Coordinate the quarterly review";
const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

/** A Work list projection: display seed only, deliberately carrying no version. */
const LIST_ROW: TaskRow = {
  task_id: TASK_ID,
  title: TITLE,
  lifecycle_state: "in_progress",
  priority: "p1",
  due_at: "2026-09-13T12:00:00Z",
  scheduled_at: "2026-09-14T12:00:00Z",
  deferred_until: "2026-09-15T12:00:00Z",
  archived_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
  // Deliberately present and deliberately stale: a list projection may carry a
  // version, and the row must still not treat it as write authority.
  version: 3,
};

const CANONICAL: TaskDetail = {
  ...LIST_ROW,
  description: null,
  evidence_state: "accepted",
  origin_kind: "evidence",
  origin_evidence_ref: "cap_origin0001origin0001",
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  acceptance_kind: null,
  closure_history_id: null,
  version: 4,
  commitment_id: null,
  role: null,
  project_id: null,
  situation_id: null,
  opened_at: "2026-08-20T12:00:00Z",
  closed_at: null,
};

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function gate(): { wait: Promise<void>; release: () => void } {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

/** Every Task route answered from the canonical Task; nothing else is expected. */
function stubFetch(handlers: {
  detail?: () => Response | Promise<Response>;
  transition?: (body: Record<string, unknown>) => Response | Promise<Response>;
  patch?: (body: Record<string, unknown>) => Response | Promise<Response>;
} = {}) {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const base = `/api/tasks/${TASK_ID}`;
    if (path === base && method === "GET") {
      return handlers.detail ? handlers.detail() : ok({ task: CANONICAL });
    }
    if (path === base && method === "PATCH") {
      return handlers.patch
        ? handlers.patch(body)
        : ok({ task: { ...CANONICAL, version: 5, due_at: (body.dueAt as string) ?? null } });
    }
    if (path === `${base}/transition` && method === "POST") {
      return handlers.transition
        ? handlers.transition(body)
        : ok({ task: { ...CANONICAL, version: 5, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

interface Handles {
  readonly onSelect: ReturnType<typeof vi.fn<TaskListRowProps["onSelect"]>>;
  readonly onOpen: ReturnType<typeof vi.fn<TaskListRowProps["onOpen"]>>;
  readonly onOpenActivity: ReturnType<typeof vi.fn<NonNullable<TaskListRowProps["onOpenActivity"]>>>;
  readonly onMutationConfirmed: ReturnType<
    typeof vi.fn<NonNullable<TaskListRowProps["onMutationConfirmed"]>>
  >;
}

function renderRow(props: Partial<TaskListRowProps> = {}): Handles {
  const handles: Handles = {
    onSelect: vi.fn<TaskListRowProps["onSelect"]>(),
    onOpen: vi.fn<TaskListRowProps["onOpen"]>(),
    onOpenActivity: vi.fn<NonNullable<TaskListRowProps["onOpenActivity"]>>(),
    onMutationConfirmed: vi.fn<NonNullable<TaskListRowProps["onMutationConfirmed"]>>(),
  };
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TaskListRow
        task={LIST_ROW}
        selected={false}
        clock={CLOCK}
        onSelect={handles.onSelect}
        onOpen={handles.onOpen}
        onOpenActivity={handles.onOpenActivity}
        onMutationConfirmed={handles.onMutationConfirmed}
        {...props}
      />
    </TaskRuntimeProvider>,
  );
  return handles;
}

function row(): HTMLElement {
  return screen.getByTestId("task-list-row");
}

/** The row hydrates canonically before any versioned control unlocks. */
async function hydrated(): Promise<HTMLElement> {
  await waitFor(() => {
    expect(screen.getByTestId("task-close-trigger")).not.toHaveProperty("disabled", true);
  });
  return row();
}

describe("TaskListRow", () => {
  it("speaks human Status only — no lifecycle tokens, no raw priority enums", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    const text = row().textContent ?? "";
    expect(text).not.toMatch(/in_progress|completed|cancelled|lifecycle|\bp[1-4]\b/i);
    expect(within(row()).getByRole("combobox")).toHaveProperty("value", "in_progress");
    expect(text).toContain("In progress");
    expect(text).toContain("Critical");
  });

  it("states Due in human words and shows no planning or bookkeeping timestamps", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    const text = row().textContent ?? "";
    expect(screen.getByRole("button", { name: "Due, Tomorrow" })).toBeTruthy();
    expect(text).not.toContain("Updated");
    expect(text).not.toContain("Planned work");
    expect(text).not.toContain("Available after");
    expect(text).not.toContain("2026-09-14");
  });

  it("never renders the Task ID as visible text", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(row().textContent ?? "").not.toContain(TASK_ID);
    expect(screen.queryByText(TASK_ID)).toBeNull();
  });

  it("offers a Comment affordance that opens the Activity surface", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    const comment = screen.getByRole("button", { name: `Add comment to ${TITLE}` });
    await userEvent.click(comment);

    expect(handles.onOpenActivity).toHaveBeenCalledTimes(1);
    expect(handles.onOpenActivity).toHaveBeenCalledWith(TASK_ID, TITLE, comment);
    expect(handles.onOpen).not.toHaveBeenCalled();
  });

  it("closes through a confirmation that asks for no authored text", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    await userEvent.click(screen.getByRole("button", { name: "Close Task" }));
    const confirmation = screen.getByTestId("task-close-confirmation");
    expect(confirmation.getAttribute("role")).toBe("alertdialog");
    expect(within(confirmation).queryByRole("textbox")).toBeNull();
    expect(confirmation.querySelectorAll("input, textarea").length).toBe(0);
    expect(within(confirmation).getByRole("button", { name: "Confirm Closed" })).toBeTruthy();
  });

  it("keeps Cancel under More, at lower prominence than Close", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(screen.queryByTestId("task-cancel-trigger")).toBeNull();

    const more = screen.getByRole("button", { name: `More actions for ${TITLE}` });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(more);

    const cancel = screen.getByTestId("task-cancel-trigger");
    const close = screen.getByTestId("task-close-trigger");
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(cancel.textContent).toContain("Cancel Task");
    expect(close.getAttribute("data-prominence")).toBe("primary");
    expect(cancel.getAttribute("data-prominence")).toBe("secondary");
  });

  it("selects from the checkbox without opening detail", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.click(screen.getByLabelText(`Select ${TITLE}`));
    expect(handles.onSelect).toHaveBeenCalledWith(TASK_ID);
    expect(handles.onOpen).not.toHaveBeenCalled();
    expect(handles.onOpenActivity).not.toHaveBeenCalled();
  });

  it("keeps Status, Due, Comment and Close out of selection and detail", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await userEvent.click(screen.getByRole("button", { name: "Due, Tomorrow" }));
    await userEvent.click(screen.getByRole("button", { name: `Add comment to ${TITLE}` }));
    await userEvent.click(screen.getByRole("button", { name: "Close Task" }));

    expect(handles.onOpen).not.toHaveBeenCalled();
    expect(handles.onSelect).not.toHaveBeenCalled();
  });

  it("opens detail from the title and hands over its own element as the trigger", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    const title = screen.getByTestId("task-list-row-title");
    await userEvent.click(title);

    expect(handles.onOpen).toHaveBeenCalledTimes(1);
    expect(handles.onOpen).toHaveBeenCalledWith("task", TASK_ID, TITLE, title);
    expect(handles.onSelect).not.toHaveBeenCalled();
  });

  it("canonical-hydrates at the first write instead of trusting the row's own version", async () => {
    /*
      The list projection carries a `version`, and it is not write authority: it
      is a read of some earlier moment, so between the list load and this click
      the Task may have moved. The row must therefore reach the canonical read
      before it writes, and send that version — while still leaving the control
      operable, because locking every row until it hydrated would mean one detail
      read per row for a list the user may never touch.
    */
    const expectedVersions: unknown[] = [];
    stubFetch({
      detail: async () => ok({ task: { ...CANONICAL, version: 9 } }),
      transition: async (body) => {
        expectedVersions.push((body as { expectedVersion?: unknown }).expectedVersion);
        return ok({ task: { ...CANONICAL, version: 10, lifecycle_state: "waiting" } });
      },
    });
    renderRow();

    // Operable before any hydration has happened.
    const status = within(row()).getByRole("combobox");
    expect(status).toHaveProperty("disabled", false);

    await userEvent.selectOptions(status, "waiting");

    await waitFor(() => expect(expectedVersions.length).toBe(1));
    // The canonical version, never the projection's stale one.
    expect(expectedVersions).toEqual([9]);
    expect(expectedVersions).not.toContain(LIST_ROW.version);
  });

  it("names every control in the context of this Task", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(screen.getByLabelText(`Select ${TITLE}`)).toBeTruthy();
    expect(screen.getByRole("group", { name: `Change status for ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("group", { name: `Change due date for ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("button", { name: `Add comment to ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("group", { name: `Close ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("button", { name: `More actions for ${TITLE}` })).toBeTruthy();
  });

  it("marks the row busy while a write is in flight", async () => {
    const transition = gate();
    stubFetch({
      transition: async (body) => {
        await transition.wait;
        return ok({ task: { ...CANONICAL, version: 5, lifecycle_state: body.toState } });
      },
    });
    renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    transition.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
  });

  it("locks the row from the activation, not from the write", async () => {
    /*
      A list row reaches the canonical Task on demand, so an activation can spend
      a real round trip before anything is sent. While that read was in flight the
      controls stayed live, so a second activation got through — and the
      coordinator refused it without a word, leaving the user pressing a control
      twice and told nothing either time.
    */
    const detail = gate();
    stubFetch({
      detail: async () => {
        await detail.wait;
        return ok({ task: CANONICAL });
      },
    });
    renderRow();
    // Close is offered immediately; hydration happens at the first write.
    await userEvent.click(await screen.findByTestId("task-close-trigger"));
    await userEvent.click(await screen.findByTestId("task-close-confirm"));

    // The canonical read has not answered yet, and the row is already busy.
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    detail.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
  });

  it("unlocks the row when the canonical read it needs cannot be had", async () => {
    /*
      The row locks from the activation, before the canonical Task it needs has
      been read. If that read fails there is no write to settle and nothing else
      will clear the lock — so the unlock on that path is the only thing standing
      between a refused read and a row whose every control is disabled for good,
      with no way back short of a reload.
    */
    stubFetch({
      detail: () =>
        new Response(JSON.stringify({ error: { message: "unavailable", code: "unavailable" } }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
    });
    renderRow();

    await userEvent.click(await screen.findByTestId("task-close-trigger"));
    await userEvent.click(await screen.findByTestId("task-close-confirm"));

    // The read is refused, and the row comes back under the user's hand.
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
    await waitFor(() =>
      expect(screen.getByTestId("task-close-trigger")).not.toHaveProperty("disabled", true),
    );
  });

  it("gives focus back to the row when a write is refused after focus was lost", async () => {
    /*
      A keyboard user starts a write from within the row. Browsers drop focus to
      the document body when the element holding it is disabled, which is exactly
      what locking does to the control they just operated. If the write is then
      refused the Task does not move, the list does not change, and nothing else
      will put the user back — they are left on the body with the row still in
      front of them.

      jsdom will not blur a disabled element, so the disabling itself cannot be
      simulated here; the loss is driven through an element in the row that jsdom
      will blur, which exercises the same hold-and-return path.
    */
    const refusal = gate();
    stubFetch({
      transition: async () => {
        await refusal.wait;
        return new Response(JSON.stringify({ error: { message: "nope", code: "invalid" } }), {
          status: 400,
          headers: { "content-type": "application/json" },
        });
      },
    });
    renderRow();
    await hydrated();

    const anchor = within(row()).getByRole("link");
    anchor.focus();
    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    // Focus is lost to the body while the write is in flight.
    anchor.focus();
    anchor.blur();
    expect(document.activeElement).toBe(document.body);

    refusal.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());

    // The refusal left the Task where it was, and the user back in the row.
    expect(document.activeElement).not.toBe(document.body);
    expect(row().contains(document.activeElement)).toBe(true);
  });

  it("reports a confirmed mutation so Work can move the row", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");

    await waitFor(() => {
      expect(handles.onMutationConfirmed).toHaveBeenCalledWith({ taskId: TASK_ID, kind: "status" });
    });
  });
});
